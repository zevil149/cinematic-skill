"""Voice providers behind one interface, for the per-edition voice framework (voice.py).

A provider turns one request (spoken text in one language, a voice, settings) into a WAV file.
Providers that return reliable word timings can read a whole section in one go (smoother
delivery); voice.py then cuts it into line segments. The others read line by line.

  mock      deterministic test audio for any language: no sound engine, no network, free
  espeak    espeak-ng, the free local scratch voice (en-us for English, hi for Hindi)
  command     any local TTS tool: "cmd": "mytts --in {txt} --out {out} --voice {voice} --lang {lang}"
  elevenlabs  ElevenLabs, the English voice (paid): word timings, so whole sections at a time
  sarvam      Sarvam AI Bulbul, the Hindi voice (paid): line by line

A provider marked paid never runs without the spend guard in voice.py: an estimate, a cap ($5 a
run by default) and an explicit --confirm-cost. API keys come from the environment only
(ELEVENLABS_API_KEY, SARVAM_API_KEY), are read at the moment of the request, and are never
written to voice.json, a manifest, the spend log, an error message or the output. Standard
library only.
"""
import array
import base64
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave

import lang as langs

SAMPLE_RATE = 22050


class ProviderError(Exception):
    pass


class Result:
    """What a provider made: the WAV, its duration, word timings if the provider knows them
    (seconds from the start of the file), and the characters it would bill."""

    def __init__(self, path, duration, words=None, chars=0):
        self.path, self.duration, self.words, self.chars = pathlib.Path(path), duration, words, chars


class Provider:
    name = ""
    paid = False                 # a paid provider needs the spend guard and, for Hindi, a native-speaker review
    timestamps = False           # returns reliable word timings, so a whole section can be read at once
    langs = ()                   # language codes it can speak; () means any
    price_per_1k_chars = 0.0     # USD, for the estimate

    def __init__(self, config=None):
        self.config = dict(config or {})

    def supports(self, code):
        return not self.langs or code in self.langs

    def default_voice(self, code):
        return ""

    def estimate_cost(self, chars):
        return chars / 1000.0 * self.price_per_1k_chars if self.paid else 0.0     # exact; rounded only for display

    max_chars = 0                # the most one request may carry; 0 means no limit
    key_env = ""                 # the environment variable that holds the API key, for API providers

    def check(self, cfg, code):
        """Problems with this voice.json for this language, before anything is sent: [] when fine."""
        return []

    def describe_cost(self, cost):
        return f"${cost:.2f}"

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        raise NotImplementedError


def write_wav(path, samples, rate=SAMPLE_RATE):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(array.array("h", samples).tobytes())


