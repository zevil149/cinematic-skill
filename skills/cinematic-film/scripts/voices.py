"""Voice providers behind one interface, for the per-edition voice framework (voice.py).

A provider turns one request (spoken text in one language, a voice, settings) into a WAV file.
Providers that return reliable word timings can read a whole section in one go (smoother
delivery); voice.py then cuts it into line segments. The others read line by line.

  mock      deterministic test audio for any language: no sound engine, no network, free
  espeak    espeak-ng, the free local scratch voice (en-us for English, hi for Hindi)
  command   any local TTS tool: "cmd": "mytts --in {txt} --out {out} --voice {voice} --lang {lang}"

Paid API providers (ElevenLabs, Sarvam) are milestone 3.4. A provider marked paid never runs
without the spend guard in voice.py: an estimate, a cap ($5 a run by default) and an explicit
--confirm-cost. Standard library only.
"""
import array
import math
import pathlib
import shlex
import shutil
import subprocess
import tempfile
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


PROVIDERS = {p.name: p for p in (Mock, Espeak, Command)}
PLANNED = {"elevenlabs": "milestone 3.4", "sarvam": "milestone 3.4"}


def get(name, config=None):
    if name in PLANNED:
        raise ProviderError(f"the {name} provider arrives in {PLANNED[name]}; use mock, espeak or command for now")
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

