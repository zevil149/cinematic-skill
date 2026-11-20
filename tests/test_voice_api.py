"""Tests for milestone 3.4: the ElevenLabs (English) and Sarvam (Hindi) voice providers.

Every request goes to a fake opener inside the test: no network, no API key, no cost. The fake
keys below are made up; the tests check that they never reach a file, a message or the output.
CINEMATIC_OFFLINE=1 is set, and the real opener is checked to refuse while it is.
"""
import array
import base64
import contextlib
import io
import json
import math
import os
import pathlib
import sys
import tempfile
import unittest
import wave
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_docpipe import cli, quiet  # noqa: E402
from test_voice import NOLOG, manifest, seg, two_editions  # noqa: E402

EL_KEY = "el-FAKE-0123456789abcdef-must-never-leak"
SV_KEY = "sv-FAKE-fedcba9876543210-must-never-leak"
KEYS = {"ELEVENLABS_API_KEY": EL_KEY, "SARVAM_API_KEY": SV_KEY}
EL_VOICE = "21m00Tcm4TlvDq8ikWAM"

EN_CFG = {"provider": "elevenlabs", "voice": EL_VOICE, "model": "eleven_multilingual_v2", "output_format": "pcm_24000",
          "settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True, "speed": 1.0}}
HI_CFG = {"provider": "sarvam", "voice": "anushka", "model": "bulbul:v2", "inr_per_usd": 85.0,
          "settings": {"pace": 1.0, "pitch": 0.0, "loudness": 1.0, "speech_sample_rate": 22050, "enable_preprocessing": True}}


def tone(seconds, rate):
    n = max(1, int(seconds * rate))
    return array.array("h", [int(8000 * math.sin(2 * math.pi * 180 * i / rate)) for i in range(n)]).tobytes()


def wav_bytes(seconds, rate=22050):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(tone(seconds, rate))
    return buf.getvalue()


def ok(body, headers=None):
    return 200, dict(headers or {}), json.dumps(body).encode()


def eleven_answer(text, rate=24000, dt=0.06):
    """What ElevenLabs answers for /with-timestamps: base64 PCM and per-character timings."""
    return ok({"audio_base64": base64.b64encode(tone(len(text) * dt + 0.2, rate)).decode(),
               "alignment": {"characters": list(text), "character_start_times_seconds": [round(i * dt, 3) for i in range(len(text))],
                             "character_end_times_seconds": [round((i + 1) * dt, 3) for i in range(len(text))]}},
              {"request-id": "el-req-1", "character-cost": str(len(text))})


def sarvam_answer(text):
    return ok({"request_id": "sv-req-1", "audios": [base64.b64encode(wav_bytes(len(text) * 0.07 + 0.2)).decode()]})


class FakeApi:
    """Stands in for the network. `script` is a list of answers used in turn (status, headers, body),
    then `default(request)` for the rest. Records every request as (method, url, headers, body)."""

    def __init__(self, default=None, script=None):
        self.calls, self.script, self.default = [], list(script or []), default

    def __call__(self, method, url, headers, data, timeout):
        body = json.loads(data.decode()) if data else None
        self.calls.append((method, url, dict(headers), body))
        if self.script:
            a = self.script.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        return self.default(method, url, body)


def el_api(**kw):
    return FakeApi(lambda m, u, b: eleven_answer(b["text"]) if b else ok({"voice_id": EL_VOICE, "name": "Narrator", "category": "premade"}), **kw)


def sv_api(**kw):
    return FakeApi(lambda m, u, b: sarvam_answer(b["text"]), **kw)


def http(api, sleeps=None):
    return V.Http(opener=api, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def configure(ed, cfg):
    c = L.load(ed / "voice.json")
    c.update(json.loads(json.dumps(cfg)))
    L.save(ed / "voice.json", c)
    return c


def api_editions(tmp):
    proj, en, hi = two_editions(tmp)
    return proj, en, hi, configure(en, EN_CFG), configure(hi, HI_CFG)


def leaks(root):
    """Files under root that contain either fake key."""
    bad = []
    for f in pathlib.Path(root).rglob("*"):
        if f.is_file():
            b = f.read_bytes()
            if EL_KEY.encode() in b or SV_KEY.encode() in b:
                bad.append(str(f))
    return bad


class ElevenLabsRequests(unittest.TestCase):
    def test_section_reads_request_format_and_word_timings(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, _ = api_editions(tmp)
            api = el_api()
            prov = V.ElevenLabs(cfg, http=http(api))
            r = voice.synth(en, provider=prov, confirm=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            takes = L.load(en / "script.json")["takes"]
            self.assertEqual(len(api.calls), len(takes))                       # one read per section
            method, url, headers, body = api.calls[0]
            self.assertEqual(method, "POST")
            self.assertEqual(url, f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE}/with-timestamps?output_format=pcm_24000")
            self.assertEqual(headers["xi-api-key"], EL_KEY)                    # the key in its header only
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertNotIn(EL_KEY, url); self.assertNotIn(EL_KEY, json.dumps(body))
            self.assertEqual(body["model_id"], "eleven_multilingual_v2")
            self.assertEqual(body["voice_settings"], EN_CFG["settings"])        # wpm (the scratch voice's) is not sent
            self.assertNotIn("previous_text", body)                            # a whole section carries its own context
            self.assertEqual(body["text"], "\n\n".join(l["spoken"] for l in takes[0]["lines"]))
            m = manifest(en)["segments"]
            n = sum(len(t["lines"]) for t in takes)
            self.assertEqual(len(m), n)
            first = m["1"]
            self.assertEqual((first["provider"], first["mode"], first["model"]), ("elevenlabs", "section", "eleven_multilingual_v2"))
            self.assertTrue(first["words"] and first["words"][0]["start"] >= 0)
            with wave.open(str(seg(en, 1))) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
            spend = L.load(en / "audio" / "voice" / "spend.json")
            self.assertEqual(len(spend["requests"]), len(takes))
            self.assertEqual(spend["requests"][0]["request_id"], "el-req-1")
            self.assertEqual(spend["requests"][0]["chars"], len(body["text"]))
            self.assertEqual(spend["lang"], "en")
            self.assertFalse((hi / "audio" / "voice" / "spend.json").exists())  # spend is per edition
            # resume: nothing changed, nothing sent
            api.calls.clear()
            self.assertTrue(voice.synth(en, provider=prov, confirm=True, **NOLOG).ok)
            self.assertEqual(api.calls, [])

    def test_line_mode_sends_neighbouring_lines_as_context(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, _ = api_editions(tmp)
            cfg = configure(en, {"mode": "line", "seed": 7})
            api = el_api()
            r = voice.synth(en, only={1, 2}, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertFalse([e for e in r.errors if e.startswith(("line 1:", "line 2:"))], r.errors)
            self.assertEqual(len(api.calls), 2)
            lines = [l for t in L.load(en / "script.json")["takes"] for l in t["lines"]]
            b1, b2 = api.calls[0][3], api.calls[1][3]
            self.assertEqual(b1["text"], lines[0]["spoken"]); self.assertEqual(b1["seed"], 7)
            self.assertEqual(b1.get("next_text"), lines[1]["spoken"])
            self.assertEqual(b2.get("previous_text"), lines[0]["spoken"])
            self.assertEqual(manifest(en)["segments"]["1"]["mode"], "line")

    def test_parsing_alignment_into_words(self):
        text = "Kitty Hawk, 1903."
        _, _, raw = eleven_answer(text)
        words = V.ElevenLabs.words(text, json.loads(raw)["alignment"])
        self.assertEqual([w["w"] for w in words], ["Kitty", "Hawk", "1903"])
        self.assertEqual((words[0]["start"], words[0]["end"]), (0.0, 0.3))      # characters 0..4
        self.assertEqual(words[1]["start"], 0.36)
        with self.assertRaises(V.ProviderError):                               # timings for other text
            V.ElevenLabs.words("Kitty Hawk", json.loads(raw)["alignment"])
        with self.assertRaises(V.ProviderError):
            V.ElevenLabs.words(text, {"characters": list(text), "character_start_times_seconds": []})
        with self.assertRaises(V.ProviderError):
            V.ElevenLabs.words(text, None)

    def test_bad_answers_are_errors_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            out = pathlib.Path(tmp) / "x.wav"
            for answer in (ok({"alignment": {}}), ok({"audio_base64": "!!!not base64!!!"}), ok({"audio_base64": ""}),
                           (200, {}, b"<html>not json</html>")):
                prov = V.ElevenLabs(EN_CFG, http=http(FakeApi(script=[answer])))
                with self.assertRaises(V.ProviderError):
                    prov.synthesize("Hello there.", out, "en", EL_VOICE, EN_CFG["settings"])
                self.assertFalse(out.exists())


class SarvamRequests(unittest.TestCase):
    def test_line_reads_request_format_rupees_and_review(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, _, cfg = api_editions(tmp)
            api = sv_api()
            prov = V.Sarvam(cfg, http=http(api))
            r = voice.synth(hi, provider=prov, confirm=True, **NOLOG)
            self.assertTrue(any("native-speaker review" in e for e in r.errors))  # paid Hindi needs the review first
            self.assertEqual(api.calls, [])
            quiet(voice.review, hi, "Reviewer A")
            r = voice.synth(hi, provider=prov, confirm=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            lines = [l for t in L.load(hi / "script.json")["takes"] for l in t["lines"]]
            self.assertEqual(len(api.calls), len(lines))                       # line by line: no word timings
            method, url, headers, body = api.calls[0]
            self.assertEqual((method, url), ("POST", "https://api.sarvam.ai/text-to-speech"))
            self.assertEqual(headers["api-subscription-key"], SV_KEY)
            self.assertNotIn(SV_KEY, url); self.assertNotIn(SV_KEY, json.dumps(body, ensure_ascii=False))
            self.assertEqual(body["target_language_code"], "hi-IN")
            self.assertEqual((body["speaker"], body["model"]), ("anushka", "bulbul:v2"))
            self.assertEqual(body["text"], lines[0]["spoken"])
            self.assertEqual((body["pace"], body["speech_sample_rate"]), (1.0, 22050))
            self.assertNotIn("wpm", body)
            self.assertTrue(any("ऀ" <= ch <= "ॿ" for ch in body["text"]))   # Devanagari is sent as it is
            e = manifest(hi)["segments"]["1"]
            self.assertEqual((e["provider"], e["mode"], e["voice"]), ("sarvam", "line", "anushka"))
            spend = L.load(hi / "audio" / "voice" / "spend.json")
            row = spend["requests"][0]
            self.assertEqual((row["request_id"], row["inr_per_usd"]), ("sv-req-1", 85.0))
            self.assertAlmostEqual(row["inr"], len(lines[0]["spoken"]) / 10000 * 15, places=4)
            self.assertAlmostEqual(row["usd"], len(lines[0]["spoken"]) / 10000 * 15 / 85, places=9)
            self.assertFalse((en / "audio" / "voice" / "spend.json").exists())

    def test_field_names_can_follow_the_api(self):
        prov = V.Sarvam({**HI_CFG, "language_field": "language_code", "text_field": "inputs"})
        url, body = prov.request("नमस्ते", "anushka", {}, "hi")
        self.assertEqual((body["language_code"], body["inputs"]), ("hi-IN", "नमस्ते"))

    def test_bad_answers_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            out = pathlib.Path(tmp) / "x.wav"
            for answer in (ok({"request_id": "r"}), ok({"audios": []}), ok({"audios": [base64.b64encode(b"ID3 an mp3").decode()]}),
                           ok({"audios": [base64.b64encode(wav_bytes(0.5)).decode()] * 2})):
                prov = V.Sarvam(HI_CFG, http=http(FakeApi(script=[answer])))
                with self.assertRaises(V.ProviderError):
                    prov.synthesize("नमस्ते", out, "hi", "anushka", HI_CFG["settings"])
                self.assertFalse(out.exists())


class HttpErrorsAndRetries(unittest.TestCase):
    URL = "https://api.example.invalid/x"

    def req(self, api, sleeps=None, **kw):
        h = V.Http(opener=api, sleep=(sleeps.append if sleeps is not None else (lambda s: None)), **kw)
        return h, h.request("POST", self.URL, {"k": "SECRET-KEY-123"}, {"text": "hi"}, secret="SECRET-KEY-123", service="Test")

    def test_rate_limit_is_retried_honouring_retry_after(self):
        sleeps = []
        api = FakeApi(script=[(429, {"Retry-After": "3"}, b'{"detail": {"status": "too_many_concurrent_requests"}}'),
                              (503, {}, b"busy"), ok({"fine": True})])
        h, (j, _) = self.req(api, sleeps)
        self.assertEqual(j, {"fine": True})
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(sleeps[0], 3.0)                                        # what the service asked for
        self.assertEqual(sleeps[1], 4.0)                                        # then backoff

    def test_gives_up_after_the_last_try_and_on_long_waits(self):
        api = FakeApi(script=[(500, {}, b"oops")] * 4)
        with self.assertRaises(V.ProviderError) as e:
            self.req(api)
        self.assertIn("after 4 attempts", str(e.exception)); self.assertEqual(len(api.calls), 4)
        sleeps = []
        api = FakeApi(script=[(429, {"Retry-After": "600"}, b"{}")])
        with self.assertRaises(V.ProviderError) as e:
            self.req(api, sleeps)
        self.assertIn("rate limited", str(e.exception)); self.assertEqual(sleeps, [])

    def test_refusals_are_not_retried(self):
        for status, body, word in ((401, b'{"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}', "API key"),
                                   (422, b'{"detail": [{"msg": "voice_settings.stability must be <= 1"}]}', "stability"),
                                   (400, b'{"error": {"message": "Text too long"}}', "Text too long"),
                                   (429, b'{"detail": {"status": "quota_exceeded"}}', "quota_exceeded"),
                                   (404, b'{"detail": {"message": "voice not found"}}', "voice not found")):
            api = FakeApi(script=[(status, {}, body)])
            with self.assertRaises(V.ProviderError) as e:
                self.req(api)
            self.assertEqual(len(api.calls), 1, status)
            self.assertIn(f"HTTP {status}", str(e.exception)); self.assertIn(word, str(e.exception))

    def test_network_failures_are_not_retried(self):
        api = FakeApi(script=[TimeoutError("timed out")])
        with self.assertRaises(V.ProviderError) as e:
            self.req(api)
        self.assertIn("could not reach Test", str(e.exception)); self.assertEqual(len(api.calls), 1)

    def test_the_key_never_appears_in_an_error(self):
        api = FakeApi(script=[(401, {}, b'{"detail": "bad key SECRET-KEY-123 for this account"}')])
        with self.assertRaises(V.ProviderError) as e:
            self.req(api)
        self.assertNotIn("SECRET-KEY-123", str(e.exception)); self.assertIn("[redacted]", str(e.exception))
        api = FakeApi(script=[ConnectionError("proxy said SECRET-KEY-123")])
        with self.assertRaises(V.ProviderError) as e:
            self.req(api)
        self.assertNotIn("SECRET-KEY-123", str(e.exception))

    def test_offline_refuses_the_real_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")) as u, \
                mock.patch.dict(os.environ, KEYS):
            with self.assertRaises(V.ProviderError) as e:
                V.Http().request("POST", self.URL, {}, {"text": "x"})
            self.assertIn("CINEMATIC_OFFLINE", str(e.exception))
            for prov, lang, voice_ in ((V.ElevenLabs(EN_CFG), "en", EL_VOICE), (V.Sarvam(HI_CFG), "hi", "anushka")):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(V.ProviderError) as e:
                        prov.synthesize("Hello.", pathlib.Path(tmp) / "x.wav", lang, voice_, {})
                    self.assertIn("CINEMATIC_OFFLINE", str(e.exception))
            u.assert_not_called()


class KeysLanguagesAndValidation(unittest.TestCase):
    def test_missing_key_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            for k in KEYS:
                os.environ.pop(k, None)
            proj, en, hi, cfg, _ = api_editions(tmp)
            api = el_api()
            r = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(any("ELEVENLABS_API_KEY is not set" in e for e in r.errors), r.errors)
            self.assertEqual(api.calls, [])
            self.assertFalse((en / "audio" / "voice" / "spend.json").exists())  # nothing spent, nothing logged
            os.environ["ELEVENLABS_API_KEY"] = "   "
            with self.assertRaises(V.ProviderError):
                V.api_key("ELEVENLABS_API_KEY")

    def test_each_provider_speaks_only_its_edition(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, _, _ = api_editions(tmp)
            configure(hi, {**EN_CFG, "inr_per_usd": None})                      # ElevenLabs in the Hindi edition
            configure(en, {**HI_CFG, "locale": "en-US"})                       # Sarvam in the English edition
            for ed, word in ((hi, "elevenlabs provider does not speak hi"), (en, "sarvam provider does not speak en")):
                r, info = voice.plan(ed)
                self.assertIsNone(info)
                self.assertTrue(any(word in e for e in r.errors), r.errors)
            api = el_api()
            r = voice.synth(hi, provider=V.ElevenLabs(EN_CFG, http=http(api)), confirm=True, **NOLOG)
            self.assertFalse(r.ok); self.assertEqual(api.calls, [])
            with self.assertRaises(V.ProviderError):
                V.ElevenLabs(EN_CFG, http=http(api)).synthesize("नमस्ते", pathlib.Path(tmp) / "x.wav", "hi", EL_VOICE, {})
            with self.assertRaises(V.ProviderError):
                V.Sarvam(HI_CFG, http=http(api)).synthesize("Hello", pathlib.Path(tmp) / "x.wav", "en", "anushka", {})
            self.assertEqual(api.calls, [])
            self.assertTrue(any("language_code" in e for e in V.ElevenLabs().check({**EN_CFG, "language_code": "hi"}, "en")))
            self.assertTrue(any("hi-IN" in e for e in V.Sarvam().check({**HI_CFG, "locale": "hi-XX"}, "hi")))

    def test_model_voice_and_settings_are_checked_before_sending(self):
        el, sv = V.ElevenLabs(), V.Sarvam()
        self.assertEqual(el.check(EN_CFG, "en"), [])
        self.assertEqual(sv.check(HI_CFG, "hi"), [])
        bad_el = [({"voice": ""}, "needs \"voice\""), ({"voice": "rachel"}, "not a voice id"), ({"model": ""}, "needs \"model\""),
                  ({"model": "eleven_v9"}, "allow_unknown_model"), ({"output_format": "mp3_44100_128"}, "output_format"),
                  ({"settings": {"stability": 1.5}}, "stability"), ({"settings": {"speed": 2.0}}, "speed"),
                  ({"settings": {"use_speaker_boost": "yes"}}, "use_speaker_boost"), ({"settings": {"stabilty": 0.5}}, "stabilty"),
                  ({"seed": -1}, "seed"), ({"max_chars": 99999}, "max_chars")]
        for change, word in bad_el:
            problems = el.check({**EN_CFG, **change}, "en")
            self.assertTrue(any(word in p for p in problems), (change, problems))
        self.assertEqual(el.check({**EN_CFG, "model": "eleven_v9", "allow_unknown_model": True}, "en"), [])
        bad_sv = [({"voice": "rachel"}, "not a bulbul:v2 speaker"), ({"voice": ""}, "needs \"voice\""), ({"model": "bulbul:v9"}, "allow_unknown_model"),
                  ({"inr_per_usd": None}, "inr_per_usd"), ({"inr_per_usd": 0.012}, "does not look like rupees"),
                  ({"settings": {"pace": 5}}, "pace"), ({"settings": {"pitch": 1}}, "pitch"),
                  ({"settings": {"speech_sample_rate": 44100}}, "speech_sample_rate"), ({"settings": {"stability": 0.5}}, "stability")]
        for change, word in bad_sv:
            problems = sv.check({**HI_CFG, **change}, "hi")
            self.assertTrue(any(word in p for p in problems), (change, problems))
        self.assertEqual(sv.check({**HI_CFG, "model": "bulbul:v3", "voice": "someone"}, "hi"), [])   # v3 names are not listed here

    def test_a_key_in_voice_json_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi, _, _ = api_editions(tmp)
            for cfg in ({"api_key": EL_KEY}, {"settings": {**EN_CFG["settings"], "xi-api-key": EL_KEY}}):
                c = configure(en, {**EN_CFG, **cfg})
                r, info = voice.plan(en)
                self.assertIsNone(info)
                self.assertTrue(any("belong in the environment" in e for e in r.errors), r.errors)
                self.assertFalse(any(EL_KEY in e for e in r.errors))
                c.pop("api_key", None); c["settings"] = EN_CFG["settings"]; L.save(en / "voice.json", c)
            self.assertTrue(any("belong in the environment" in e for e in V.secret_fields({"mock": {"token": "x"}})))

    def test_the_provider_holds_no_key(self):
        with mock.patch.dict(os.environ, KEYS):
            for prov in (V.ElevenLabs(EN_CFG), V.Sarvam(HI_CFG)):
                self.assertNotIn(EL_KEY, repr(vars(prov))); self.assertNotIn(SV_KEY, repr(vars(prov)))


class CostsAndGuard(unittest.TestCase):
    def test_estimates(self):
        self.assertAlmostEqual(V.ElevenLabs(EN_CFG).estimate_cost(1000), 0.10)
        self.assertAlmostEqual(V.ElevenLabs({**EN_CFG, "model": "eleven_flash_v2_5"}).estimate_cost(1000), 0.05)
        self.assertAlmostEqual(V.ElevenLabs({**EN_CFG, "price_per_1k": 0.3}).estimate_cost(2500), 0.75)
        sv = V.Sarvam(HI_CFG)
        self.assertAlmostEqual(sv.estimate_inr(10000), 15.0)
        self.assertAlmostEqual(sv.estimate_cost(10000), 15.0 / 85)
        self.assertAlmostEqual(V.Sarvam({**HI_CFG, "model": "bulbul:v3"}).estimate_inr(10000), 30.0)
        self.assertAlmostEqual(V.Sarvam({**HI_CFG, "inr_per_10k_chars": 18}).estimate_inr(5000), 9.0)
        self.assertEqual(V.Sarvam({**HI_CFG, "inr_per_usd": None}).estimate_cost(10), float("inf"))
        self.assertIn("₹", sv.describe_cost(sv.estimate_cost(1000)))

    def test_cap_and_confirmation_before_any_request(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, hcfg = api_editions(tmp)
            api = el_api()
            pricey = V.ElevenLabs({**cfg, "price_per_1k": 500.0}, http=http(api))
            r = voice.synth(en, provider=pricey, confirm=True, **NOLOG)
            self.assertTrue(any("over the cap of $5.00" in e for e in r.errors), r.errors)
            r = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(api)), **NOLOG)
            self.assertTrue(any("--confirm-cost" in e for e in r.errors))
            r = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, max_cost=0.0001, **NOLOG)
            self.assertTrue(any("over the cap" in e for e in r.errors))
            quiet(voice.review, hi, "Reviewer A")
            r = voice.synth(hi, provider=V.Sarvam({**hcfg, "inr_per_10k_chars": 1e7}, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(any("over the cap" in e and "₹" in e for e in r.errors), r.errors)
            self.assertEqual(api.calls, [])
            for ed in (en, hi):
                self.assertFalse((ed / "audio" / "voice" / "spend.json").exists())
                self.assertFalse((ed / "audio" / "voice" / "segments").exists() and any((ed / "audio" / "voice" / "segments").iterdir()))

    def test_a_request_over_the_provider_limit_is_not_sent(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, _ = api_editions(tmp)
            cfg = configure(en, {"max_chars": 40})
            api = el_api()
            r = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(any("takes at most 40" in e for e in r.errors), r.errors)
            self.assertEqual(api.calls, [])
            with self.assertRaises(V.ProviderError):
                V.ElevenLabs(cfg, http=http(api)).synthesize("x" * 41, pathlib.Path(tmp) / "x.wav", "en", EL_VOICE, {})
            self.assertEqual(api.calls, [])

    def test_retries_are_billed_once_and_the_rate_does_not_remake_audio(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, _, cfg = api_editions(tmp)
            quiet(voice.review, hi, "Reviewer A")
            api = sv_api(script=[(429, {"Retry-After": "1"}, b"{}"), (502, {}, b"")])
            r = voice.synth(hi, provider=V.Sarvam(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            lines = sum(len(t["lines"]) for t in L.load(hi / "script.json")["takes"])
            self.assertEqual(len(api.calls), lines + 2)
            self.assertEqual(len(L.load(hi / "audio" / "voice" / "spend.json")["requests"]), lines)
            cfg = configure(hi, {"inr_per_usd": 90.0})                          # a new exchange rate: same audio
            self.assertEqual(set(voice.plan(hi)[1]["rows"][i]["state"] for i in range(lines)), {"ok"})
            configure(hi, {"voice": "vidya"})                                   # a new speaker: made again
            self.assertEqual({x["state"] for x in voice.plan(hi)[1]["rows"]}, {"stale"})


class AuditionAndVerify(unittest.TestCase):
    def test_audition_is_gated_kept_apart_and_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, hcfg = api_editions(tmp)
            api = el_api()
            prov = V.ElevenLabs(cfg, http=http(api))
            r = voice.audition(en, lines=3, provider=prov, **NOLOG)
            self.assertTrue(any("--confirm-cost" in e for e in r.errors)); self.assertEqual(api.calls, [])
            r = voice.audition(en, lines=3, provider=V.ElevenLabs({**cfg, "price_per_1k": 1e6}, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(any("over the cap" in e for e in r.errors)); self.assertEqual(api.calls, [])
            r = voice.audition(en, lines=3, provider=prov, confirm=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(len(api.calls), 3)
            self.assertTrue(all(c[3].get("next_text") or c[3].get("previous_text") for c in api.calls))
            d = en / "audio" / "voice" / "auditions" / f"elevenlabs-eleven_multilingual_v2-{EL_VOICE}"
            a = L.load(d / "audition.json")
            self.assertEqual((a["lang"], a["provider"], len(a["lines"])), ("en", "elevenlabs", 3))
            self.assertTrue((d / "L0001.wav").exists())
            self.assertFalse((en / "audio" / "voice" / "manifest.json").exists())   # auditions are never segments
            self.assertFalse((en / "audio" / "voice" / "segments").exists())
            spend = L.load(en / "audio" / "voice" / "spend.json")["requests"]
            self.assertEqual([x["what"] for x in spend], ["audition line 1", "audition line 2", "audition line 3"])
            r = voice.audition(en, lines=3, provider=prov, confirm=True, **NOLOG)
            self.assertTrue(any("already has a elevenlabs audition" in e for e in r.errors)); self.assertEqual(len(api.calls), 3)
            self.assertTrue(voice.audition(en, lines=1, provider=prov, confirm=True, again=True, **NOLOG).ok)
            self.assertEqual(len(api.calls), 4)
            # Hindi: the review first, then the Sarvam sample
            sapi = sv_api()
            r = voice.audition(hi, lines=2, provider=V.Sarvam(hcfg, http=http(sapi)), confirm=True, **NOLOG)
            self.assertTrue(any("native-speaker review" in e for e in r.errors)); self.assertEqual(sapi.calls, [])
            quiet(voice.review, hi, "Reviewer A")
            self.assertTrue(voice.audition(hi, lines=2, provider=V.Sarvam(hcfg, http=http(sapi)), confirm=True, **NOLOG).ok)
            self.assertEqual(len(sapi.calls), 2)

    def test_verify_is_offline_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, _ = api_editions(tmp)
            r = voice.verify(en)
            self.assertTrue(r.ok, r.errors); self.assertTrue(any("nothing was sent" in n for n in r.notes))
            r = voice.verify(en, online=True)                                   # the real client, offline: refused
            self.assertTrue(any("CINEMATIC_OFFLINE" in e for e in r.errors))
            api = el_api()
            v = V.ElevenLabs(cfg, http=http(api)).verify(EL_VOICE)
            self.assertEqual((v["name"], api.calls[0][0], api.calls[0][1]), ("Narrator", "GET", f"https://api.elevenlabs.io/v1/voices/{EL_VOICE}"))
            self.assertIsNone(api.calls[0][3])
            self.assertTrue(any("checked offline" in n for n in voice.verify(hi).notes))


class NoKeyLeaks(unittest.TestCase):
    def test_keys_never_reach_files_messages_or_output(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, hcfg = api_editions(tmp)
            quiet(voice.review, hi, "Reviewer A")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                r1 = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(el_api())), confirm=True)
                r2 = voice.synth(hi, provider=V.Sarvam(hcfg, http=http(sv_api())), confirm=True)
                # services that echo the key back in a refusal
                echo = FakeApi(script=[(401, {}, json.dumps({"detail": f"key {EL_KEY} is not valid"}).encode())])
                c = configure(en, {"voice": "AAAAAAAAAAAAAAAAAAAA"})
                r3 = voice.synth(en, provider=V.ElevenLabs(c, http=http(echo)), confirm=True)
                echo = FakeApi(script=[(403, {}, f"forbidden for {SV_KEY}".encode())])
                c = configure(hi, {"voice": "vidya"})
                r4 = voice.synth(hi, provider=V.Sarvam(c, http=http(echo)), confirm=True, only={1})
                print(r1.report("en")); print(r2.report("hi")); print(r3.report("en")); print(r4.report("hi"))
            self.assertTrue(r1.ok and r2.ok, (r1.errors, r2.errors))
            self.assertFalse(r3.ok or r4.ok)
            text = out.getvalue() + json.dumps([r.errors + r.warnings + r.notes for r in (r1, r2, r3, r4)], ensure_ascii=False)
            self.assertIn("[redacted]", text)
            self.assertNotIn(EL_KEY, text); self.assertNotIn(SV_KEY, text)
            self.assertEqual(leaks(proj), [])                                   # manifests, spend logs, voice.json, audio
            env = {**os.environ, **KEYS}
            import subprocess
            for args in (["providers"], ["plan", "--project", str(en)], ["status", "--project", str(hi)],
                         ["verify", "--project", str(en)], ["synth", "--project", str(en)]):
                p = subprocess.run([sys.executable, str(SCRIPTS / "voice.py"), *args], capture_output=True, text=True, env=env)
                self.assertNotIn(EL_KEY, p.stdout + p.stderr); self.assertNotIn(SV_KEY, p.stdout + p.stderr)
            p = subprocess.run([sys.executable, str(SCRIPTS / "voice.py"), "providers"], capture_output=True, text=True, env=env)
            self.assertIn("ELEVENLABS_API_KEY set", p.stdout); self.assertIn("SARVAM_API_KEY set", p.stdout)
            self.assertEqual(leaks(proj), [])


if __name__ == "__main__":
    unittest.main()
