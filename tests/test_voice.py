"""Tests for milestone 3.3: the per-edition voice framework (the API providers: test_voice_api). Offline (CINEMATIC_OFFLINE=1) and
standard library only, except the espeak test (it needs espeak-ng; the CI film job has it).
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import beats  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import lang  # noqa: E402
import narration  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_docpipe import add_research, cli, fill_narration, fill_outline, make_project, quiet  # noqa: E402
from test_editions import production, write_english, write_hindi  # noqa: E402

NOLOG = dict(log=lambda *a: None)


def two_editions(tmp, provider="mock", **cfg):
    proj = production(tmp)
    write_english(proj)
    beats.build(proj, log=lambda *a: None)
    hi = write_hindi(proj)
    en = editions.edition_dir(proj, "en")
    for ed in (en, hi):
        quiet(narration.fill_spoken, ed)
        assert quiet(narration.export, ed).ok
        c = L.load(ed / "voice.json"); c["provider"] = provider; c.update(cfg)
        L.save(ed / "voice.json", c)
    return proj, en, hi


def seg(ed, line):
    return ed / "audio" / "voice" / "segments" / voice.seg_name(line)


def manifest(ed):
    return L.load(ed / "audio" / "voice" / "manifest.json")


def states(ed):
    return {x["line"]: x["state"] for x in voice.plan(ed)[1]["rows"]}


class Counting(V.Mock):
    """The mock, counting what it was asked to read."""


class Registry(unittest.TestCase):
    def test_providers(self):
        self.assertIsInstance(V.get("mock"), V.Mock)
        self.assertIsInstance(V.get("espeak"), V.Espeak)
        self.assertIsInstance(V.get("command", {"cmd": "x"}), V.Command)
        self.assertIsInstance(V.get("elevenlabs"), V.ElevenLabs)                 # milestone 3.4 (tests: test_voice_api)
        self.assertIsInstance(V.get("sarvam"), V.Sarvam)
        with self.assertRaises(V.ProviderError):
            V.get("azure")
        self.assertFalse(any(V.get(n, {"cmd": "x"}).paid for n in ("mock", "espeak", "command")))
        self.assertTrue(all(V.get(n).paid for n in ("elevenlabs", "sarvam")))
        out = cli("voice.py", "providers").stdout
        self.assertIn("espeak", out); self.assertIn("ELEVENLABS_API_KEY", out); self.assertIn("SARVAM_API_KEY", out)

    def test_default_voice_per_language(self):
        en, hi = voice.default_config("en"), voice.default_config("hi")
        self.assertEqual((en["locale"], en["voice"], en["settings"]["wpm"]), ("en-US", "en-us", 150))
        self.assertEqual((hi["locale"], hi["voice"], hi["settings"]["wpm"]), ("hi-IN", "hi", 135))


class Isolation(unittest.TestCase):
    def test_each_edition_has_its_own_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            self.assertEqual((L.load(en / "voice.json")["lang"], L.load(hi / "voice.json")["lang"]), ("en", "hi"))
            self.assertTrue(editions.check(proj, "hi").ok)
            self.assertFalse(quiet(voice.init, hi))                           # never overwrites
            c = L.load(hi / "voice.json")
            for bad, msg in ((dict(lang="en"), "voice.json is for 'en'"), (dict(locale="en-US"), "locale 'en-US' is not hi"),
                             (dict(provider="espeak", voice="en-us"), "speaks another language")):
                L.save(hi / "voice.json", {**c, **bad})
                r, _ = voice.plan(hi)
                self.assertTrue(any(msg in e for e in r.errors), (bad, r.errors))
            L.save(hi / "voice.json", {**c, "lang": "en"})
            self.assertTrue(any("voice.json is tagged 'en'" in e for e in editions.check(proj, "hi").errors))

    def test_a_script_or_manifest_from_another_edition_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            shutil.copy(en / "script.json", hi / "script.json")
            r, _ = voice.plan(hi)
            self.assertTrue(any("the en script" in e for e in r.errors))
            quiet(narration.export, hi, force=True)
            voice.synth(en, **NOLOG)
            (hi / "audio" / "voice").mkdir(parents=True, exist_ok=True)
            shutil.copy(en / "audio" / "voice" / "manifest.json", hi / "audio" / "voice" / "manifest.json")
            self.assertFalse(voice.synth(hi, **NOLOG).ok)

    def test_lexicons_stay_in_their_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            L.save(hi / "lexicon.json", {"lang": "hi", "terms": {"Wright": {"spoken": "राइट"}}, "allow": []})
            self.assertEqual(lang.for_paths(L.paths(en)).spoken_text("Wright"), "Wright")
            self.assertEqual(lang.for_paths(L.paths(hi)).spoken_text("Wright"), "राइट")


class Generation(unittest.TestCase):
    def test_segments_manifest_and_resume_in_both_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            for ed, code in ((en, "en"), (hi, "hi")):
                r = voice.synth(ed, **NOLOG)
                self.assertTrue(r.ok, r.errors)
                m = manifest(ed)
                self.assertEqual(m["lang"], code)
                lines = [l["id"] for t in L.load(ed / "script.json")["takes"] for l in t["lines"]]
                self.assertEqual(sorted(int(k) for k in m["segments"]), sorted(lines))
                e = m["segments"][str(lines[0])]
                self.assertTrue(seg(ed, lines[0]).exists())
                self.assertGreater(e["duration"], 0.3)
                self.assertTrue(e["words"] and e["request_hash"] and e["file_sha256"])
                self.assertEqual((e["provider"], e["source"], e["status"]), ("mock", "provider", "ok"))
                self.assertTrue(set(states(ed).values()) == {"ok"})
            mock = V.Mock()
            r = voice.synth(hi, provider=mock, **NOLOG)
            self.assertEqual(mock.calls, [])                                   # resume: nothing made again
            self.assertIn("made 0 segment(s)", r.notes)

    def test_only_what_changed_is_made_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            voice.synth(hi, **NOLOG)
            n = L.load(L.paths(hi)["narration"]); line = n["sections"][0]["lines"][0]
            line["text"] = "विमान ऊपर उठा।"; line.pop("spoken", None); L.save(L.paths(hi)["narration"], n)
            quiet(narration.fill_spoken, hi); quiet(narration.export, hi)
            self.assertEqual(states(hi)[line["id"]], "stale")
            mock = V.Mock()
            voice.synth(hi, provider=mock, **NOLOG)
            self.assertEqual(mock.calls, ["विमान ऊपर उठा।"])
            c = L.load(hi / "voice.json"); c["settings"]["wpm"] = 130; L.save(hi / "voice.json", c)
            self.assertEqual(set(states(hi).values()), {"stale"})              # a new setting: every line again

    def test_edited_files_are_locked_and_force_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            voice.synth(en, **NOLOG)
            f = seg(en, 2)
            V.write_wav(f, [3000] * 22050)                                     # someone trimmed it by hand
            mine = f.read_bytes()
            self.assertEqual(states(en)[2], "edited")
            mock = V.Mock()
            voice.synth(en, provider=mock, **NOLOG)
            self.assertEqual(mock.calls, [])
            self.assertEqual(f.read_bytes(), mine)
            self.assertTrue(any("line 2" in n and "locked" in n for n in voice.validate(en).notes))
            voice.synth(en, force=True, **NOLOG)
            self.assertNotEqual(f.read_bytes(), mine)
            self.assertEqual(f.with_suffix(".wav.bak").read_bytes(), mine)
            # a segment file nobody recorded making is yours too
            m = manifest(en); del m["segments"]["3"]; L.save(en / "audio" / "voice" / "manifest.json", m)
            self.assertEqual(states(en)[3], "edited")

    def test_manual_recordings_always_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            man = hi / "audio" / "voice" / "manual" / voice.seg_name(1)
            V.write_wav(man, [4000 if i % 40 < 20 else -4000 for i in range(22050 * 3)])
            mock = V.Mock()
            r = voice.synth(hi, provider=mock, force=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            self.assertNotIn("राइट बंधुओं का विमान रेत से ऊपर उठा।", mock.calls[:1] if mock.calls else [])
            self.assertFalse(seg(hi, 1).exists())
            e = manifest(hi)["segments"]["1"]
            self.assertEqual((e["source"], e["status"]), ("manual", "manual"))
            V.write_wav(man, [0] * 22050)                                      # a silent recording
            self.assertTrue(any("line 1" in x and "silent" in x for x in voice.validate(hi).errors))

    def test_validation_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            r = voice.validate(en)
            self.assertTrue(any("segment missing" in e for e in r.errors))
            r = voice.synth(en, provider=V.Mock({"fail": "error"}), **NOLOG)
            self.assertFalse(r.ok)
            self.assertFalse(list((en / "audio" / "voice" / "segments").glob("*.wav")))   # no half-made files
            voice.synth(en, provider=V.Mock({"fail": "silent"}), **NOLOG)
            self.assertEqual(set(states(en).values()), {"invalid"})
            voice.synth(en, **NOLOG)                                            # invalid ones are made again
            self.assertEqual(set(states(en).values()), {"ok"})
            V.write_wav(hi / "audio" / "voice" / "manual" / voice.seg_name(2), [32767, -32768] * 22050 * 10)
            r = voice.synth(hi, **NOLOG)
            self.assertTrue(any("line 2" in w and "clips" in w for w in r.warnings))
            self.assertTrue(any("line 2" in w and "expected" in w for w in r.warnings))   # 20 s for a short line


class SectionMode(unittest.TestCase):
    def test_one_read_per_section_cut_into_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp, mode="auto", timestamps=True)
            mock = V.Mock({"timestamps": True})
            r = voice.synth(hi, provider=mock, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            takes = L.load(hi / "script.json")["takes"]
            self.assertEqual(len(mock.calls), len(takes))                      # one request per section
            self.assertTrue(all("\n\n" in c for c in mock.calls))
            m = manifest(hi)
            self.assertEqual(m["segments"]["1"]["mode"], "section")
            for t in takes:
                durs = [m["segments"][str(l["id"])]["duration"] for l in t["lines"]]
                self.assertTrue(all(d > 0.3 for d in durs))
                words = m["segments"][str(t["lines"][1]["id"])]["words"]
                self.assertGreaterEqual(words[0]["start"], 0.0)               # word times from the segment's start
            # one changed line reopens its whole section, but never a locked line in it
            V.write_wav(seg(hi, 2), [5000] * 22050); mine = seg(hi, 2).read_bytes()
            n = L.load(L.paths(hi)["narration"]); n["sections"][0]["lines"][0]["text"] = "विमान ऊपर उठा।"
            n["sections"][0]["lines"][0].pop("spoken", None); L.save(L.paths(hi)["narration"], n)
            quiet(narration.fill_spoken, hi); quiet(narration.export, hi)
            st = states(hi)
            self.assertEqual((st[1], st[2], st[3]), ("stale", "edited", "stale"))
            mock = V.Mock({"timestamps": True})
            voice.synth(hi, provider=mock, **NOLOG)
            self.assertEqual(len(mock.calls), 1)
            self.assertEqual(seg(hi, 2).read_bytes(), mine)

    def test_cutting_needs_matching_timings(self):
        with self.assertRaises(V.ProviderError):
            V.split_takes_by_words([(1, "one two"), (2, "three")], [{"w": "one", "start": 0, "end": 1}])
        cuts = V.split_takes_by_words([(1, "a b"), (2, "c")], [{"w": "a", "start": 0.1, "end": 0.4}, {"w": "b", "start": 0.5, "end": 0.8},
                                                                {"w": "c", "start": 1.2, "end": 1.6}])
        self.assertEqual(cuts[1][1], cuts[2][0])
        self.assertAlmostEqual(cuts[1][1], 1.0)


class SpendGuard(unittest.TestCase):
    def test_cap_confirmation_and_hindi_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            pricey = V.Mock({"paid": True, "price": 50.0})                      # $50 per 1,000 characters
            r = voice.synth(en, provider=pricey, **NOLOG)
            self.assertTrue(any("over the cap of $5.00" in e for e in r.errors))
            self.assertEqual(pricey.calls, [])
            paid = V.Mock({"paid": True, "price": 0.08})
            r = voice.synth(en, provider=paid, **NOLOG)
            self.assertTrue(any("--confirm-cost" in e for e in r.errors))
            self.assertEqual(paid.calls, [])
            r = voice.synth(en, provider=paid, confirm=True, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            spend = L.load(en / "audio" / "voice" / "spend.json")
            self.assertEqual(len(spend["requests"]), len(paid.calls))
            self.assertAlmostEqual(sum(x["usd"] for x in spend["requests"]), sum(len(c) for c in paid.calls) / 1000 * 0.08, places=6)
            # Hindi: a native-speaker review of the current script comes first
            r = voice.synth(hi, provider=V.Mock({"paid": True, "price": 0.08}), confirm=True, **NOLOG)
            self.assertTrue(any("native-speaker review" in e for e in r.errors))
            quiet(voice.review, hi, "Reviewer A")
            self.assertTrue(voice.synth(hi, provider=V.Mock({"paid": True, "price": 0.08}), confirm=True, **NOLOG).ok)
            n = L.load(L.paths(hi)["narration"]); n["sections"][0]["lines"][0]["text"] = "विमान ऊपर उठा।"
            n["sections"][0]["lines"][0].pop("spoken", None); L.save(L.paths(hi)["narration"], n)
            quiet(narration.fill_spoken, hi); quiet(narration.export, hi)
            r = voice.synth(hi, provider=V.Mock({"paid": True, "price": 0.08}), confirm=True, **NOLOG)
            self.assertTrue(any("native-speaker review" in e for e in r.errors))  # a changed script needs a new review
            self.assertTrue(voice.synth(hi, provider=V.Mock(), **NOLOG).ok)         # free scratch needs none


class CommandAndLegacy(unittest.TestCase):
    def test_command_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            tool = pathlib.Path(tmp) / "tts.py"
            tool.write_text("import sys, wave, array\n"
                            "txt, out, lang = sys.argv[1], sys.argv[2], sys.argv[3]\n"
                            "n = len(open(txt, encoding='utf-8').read()) * 800\n"
                            "w = wave.open(out, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)\n"
                            "w.writeframes(array.array('h', [(i * 37) % 6000 - 3000 for i in range(n)]).tobytes()); w.close()\n"
                            "open(out + '.lang', 'w').write(lang)\n")
            c = L.load(hi / "voice.json"); c.update(provider="command", cmd=f"{sys.executable} {tool} {{txt}} {{out}} {{lang}}")
            L.save(hi / "voice.json", c)
            r = voice.synth(hi, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(manifest(hi)["segments"]["1"]["provider"], "command")
            c["cmd"] = f"{sys.executable} -c \"import sys; sys.exit(3)\""; L.save(hi / "voice.json", c)
            self.assertFalse(voice.synth(hi, **NOLOG).ok)

    def test_single_language_project_is_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj); import outline
            quiet(outline.init, proj); fill_outline(proj); quiet(narration.init, proj); fill_narration(proj)
            quiet(narration.export, proj)
            quiet(voice.init, proj, "mock")
            self.assertEqual(L.load(proj / "voice.json")["lang"], "en")
            r = voice.synth(proj, **NOLOG)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(manifest(proj)["lang"], "en")
            self.assertNotIn("lang", L.load(proj / "script.json"))              # the project itself is unchanged


@unittest.skipUnless(shutil.which("espeak-ng"), "needs espeak-ng")
class Espeak(unittest.TestCase):
    def test_real_scratch_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp, provider="espeak")
            c = L.load(en / "voice.json"); c["voice"] = "en-us"; L.save(en / "voice.json", c)
            c = L.load(hi / "voice.json"); c["voice"] = "hi"; L.save(hi / "voice.json", c)
            for ed in (en, hi):
                r = voice.synth(ed, only={1, 2}, **NOLOG)
                self.assertFalse([e for e in r.errors if e.startswith(("line 1:", "line 2:"))], r.errors)
                for line in (1, 2):
                    e = manifest(ed)["segments"][str(line)]
                    self.assertGreater(e["rms"], 0.01)
                    self.assertTrue(0.5 < e["duration"] < 15, e["duration"])
                    with wave.open(str(seg(ed, line))) as w:
                        self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2))
            self.assertEqual(manifest(hi)["segments"]["1"]["voice"], "hi")
            self.assertEqual(manifest(en)["segments"]["1"]["voice"], "en-us")


if __name__ == "__main__":
    unittest.main()