def wav_info(path):
    """(duration, rate, rms 0..1, peak 0..1) of a 16-bit PCM WAV, standard library only."""
    with wave.open(str(path), "rb") as w:
        rate, n, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        data = w.readframes(n)
    if width != 2:
        raise ProviderError(f"{path}: {8 * width}-bit WAV; 16-bit expected")
    a = array.array("h"); a.frombytes(data)
    if not a:
        return 0.0, rate, 0.0, 0.0
    step = max(1, len(a) // 200000)                       # a sample of the frames is enough for levels
    sub = a[::step]
    rms = math.sqrt(sum(x * x for x in sub) / len(sub)) / 32768.0
    peak = max(abs(x) for x in sub) / 32768.0
    return n / float(rate), rate, rms, peak


def cut_wav(src, dst, t0, t1):
    with wave.open(str(src), "rb") as w:
        rate, n = w.getframerate(), w.getnframes()
        params = w.getparams()
        a, b = max(0, int(t0 * rate)), min(n, int(t1 * rate))
        w.setpos(a)
        frames = w.readframes(max(0, b - a))
    pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as o:
        o.setparams(params)
        o.writeframes(frames)


def to_wav(src, dst):
    """Any audio the provider wrote -> a 16-bit mono WAV at dst (ffmpeg only when it is not one already)."""
    try:
        with wave.open(str(src), "rb") as w:
            if w.getsampwidth() == 2 and w.getnchannels() == 1:
                if pathlib.Path(src) != pathlib.Path(dst):
                    shutil.copyfile(src, dst)
                return
    except (wave.Error, EOFError):
        pass
    if not shutil.which("ffmpeg"):
        raise ProviderError(f"{src} is not a 16-bit mono WAV and ffmpeg is not installed to convert it")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-sample_fmt", "s16", str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise ProviderError(f"could not convert {src}: {r.stderr.strip()[-300:]}")


class Mock(Provider):
    """Deterministic audio sized like real speech in the given language (its own timing rules),
    with word timings. Settings for tests: {"timestamps": true} reads whole sections, {"paid": true,
    "price": 0.08} acts as a paid provider, {"fail": "error" | "empty" | "silent"} misbehaves."""
    name = "mock"

    def __init__(self, config=None):
        super().__init__(config)
        self.timestamps = bool(self.config.get("timestamps"))
        self.paid = bool(self.config.get("paid"))
        self.price_per_1k_chars = float(self.config.get("price", 0.0))
        self.calls = []

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        self.calls.append(text)
        fail = (settings or {}).get("fail") or self.config.get("fail")
        if fail == "error":
            raise ProviderError("mock provider failure (requested)")
        lg = langs.get(lang_code)
        words = langs.TOKEN.findall(text)
        if fail == "empty":
            write_wav(out, []); return Result(out, 0.0, [], len(text))
        weights = [max(0.2, lg.est_seconds(w)) for w in words] or [0.3]
        scale = max(0.3, lg.est_seconds(text)) / sum(weights)
        timings, t = [], 0.05
        for w, wt in zip(words, weights):
            d = wt * scale
            timings.append({"w": w, "start": round(t, 3), "end": round(t + d * 0.9, 3)})
            t += d
        total = t + 0.1
        seed = sum(map(ord, text)) % 97 + 3
        amp = 0 if fail == "silent" else 9000
        samples = [int(amp * math.sin(2 * math.pi * (110 + seed) * i / SAMPLE_RATE) * (0.6 + 0.4 * math.sin(i / 900.0)))
                   for i in range(int(total * SAMPLE_RATE))]
        write_wav(out, samples)
        return Result(out, total, timings, len(text))


class Espeak(Provider):
    """espeak-ng: robotic but free and local, the scratch voice that times a film before the final one."""
    name = "espeak"
    langs = ("en", "hi")
    VOICES = {"en": "en-us", "hi": "hi"}

    def default_voice(self, code):
        return self.VOICES.get(code, code)

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            raise ProviderError("espeak-ng is not installed (apt install espeak-ng)")
        voice = voice or self.default_voice(lang_code)
        rate = int((settings or {}).get("wpm") or 160)
        tmp = pathlib.Path(out).with_suffix(".espeak.wav")
        r = subprocess.run([exe, "-v", voice, "-s", str(rate), "-w", str(tmp), text], capture_output=True, text=True)
        if r.returncode != 0 or not tmp.exists():
            raise ProviderError(f"espeak-ng failed for voice {voice!r}: {r.stderr.strip()[-200:]}")
        to_wav(tmp, out); tmp.unlink()
        dur = wav_info(out)[0]
        return Result(out, dur, None, len(text))


class Command(Provider):
    """Any local TTS: "cmd" in voice.json with {txt} (a UTF-8 file with the text), {out} (the file to
    write), {voice} and {lang}. Treated as free and local; it never receives an API key from here."""
    name = "command"

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        cmd = self.config.get("cmd")
        if not cmd:
            raise ProviderError('the command provider needs "cmd" in voice.json')
        with tempfile.TemporaryDirectory() as tmp:
            txt = pathlib.Path(tmp) / "line.txt"
            txt.write_text(text, encoding="utf-8")
            raw = pathlib.Path(tmp) / ("out" + (self.config.get("ext") or ".wav"))
            args = [a.format(txt=txt, out=raw, voice=voice or "", lang=lang_code) for a in shlex.split(cmd)]
            r = subprocess.run(args, capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not raw.exists():
                raise ProviderError(f"command failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
            to_wav(raw, out)
        return Result(out, wav_info(out)[0], None, len(text))


# ---------------------------------------------------------------------------------------------
# Paid API providers. Nothing here runs in the tests against a real service: every request goes
# through Http, whose opener the tests replace, and CINEMATIC_OFFLINE=1 refuses the real one.
# ---------------------------------------------------------------------------------------------

SECRET_NAME = re.compile(r"(api[_-]?key|secret|token|password|subscription[_-]?key|authorization)", re.I)
NOT_IN_REQUEST = ("note", "provider", "inr_per_usd", "price_per_1k", "inr_per_10k_chars", "max_chars",
                  "allow_unknown_model")     # voice.json fields that change the estimate, not the audio


def secret_fields(cfg, where="voice.json"):
    """Fields in voice.json that look like credentials. Keys belong in the environment, never in a file."""
    found = []

    def walk(d, path):
        for k, v in (d or {}).items():
            if SECRET_NAME.search(str(k)):
                found.append(f"{where} has a field {path + str(k)!r}: API keys belong in the environment "
                             f"(ELEVENLABS_API_KEY, SARVAM_API_KEY), never in a project file; remove it")
            elif isinstance(v, dict):
                walk(v, path + str(k) + ".")
    walk(cfg, "")
    return found


def redact(text, *secrets):
    text = str(text)
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "[redacted]")
    return text


def api_key(env):
    """The key from the environment, at the moment it is needed. Never stored on the provider."""
    key = (os.environ.get(env) or "").strip()
    if not key:
        raise ProviderError(f"{env} is not set: put the API key in the environment (never in voice.json); "
                            f"nothing was sent")
    return key


def urllib_opener(method, url, headers, data, timeout):
    """The real network: (status, headers, body). Only Http calls it, and only when not offline."""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


class Http:
    """JSON over HTTPS for the API providers: retries what is worth retrying, and keeps keys out of
    every message. Retried: 429 (rate limit) and 500/502/503/504, honouring Retry-After, at most
    `tries` attempts and `max_wait` seconds a wait. Not retried: 4xx refusals (a bad key, a bad
    request, quota) and network failures or timeouts, where the service may already have done (and
    billed) the work. A response that arrives is never sent twice."""
    RETRY = (429, 500, 502, 503, 504)

    def __init__(self, opener=None, sleep=time.sleep, tries=4, max_wait=60.0, timeout=180):
        self.opener, self.sleep, self.tries, self.max_wait, self.timeout = opener, sleep, tries, max_wait, timeout
        self.attempts = 0

    def request(self, method, url, headers, body=None, secret="", service="the API"):
        opener = self.opener
        if opener is None:
            if os.environ.get("CINEMATIC_OFFLINE") == "1":
                raise ProviderError(f"CINEMATIC_OFFLINE=1: no request to {service} (nothing was sent)")
            opener = urllib_opener
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        for attempt in range(1, self.tries + 1):
            self.attempts += 1
            try:
                status, rh, raw = opener(method, url, headers, data, self.timeout)
            except ProviderError:
                raise
            except Exception as e:                 # DNS, refused, reset, timeout: not retried (it may have run)
                raise ProviderError(redact(f"could not reach {service}: {type(e).__name__}: {e}", secret)) from None
            rh = {str(k).lower(): v for k, v in (rh or {}).items()}
            if 200 <= status < 300:
                try:
                    return json.loads(raw.decode("utf-8")), rh
                except (ValueError, UnicodeDecodeError):
                    raise ProviderError(f"{service} answered {status} with something that is not JSON") from None
            msg = redact(self.message(raw), secret)
            if status in self.RETRY and attempt < self.tries and not self.quota(raw):
                wait = self.wait(rh.get("retry-after"), attempt)
                if wait > self.max_wait:
                    raise ProviderError(f"{service} is rate limited for {wait:.0f}s (over {self.max_wait:.0f}s); try later: {msg}")
                self.sleep(wait)
                continue
            raise ProviderError(self.explain(status, msg, service, attempt))
        raise ProviderError(f"{service}: gave up after {self.tries} attempts")    # not reached

    @staticmethod
    def wait(retry_after, attempt):
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            return float(min(30, 2 ** attempt))

    @staticmethod
    def quota(raw):
        return b"quota_exceeded" in (raw or b"") or b"insufficient" in (raw or b"").lower()

    @staticmethod
    def message(raw):
        """The service's own words about a refusal, short; never the request or its headers."""
        try:
            j = json.loads((raw or b"").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return (raw or b"")[:200].decode("utf-8", "replace").strip() or "no details"
        d = j.get("detail", j.get("error", j)) if isinstance(j, dict) else j
        if isinstance(d, dict):
            d = d.get("message") or d.get("msg") or d.get("status") or d.get("code") or json.dumps(d)[:200]
        elif isinstance(d, list):
            d = "; ".join(str(x.get("msg", x) if isinstance(x, dict) else x) for x in d[:3])
        return str(d)[:300]

    @staticmethod
    def explain(status, msg, service, attempt):
        why = {400: "refused the request", 401: "refused the API key (wrong, expired or out of quota)",
               402: "needs payment on the account", 403: "does not allow this for the key", 404: "does not know this voice or model",
               413: "says the text is too long", 422: "says the request is not valid", 429: "is rate limiting us"}.get(
            status, "failed" if status >= 500 else "refused the request")
        tail = f" after {attempt} attempts" if attempt > 1 else ""
        return f"{service} {why} (HTTP {status}{tail}): {msg}"


class ApiProvider(Provider):
    """What the paid API providers share: the key from the environment, the Http client (tests
    replace it), and the same checks for every request before anything is sent."""
    paid = True
    host = ""

    def __init__(self, config=None, http=None):
        super().__init__(config)
        self.http = http or Http()
        self.last = {}                         # the last request's request id and billed characters (no keys)

    def number(self, settings, key, lo, hi, problems):
        v = settings.get(key)
        if v is None:
            return
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= v <= hi):
            problems.append(f"{self.name} setting {key}={v!r} must be a number from {lo} to {hi}")

    def common_checks(self, cfg, code, allowed_settings):
        problems = secret_fields(cfg)
        if not self.supports(code):
            problems.append(f"the {self.name} provider speaks {', '.join(self.langs)}, not {code}: "
                            f"each edition has its own voice ({'elevenlabs for en' if code == 'en' else 'sarvam for hi'})")
        settings = cfg.get("settings") or {}
        if not isinstance(settings, dict):
            return problems + [f"{self.name}: settings must be an object"]
        extra = sorted(set(settings) - set(allowed_settings) - {"wpm"})
        if extra:
            problems.append(f"{self.name} does not take the setting(s) {', '.join(extra)}; it takes {', '.join(sorted(allowed_settings))}")
        if self.max_chars and int(cfg.get("max_chars") or self.max_chars) > self.max_chars:
            problems.append(f"{self.name}: max_chars {cfg.get('max_chars')} is over the provider's {self.max_chars}")
        return problems

    def limit(self):
        return int(self.config.get("max_chars") or self.max_chars)

    def too_long(self, text):
        if self.limit() and len(text) > self.limit():
            raise ProviderError(f"{len(text)} characters in one request; {self.name} takes at most {self.limit()} "
                                f"(nothing was sent; use \"mode\": \"line\" or shorter lines)")


class ElevenLabs(ApiProvider):
    """ElevenLabs text to speech with character timestamps, for the English edition.

    voice.json: {"provider": "elevenlabs", "voice": "<voice id from your ElevenLabs library>",
                 "model": "eleven_multilingual_v2", "settings": {"stability": 0.5, "similarity_boost": 0.75,
                 "style": 0.0, "use_speaker_boost": true, "speed": 1.0}, "output_format": "pcm_24000"}
    Optional: "seed" (repeatable takes), "language_code": "en", "price_per_1k" (your plan's USD price),
    "allow_unknown_model": true (a model newer than this list). The voice and model are chosen by
    audition (voice.py audition), never assumed. The key comes from ELEVENLABS_API_KEY."""
    name = "elevenlabs"
    timestamps = True
    langs = ("en",)
    key_env = "ELEVENLABS_API_KEY"
    host = "api.elevenlabs.io"
    max_chars = 5000
    # USD per 1,000 characters; a deliberately cautious default (not verified against your plan:
    # set "price_per_1k" to what your plan charges, and the cap and spend log follow it)
    MODELS = {"eleven_multilingual_v2": 0.10, "eleven_v3": 0.10, "eleven_turbo_v2_5": 0.05, "eleven_flash_v2_5": 0.05}
    FORMATS = {"pcm_16000": 16000, "pcm_22050": 22050, "pcm_24000": 24000, "pcm_44100": 44100}
    SETTINGS = ("stability", "similarity_boost", "style", "use_speaker_boost", "speed")
    VOICE_ID = re.compile(r"^[A-Za-z0-9]{16,40}$")

    def __init__(self, config=None, http=None):
        super().__init__(config, http)
        model = self.config.get("model") or ""
        self.price_per_1k_chars = float(self.config.get("price_per_1k") or self.MODELS.get(model, 0.10))

    def check(self, cfg, code):
        problems = self.common_checks(cfg, code, self.SETTINGS)
        voice, model = cfg.get("voice") or "", cfg.get("model") or ""
        if not voice:
            problems.append("elevenlabs needs \"voice\": a voice id from your ElevenLabs library, chosen by audition")
        elif not self.VOICE_ID.match(voice):
            problems.append(f"elevenlabs voice {voice!r} is not a voice id (letters and digits, like 21m00Tcm4TlvDq8ikWAM)")
        if not model:
            problems.append(f"elevenlabs needs \"model\", chosen by audition: one of {', '.join(self.MODELS)}")
        elif model not in self.MODELS and not cfg.get("allow_unknown_model"):
            problems.append(f"elevenlabs model {model!r} is not one of {', '.join(self.MODELS)} "
                            f"(\"allow_unknown_model\": true if it is a newer one)")
        if (cfg.get("output_format") or "pcm_24000") not in self.FORMATS:
            problems.append(f"elevenlabs output_format must be one of {', '.join(self.FORMATS)} (raw PCM, so no ffmpeg is needed)")
        lc = cfg.get("language_code")
        if lc and lc.lower() != code:
            problems.append(f"elevenlabs language_code {lc!r} is not this edition's language ({code})")
        s = cfg.get("settings") or {}
        if isinstance(s, dict):
            for k in ("stability", "similarity_boost", "style"):
                self.number(s, k, 0.0, 1.0, problems)
            self.number(s, "speed", 0.7, 1.2, problems)
            if "use_speaker_boost" in s and not isinstance(s["use_speaker_boost"], bool):
                problems.append("elevenlabs setting use_speaker_boost must be true or false")
        if cfg.get("seed") is not None and (isinstance(cfg["seed"], bool) or not isinstance(cfg["seed"], int)
                                            or not 0 <= cfg["seed"] <= 4294967295):
            problems.append("elevenlabs seed must be a whole number from 0 to 4294967295")
        return problems

    def request(self, text, voice, settings, context, lang_code):
        """(url, json body) for one read; the key goes in a header, never in the URL or the body."""
        fmt = self.config.get("output_format") or "pcm_24000"
        url = f"https://{self.host}/v1/text-to-speech/{voice}/with-timestamps?output_format={fmt}"
        body = {"text": text, "model_id": self.config.get("model")}
        vs = {k: v for k, v in (settings or {}).items() if k in self.SETTINGS}
        if vs:
            body["voice_settings"] = vs
        if context:
            if context.get("previous"):
                body["previous_text"] = context["previous"]
            if context.get("next"):
                body["next_text"] = context["next"]
        if self.config.get("seed") is not None:
            body["seed"] = self.config["seed"]
        if self.config.get("language_code"):
            body["language_code"] = self.config["language_code"]
        return url, body

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        if not self.supports(lang_code):
            raise ProviderError(f"elevenlabs is the English voice; it does not read {lang_code} (nothing was sent)")
        problems = self.check({**self.config, "voice": voice, "settings": settings or {}}, lang_code)
        if problems:
            raise ProviderError(problems[0] + " (nothing was sent)")
        self.too_long(text)
        url, body = self.request(text, voice, settings, context, lang_code)
        key = api_key(self.key_env)
        j, rh = self.http.request("POST", url, {"xi-api-key": key, "Content-Type": "application/json",
                                               "Accept": "application/json"}, body, secret=key, service="ElevenLabs")
        rate = self.FORMATS[self.config.get("output_format") or "pcm_24000"]
        try:
            pcm = base64.b64decode(j["audio_base64"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise ProviderError("ElevenLabs answered without audio (no audio_base64)") from None
        if len(pcm) < 2:
            raise ProviderError("ElevenLabs returned empty audio")
        pcm = pcm[: len(pcm) // 2 * 2]
        write_pcm_wav(out, pcm, rate)
        words = self.words(text, j.get("alignment"))
        self.last = {"request_id": rh.get("request-id") or rh.get("x-request-id") or "",
                     "billed_chars": int(rh["character-cost"]) if str(rh.get("character-cost", "")).isdigit() else len(text)}
        return Result(out, len(pcm) / 2 / float(rate), words, len(text))

    @staticmethod
    def words(text, al):
        """Word timings from the character alignment: each word starts at its first character and
        ends at its last. An alignment that does not match the text is an error, not a guess."""
        if not isinstance(al, dict):
            raise ProviderError("ElevenLabs answered without character timings (alignment)")
        chars, starts, ends = (al.get("characters"), al.get("character_start_times_seconds"),
                               al.get("character_end_times_seconds"))
        if not (isinstance(chars, list) and isinstance(starts, list) and isinstance(ends, list)) \
                or not (len(chars) == len(starts) == len(ends)):
            raise ProviderError("ElevenLabs character timings are incomplete")
        if "".join(chars) != text:
            raise ProviderError(f"ElevenLabs character timings do not match the text sent "
                                f"({len(chars)} characters timed, {len(text)} sent)")
        out = []
        for m in langs.TOKEN.finditer(text):
            a, b = m.start(), m.end() - 1
            out.append({"w": m.group(0), "start": round(float(starts[a]), 3), "end": round(float(ends[b]), 3)})
        return out

    def verify(self, voice):
        """A free check that the voice id exists for this key (GET, no synthesis). Live: only on request."""
        if not self.VOICE_ID.match(voice or ""):
            raise ProviderError(f"{voice!r} is not an ElevenLabs voice id")
        key = api_key(self.key_env)
        j, _ = self.http.request("GET", f"https://{self.host}/v1/voices/{voice}", {"xi-api-key": key, "Accept": "application/json"},
                                 None, secret=key, service="ElevenLabs")
        return {"voice_id": j.get("voice_id", voice), "name": j.get("name", ""), "category": j.get("category", "")}


class Sarvam(ApiProvider):
    """Sarvam AI Bulbul text to speech, for the Hindi edition. Line by line (no word timings).

    voice.json: {"provider": "sarvam", "voice": "<speaker, e.g. anushka>", "model": "bulbul:v2",
                 "locale": "hi-IN", "inr_per_usd": 85.0, "settings": {"pace": 1.0, "pitch": 0.0,
                 "loudness": 1.0, "speech_sample_rate": 22050, "enable_preprocessing": true}}
    "inr_per_usd" is your own rate and is required: Sarvam bills in rupees and the cap is in
    dollars. Optional: "inr_per_10k_chars" (your plan's price), "language_field" and "text_field"
    (if the API names them differently), "allow_unknown_model". The key comes from SARVAM_API_KEY."""
    name = "sarvam"
    langs = ("hi",)
    key_env = "SARVAM_API_KEY"
    host = "api.sarvam.ai"
    max_chars = 1500
    # rupees per 10,000 characters: cautious defaults, not verified against your plan
    MODELS = {"bulbul:v2": 15.0, "bulbul:v3": 30.0}
    SPEAKERS = {"bulbul:v2": ("anushka", "manisha", "vidya", "arya", "abhilash", "karun", "hitesh")}
    RATES = (8000, 16000, 22050, 24000)
    SETTINGS = ("pitch", "pace", "loudness", "speech_sample_rate", "enable_preprocessing")

    def __init__(self, config=None, http=None):
        super().__init__(config, http)
        model = self.config.get("model") or ""
        self.inr_per_10k = float(self.config.get("inr_per_10k_chars") or self.MODELS.get(model, 30.0))
        try:
            self.inr_per_usd = float(self.config.get("inr_per_usd") or 0)
        except (TypeError, ValueError):
            self.inr_per_usd = 0.0

    def estimate_inr(self, chars):
        return chars / 10000.0 * self.inr_per_10k

    def estimate_cost(self, chars):
        """Dollars for the cap, at your rate. With no rate the estimate is infinite: nothing is sent."""
        return self.estimate_inr(chars) / self.inr_per_usd if self.inr_per_usd > 0 else float("inf")

    def describe_cost(self, cost):
        if cost == float("inf"):
            return "unknown dollars (no inr_per_usd)"
        return f"${cost:.2f} (₹{cost * self.inr_per_usd:.2f} at ₹{self.inr_per_usd:g} a dollar)"

    def check(self, cfg, code):
        problems = self.common_checks(cfg, code, self.SETTINGS)
        voice, model = cfg.get("voice") or "", cfg.get("model") or ""
        if not model:
            problems.append(f"sarvam needs \"model\", chosen by audition: one of {', '.join(self.MODELS)}")
        elif model not in self.MODELS and not cfg.get("allow_unknown_model"):
            problems.append(f"sarvam model {model!r} is not one of {', '.join(self.MODELS)} "
                            f"(\"allow_unknown_model\": true if it is a newer one)")
        if not voice:
            problems.append("sarvam needs \"voice\": a speaker name, chosen by audition")
        elif model in self.SPEAKERS and voice not in self.SPEAKERS[model]:
            problems.append(f"sarvam speaker {voice!r} is not a {model} speaker: {', '.join(self.SPEAKERS[model])}")
        elif not re.match(r"^[a-z][a-z0-9_-]{1,30}$", voice):
            problems.append(f"sarvam speaker {voice!r} is not a speaker name (lower-case, like anushka)")
        loc = cfg.get("locale") or ""
        if code == "hi" and loc and loc != "hi-IN":
            problems.append(f"sarvam reads Hindi as hi-IN; voice.json locale is {loc!r}")
        try:
            rate = float(cfg.get("inr_per_usd") or 0)
        except (TypeError, ValueError):
            rate = 0
        if rate <= 0:
            problems.append("sarvam bills in rupees: set \"inr_per_usd\" in voice.json to your own exchange rate "
                            "(the $ cap needs it; decision J)")
        elif not 20 <= rate <= 500:
            problems.append(f"inr_per_usd {rate:g} does not look like rupees to the dollar")
        s = cfg.get("settings") or {}
        if isinstance(s, dict):
            self.number(s, "pitch", -0.75, 0.75, problems)
            self.number(s, "pace", 0.3, 3.0, problems)
            self.number(s, "loudness", 0.1, 3.0, problems)
            if "speech_sample_rate" in s and s["speech_sample_rate"] not in self.RATES:
                problems.append(f"sarvam speech_sample_rate must be one of {', '.join(map(str, self.RATES))}")
            if "enable_preprocessing" in s and not isinstance(s["enable_preprocessing"], bool):
                problems.append("sarvam setting enable_preprocessing must be true or false")
        return problems

    def request(self, text, voice, settings, lang_code):
        body = {self.config.get("text_field") or "text": text,
                self.config.get("language_field") or "target_language_code": "hi-IN",
                "speaker": voice, "model": self.config.get("model")}
        for k, v in (settings or {}).items():
            if k in self.SETTINGS:
                body[k] = v
        return f"https://{self.host}/text-to-speech", body

    def synthesize(self, text, out, lang_code, voice="", settings=None, context=None):
        if not self.supports(lang_code):
            raise ProviderError(f"sarvam is the Hindi voice; it does not read {lang_code} (nothing was sent)")
        problems = self.check({**self.config, "voice": voice, "settings": settings or {}}, lang_code)
        if problems:
            raise ProviderError(problems[0] + " (nothing was sent)")
        self.too_long(text)
        url, body = self.request(text, voice, settings, lang_code)
        key = api_key(self.key_env)
        j, rh = self.http.request("POST", url, {"api-subscription-key": key, "Content-Type": "application/json",
                                               "Accept": "application/json"}, body, secret=key, service="Sarvam")
        audios = j.get("audios") if isinstance(j, dict) else None
        if not isinstance(audios, list) or not audios:
            raise ProviderError("Sarvam answered without audio (no audios)")
        try:
            raw = b"".join(base64.b64decode(a, validate=True) for a in audios)
        except (TypeError, ValueError):
            raise ProviderError("Sarvam audio is not valid base64") from None
        if len(audios) > 1 or raw[:4] != b"RIFF":
            raise ProviderError("Sarvam returned audio that is not one WAV file" if raw[:4] != b"RIFF"
                                else "Sarvam returned several audio parts for one line; send shorter lines")
        out = pathlib.Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".sarvam.wav")
        tmp.write_bytes(raw)
        try:
            to_wav(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        dur = wav_info(out)[0]
        if dur <= 0:
            raise ProviderError("Sarvam returned empty audio")
        self.last = {"request_id": str(j.get("request_id") or rh.get("request-id") or ""), "billed_chars": len(text),
                     "inr": round(self.estimate_inr(len(text)), 4)}
        return Result(out, dur, None, len(text))


def write_pcm_wav(path, pcm, rate):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(pcm)


PROVIDERS = {p.name: p for p in (Mock, Espeak, Command, ElevenLabs, Sarvam)}


def get(name, config=None):
    if name not in PROVIDERS:
        raise ProviderError(f"unknown voice provider {name!r}; available: {', '.join(PROVIDERS)}")
    return PROVIDERS[name](config)


def split_takes_by_words(take_lines, words):
    """Where each line of a section starts and ends in the section's audio, from word timings.
    take_lines: [(line id, spoken)]. Returns {line id: (t0, t1)}; lines meet halfway between words."""
    counts = [len(langs.TOKEN.findall(s)) for _, s in take_lines]
    if sum(counts) != len(words):
        raise ProviderError(f"word timings do not match the text ({len(words)} timed, {sum(counts)} in the lines)")
    bounds, k = {}, 0
    for (lid, _), c in zip(take_lines, counts):
        first, last = words[k], words[k + c - 1]
        bounds[lid] = [first["start"], last["end"]]
        k += c
    ids = [lid for lid, _ in take_lines]
    for a, b in zip(ids, ids[1:]):
        mid = (bounds[a][1] + bounds[b][0]) / 2
        bounds[a][1] = bounds[b][0] = mid
    bounds[ids[0]][0] = max(0.0, bounds[ids[0]][0] - 0.05)
    bounds[ids[-1]][1] = bounds[ids[-1]][1] + 0.1
    return {k: tuple(v) for k, v in bounds.items()}

