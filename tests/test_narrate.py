"""Tests for milestone 3.5: timing per edition. An edition's voice segments become its narration
track and timing.json (with word times), the storyboard and scenes follow, and doc.W lands on the
word. Offline: the mock voice, no network (CINEMATIC_OFFLINE=1), no API provider is ever asked.
Needs ffmpeg (the film job has it); the render checks need skia as well.
"""
import array
import math
import os
import pathlib
import shutil
import subprocess
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
import editions  # noqa: E402
import lang  # noqa: E402
import narrate  # noqa: E402
import narration  # noqa: E402
import storyboard  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_docpipe import quiet  # noqa: E402
from test_voice import NOLOG, seg, two_editions  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
try:
    import skia  # noqa: F401
    HAVE_SKIA = True
except Exception:                          # pragma: no cover
    HAVE_SKIA = False

QUIET = dict(log=lambda *a: None)


def no_api():
    """Narration never asks a voice provider for anything: any request fails the test."""
    return mock.patch.object(V.Http, "request", side_effect=AssertionError("narrate.py sent an API request"))


def voiced(tmp):
    proj, en, hi = two_editions(tmp)
    for ed in (en, hi):
        assert voice.synth(ed, **NOLOG).ok
        storyboard.build(ed)
    return proj, en, hi


def timing(ed):
    return L.load(ed / "audio" / "timing.json")


def track(ed):
    return ed / "audio" / "narration.m4a"


def probe_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def recording(path, speech, pad_before=0.6, pad_after=0.8, rate=16000):
    """A 'manual recording': silence, a tone standing in for speech, silence."""
    n0, n1, n2 = int(pad_before * rate), int(speech * rate), int(pad_after * rate)
    s = [0] * n0 + [int(7000 * math.sin(2 * math.pi * 200 * i / rate)) for i in range(n1)] + [0] * n2
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(array.array("h", s).tobytes())


def sha(path):
    return voice.sha_file(path)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class TrackAndTiming(unittest.TestCase):
    def test_each_edition_gets_its_own_track_and_word_timing(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            for ed, code in ((en, "en"), (hi, "hi")):
                r = narrate.build(ed, **QUIET)
                self.assertTrue(r.ok, r.errors)
                t = timing(ed)
                self.assertEqual((t["lang"], t["built_by"], t["source"], t["tempo"]), (code, "narrate.py", "voice", 1.0))
                lines = [l for tk in L.load(ed / "script.json")["takes"] for l in tk["lines"]]
                segs = t["segments"]
                self.assertEqual([s["id"] for s in segs], [l["id"] for l in lines])
                self.assertEqual(segs[0]["start"], L.LEAD)
                for s, l, nxt in zip(segs, lines, segs[1:] + [None]):
                    self.assertEqual((s["caption"], s["vo"]), (l["text"], l["spoken"]))
                    self.assertEqual(len(s["words"]), len(lang.TOKEN.findall(l["spoken"])))
                    self.assertEqual(s["words_from"], "voice")                  # the mock gives word timings
                    times = [w["start"] for w in s["words"]]
                    self.assertEqual(times, sorted(times))
                    self.assertTrue(s["start"] - 1e-3 <= times[0] and s["words"][-1]["end"] <= s["end"] + 1e-3)
                    if nxt:
                        self.assertAlmostEqual(nxt["start"] - s["end"], l.get("gap_after", nxt["start"] - s["end"]), places=2)
                        self.assertGreaterEqual(nxt["start"] - s["end"], L.GAP - 0.01)
                self.assertAlmostEqual(t["total_duration"], segs[-1]["end"] + L.TAIL, places=2)
                self.assertAlmostEqual(probe_seconds(track(ed)), t["total_duration"], delta=0.15)
            # each edition's words are in its own script
            self.assertTrue(all(w["w"].isascii() for w in timing(en)["segments"][0]["words"]))
            self.assertTrue(any("ऀ" <= ch <= "ॿ" for w in timing(hi)["segments"][0]["words"] for ch in w["w"]))
            self.assertNotEqual(timing(en)["total_duration"], timing(hi)["total_duration"])
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)

    def test_resume_and_only_changed_parts(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            self.assertTrue(narrate.build(hi, **QUIET).ok)
            parts = hi / "audio" / "voice" / "build" / "parts"
            before, h = len(list(parts.glob("L*.wav"))), sha(track(hi))
            r = narrate.build(hi, **QUIET)
            self.assertTrue(any("up to date" in n for n in r.notes))
            self.assertEqual(sha(track(hi)), h)
            # one Hindi line changes: its voice is stale, so nothing is built until it is made again
            n = L.load(L.paths(hi)["narration"]); n["sections"][0]["lines"][0]["text"] = "विमान रेत से ऊपर उठा।"
            n["sections"][0]["lines"][0].pop("spoken", None); L.save(L.paths(hi)["narration"], n)
            quiet(narration.fill_spoken, hi); quiet(narration.export, hi)
            r = narrate.build(hi, **QUIET)
            self.assertTrue(any("older text" in e for e in r.errors), r.errors)
            self.assertEqual(sha(track(hi)), h)
            self.assertTrue(voice.synth(hi, **NOLOG).ok)
            self.assertTrue(narrate.build(hi, **QUIET).ok)
            self.assertEqual(len(list(parts.glob("L*.wav"))), before + 1)      # one new part; the rest reused
            self.assertNotEqual(sha(track(hi)), h)
            self.assertFalse((en / "audio" / "timing.json").exists())         # English untouched

    def test_missing_voice_is_reported_and_nothing_is_built_or_bought(self):
        with tempfile.TemporaryDirectory() as tmp, no_api(), mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "x" * 20}):
            proj, en, hi = two_editions(tmp)
            c = L.load(en / "voice.json")
            c.update(provider="elevenlabs", voice="21m00Tcm4TlvDq8ikWAM", model="eleven_multilingual_v2",
                     settings={"stability": 0.5})
            L.save(en / "voice.json", c)
            r = narrate.build(en, **QUIET)
            self.assertFalse(r.ok)
            self.assertTrue(any("voice.py synth" in e for e in r.errors), r.errors)
            self.assertFalse((en / "audio" / "timing.json").exists()); self.assertFalse(track(en).exists())
            self.assertFalse((en / "audio" / "voice" / "spend.json").exists())

    def test_tempo_target(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            self.assertTrue(narrate.build(en, **QUIET).ok)
            natural = timing(en)["total_duration"]
            r = narrate.build(en, target=natural * 0.5, **QUIET)
            self.assertTrue(any("outside" in e for e in r.errors))
            self.assertTrue(narrate.build(en, target=natural - 4, **QUIET).ok)
            t = timing(en)
            self.assertGreater(t["tempo"], 1.0)
            self.assertAlmostEqual(t["total_duration"], natural - 4, delta=0.3)
            s = t["segments"][3]
            self.assertTrue(s["start"] <= s["words"][0]["start"] and s["words"][-1]["end"] <= s["end"] + 1e-3)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class YourAudioIsKept(unittest.TestCase):
    def test_manual_and_edited_audio_is_used_and_never_written(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            man = hi / "audio" / "voice" / "manual" / voice.seg_name(2)
            recording(man, 2.0)
            edited = seg(hi, 3)
            with wave.open(str(edited), "rb") as w:
                params, frames = w.getparams(), w.readframes(w.getnframes())
            with wave.open(str(edited), "wb") as w:                            # you lengthened line 3 by hand
                w.setparams(params); w.writeframes(frames + frames)
            self.assertTrue(voice.synth(hi, **NOLOG).ok)                        # records the manual file; keeps the edit
            hashes = {f: sha(f) for f in (man, edited, seg(hi, 1))}
            r = narrate.build(hi, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual({f: sha(f) for f in hashes}, hashes)               # read, never written
            segs = {s["id"]: s for s in timing(hi)["segments"]}
            self.assertEqual((segs[2]["audio"], segs[2]["words_from"]), ("manual", "estimate"))
            self.assertAlmostEqual(segs[2]["duration"], 2.0 + 2 * narrate.PAD, delta=0.03)   # its silence trimmed
            self.assertEqual((segs[3]["audio"], segs[3]["words_from"]), ("edited", "estimate"))
            self.assertEqual((segs[1]["audio"], segs[1]["words_from"]), ("voice", "voice"))
            self.assertEqual(len(segs[2]["words"]), len(lang.TOKEN.findall(segs[2]["vo"])))

    def test_a_track_you_made_or_changed_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            (en / "audio").mkdir(parents=True, exist_ok=True)
            track(en).write_bytes(b"my own mix")
            L.save(en / "audio" / "timing.json", {"total_duration": 9.0, "segments": []})   # e.g. build_narration.py
            r = narrate.build(en, **QUIET)
            self.assertTrue(any("not made by narrate.py" in e for e in r.errors))
            self.assertEqual(track(en).read_bytes(), b"my own mix")
            self.assertTrue(narrate.build(en, force=True, **QUIET).ok)
            self.assertEqual((en / "audio" / "narration.m4a.bak").read_bytes(), b"my own mix")
            self.assertEqual(L.load(en / "audio" / "timing.json.bak")["total_duration"], 9.0)
            # built by narrate.py, then changed by you: locked again
            with open(track(en), "ab") as f:
                f.write(b"\0")
            h = sha(track(en))
            r = narrate.build(en, lead=1.2, **QUIET)
            self.assertTrue(any("changed since" in e for e in r.errors)); self.assertEqual(sha(track(en)), h)

    def test_timing_from_another_edition_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            self.assertTrue(narrate.build(hi, **QUIET).ok)
            shutil.copyfile(hi / "audio" / "timing.json", en / "audio" / "timing.json")
            r = narrate.build(en, **QUIET)
            self.assertTrue(any("is the hi voice" in e for e in r.errors), r.errors)
            self.assertEqual(timing(en)["lang"], "hi")
            r = storyboard.build(en)
            self.assertTrue(any("is the hi voice" in e for e in r.errors))
            self.assertFalse(editions.check(proj, "en").ok)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class Retime(unittest.TestCase):
    def test_storyboard_and_scenes_follow_the_voice(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            import scenegen
            import visuals
            visuals.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            for ed in (en, hi):
                editions.link_shared(proj, ed)
                self.assertEqual(L.load(ed / "04_scenes" / "storyboard.json")["timing"], "estimate")
                self.assertTrue(scenegen.generate(ed).ok)
            act = en / "06_film" / "act_01" / "scene.py"
            act.write_text(act.read_text() + "\n# my edit\n")
            for ed in (en, hi):
                r = narrate.build(ed, **QUIET)
                self.assertTrue(r.ok, r.errors)
                sb = L.load(ed / "04_scenes" / "storyboard.json")
                t = {s["id"]: s for s in timing(ed)["segments"]}
                self.assertEqual(sb["timing"], "voice")
                self.assertEqual(sb["lang"], ed.name)
                for sc in sb["scenes"]:
                    self.assertAlmostEqual(sc["start"], t[sc["line"]]["start"], places=2)
                acts = L.load(ed / "06_film" / "acts.json")["acts"]
                self.assertEqual({a["timing"] for a in acts}, {"voice"})
                self.assertAlmostEqual(acts[0]["t0"], t[acts[0]["lines"][0]]["start"], places=2)
            self.assertIn("# my edit", act.read_text())                        # your scene is kept
            self.assertTrue(any("has your edits" in w for w in narrate.retime_scenes(en).warnings))


@unittest.skipUnless(HAVE_FFMPEG and HAVE_SKIA, "needs ffmpeg and skia-python")
class WordTimes(unittest.TestCase):
    def test_doc_w_lands_on_each_editions_key_words(self):
        import engine
        import scenekit
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            for ed in (en, hi):
                self.assertTrue(narrate.build(ed, **QUIET).ok)
                doc = engine.Doc(ed)
                lg = lang.get(ed.name)
                for s in timing(ed)["segments"][:8]:
                    kw = lg.key_word(s["vo"])
                    toks = [m.group(0) for m in lang.TOKEN.finditer(s["vo"])]
                    k = next(n for n, tk in enumerate(toks) if kw.lower() in tk.lower())
                    self.assertEqual(doc.W(s["id"], kw), s["words"][k]["start"])
                    self.assertEqual(scenekit.word_time(doc, s["id"], kw), s["words"][k]["start"])
                    self.assertTrue(s["start"] <= doc.W(s["id"], kw) < s["end"])

    def test_without_word_times_doc_w_is_unchanged(self):
        import engine
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            seg_ = {"id": 1, "start": 2.0, "end": 6.0, "duration": 4.0, "vo": "the plane rose from the sand", "caption": ""}
            L.save(d / "audio" / "timing.json", {"total_duration": 9.0, "segments": [seg_]})
            old = engine.Doc(d).W(1, "sand")
            self.assertAlmostEqual(old, 2.0 + 4.0 * len("theplanerosefromthe") / len("theplanerosefromthesand") + 0.04)
            seg_["words"] = [{"w": "the", "start": 2.0, "end": 2.1}]           # times that do not match: the estimate
            L.save(d / "audio" / "timing.json", {"total_duration": 9.0, "segments": [seg_]})
            self.assertEqual(engine.Doc(d).W(1, "sand"), old)
            with self.assertRaises(ValueError):
                engine.Doc(d).W(1, "ocean")


@unittest.skipUnless(HAVE_FFMPEG and HAVE_SKIA, "needs ffmpeg and skia-python")
class Renders(unittest.TestCase):
    def test_both_editions_render_on_their_own_voice(self):
        import scenegen
        import visuals
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = voiced(tmp)
            visuals.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            subprocess.run([sys.executable, str(SCRIPTS / "prep_assets.py"), "--project", str(proj)], capture_output=True, check=True)
            for ed in (en, hi):
                editions.link_shared(proj, ed)
                self.assertTrue(scenegen.generate(ed).ok)
                self.assertTrue(narrate.build(ed, **QUIET).ok)
                kw_t = engine_time(ed)
                r = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "--project", str(ed), "--probe", f"{kw_t:.2f}",
                                    "--size", "320x180"], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-1500:])
                self.assertTrue(list((ed / "out" / "probe").glob("t*.png")))


def engine_time(ed):
    s = timing(ed)["segments"][2]
    return s["words"][len(s["words"]) // 2]["start"]


if __name__ == "__main__":
    unittest.main()
