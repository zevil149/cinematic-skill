"""Tests for milestone 3.6: the rights-gated audio library, per-edition cue sheets and the mix.

Offline (CINEMATIC_OFFLINE=1): the voice is the mock, music and sounds are tones written by the
tests, and the one Freesound lookup goes to a fake opener. The library tests need only the standard
library; the cue sheet and mix tests need numpy and ffmpeg (the film job has both).
"""
import array
import json
import math
import os
import pathlib
import shutil
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

import audiolib  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_voice import NOLOG, two_editions  # noqa: E402
from test_voice_api import FakeApi, http, ok  # noqa: E402

try:
    import numpy as np
    HAVE_MIX = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE_MIX = False

QUIET = dict(log=lambda *a: None)
CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"
BY = "https://creativecommons.org/licenses/by/4.0/"
FS_KEY = "fs-FAKE-key-0123456789-never-leak"


def tone(path, seconds=8.0, freq=220.0, amp=0.3, rate=44100, channels=1):
    n = int(seconds * rate)
    s = [int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    if channels == 2:
        s = [v for x in s for v in (x, x)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(array.array("h", s).tobytes())
    return path


def production(tmp):
    """A small two-edition production (no voice yet): enough for the library."""
    proj, en, hi = two_editions(tmp)
    return proj, en, hi


def add(proj, f, **kw):
    kw.setdefault("kind", "music")
    if "license" in kw:
        kw["license_text"] = kw.pop("license")
    r, a = audiolib.add(proj, f, kw.pop("kind"), kw.pop("source"), log=lambda *x: None, **kw)
    return r, a


class Library(unittest.TestCase):
    def test_licences_decide_what_may_be_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp)
            src = pathlib.Path(tmp) / "mine"
            cases = [
                (dict(source="own", by="Zed"), "cleared", "OWN"),
                (dict(source="cc", license_url=CC0, creator="A"), "cleared", "CC0"),
                (dict(source="cc", license_url=BY, creator="B", source_url="https://example.org/b"), "cleared", "CC-BY"),
                (dict(source="cc", license_url="https://creativecommons.org/licenses/by-sa/4.0/", creator="C"), "cleared", "CC-BY-SA"),
                (dict(source="cc", license_url="https://creativecommons.org/licenses/by-nc/4.0/"), "refused", "RESTRICTED"),
                (dict(source="cc", license_url="https://creativecommons.org/licenses/by-nd/4.0/"), "refused", "RESTRICTED"),
                (dict(source="cc"), "refused", "UNKNOWN"),                                   # no licence stated
                (dict(source="cc", license="free to download"), "refused", "UNKNOWN"),       # downloadable is not a licence
                (dict(source="licensed", license="Library subscription", license_ref="order 77"), "pending", "LICENSED"),
                (dict(source="freesound", freesound_id="123", license_url=CC0, creator="fs"), "pending", "CC0"),
                (dict(source="freesound", freesound_id="124", license="Sampling+"), "refused", "RESTRICTED"),
                (dict(source="freesound", freesound_id="125", license_url="http://creativecommons.org/licenses/by-nc/3.0/"), "refused", "RESTRICTED"),
            ]
            for n, (kw, state, code) in enumerate(cases):
                f = tone(src / f"t{n}.wav", 1.0, 200 + 10 * n)
                r, a = add(proj, f, **kw)
                self.assertEqual((a["clearance"]["status"], a["license"]["code"]), (state, code), kw)
                self.assertEqual(audiolib.usable(proj, a) == "", state == "cleared", kw)
            lib = audiolib.load(proj)["assets"]
            by = next(a for a in lib if a["license"]["code"] == "CC-BY")
            self.assertTrue(by["attribution_required"])
            self.assertIn("by B", by["attribution"]); self.assertIn(BY, by["attribution"]); self.assertIn("example.org/b", by["attribution"])
            self.assertFalse(next(a for a in lib if a["source"] == "own")["attribution_required"])
            # incomplete records are refused outright
            for kw, word in ((dict(source="own"), "--by"), (dict(source="licensed", license="x"), "--license-ref"),
                             (dict(source="freesound", license_url=CC0), "--freesound-id"),
                             (dict(source="youtube"), "--source")):
                r, a = add(proj, tone(src / "x.wav", 0.5, 999), **kw)
                self.assertIsNone(a); self.assertTrue(any(word in e for e in r.errors), r.errors)
            r, a = add(proj, src / "nope.wav", source="own", by="Z")
            self.assertIsNone(a)
            (src / "notes.txt").write_text("hi")
            r, a = add(proj, src / "notes.txt", source="own", by="Z")
            self.assertIsNone(a)

    def test_originals_are_copied_never_touched_and_changes_are_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp)
            f = tone(pathlib.Path(tmp) / "user" / "score.wav", 2.0)
            before, mtime = audiolib.sha_file(f), f.stat().st_mtime
            r, a = add(proj, f, source="own", by="Zed", title="Score")
            self.assertEqual((audiolib.sha_file(f), f.stat().st_mtime), (before, mtime))
            copy = audiolib.lib_paths(proj)["dir"] / a["file"]
            self.assertTrue(copy.exists()); self.assertEqual(audiolib.sha_file(copy), before)
            self.assertEqual(copy.parent.parent, pathlib.Path(proj).resolve() / "audio_library")   # shared, at the production root
            self.assertEqual(a["duration"], 2.0)
            r, again = add(proj, f, source="own", by="Zed")
            self.assertEqual(again["id"], a["id"]); self.assertEqual(len(audiolib.load(proj)["assets"]), 1)
            self.assertEqual(audiolib.lib_paths(en)["json"], audiolib.lib_paths(hi)["json"])        # one library for both editions
            with open(copy, "ab") as fh:
                fh.write(b"\0\0")
            self.assertIn("changed after it was added", audiolib.usable(proj, a))
            self.assertFalse(audiolib.check(proj).ok)
            copy.unlink()
            self.assertIn("missing", audiolib.usable(proj, a))

    def test_clearing_is_recorded_and_needs_a_name_and_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp)
            _, lic = add(proj, tone(pathlib.Path(tmp) / "a.wav", 1.0), source="licensed", license="Store", license_ref="inv 9")
            _, nc = add(proj, tone(pathlib.Path(tmp) / "b.wav", 1.0, 300), source="cc",
                        license_url="https://creativecommons.org/licenses/by-nc/4.0/")
            self.assertFalse(audiolib.clear(proj, lic["id"], "", "x").ok)
            self.assertFalse(audiolib.clear(proj, lic["id"], "Zed", " ").ok)
            self.assertTrue(audiolib.clear(proj, lic["id"], "Zed", "standard licence covers online video").ok)
            r = audiolib.clear(proj, nc["id"], "Zed", "written permission from the composer, 2026-11-01")
            self.assertTrue(any("override" in w for w in r.warnings))
            lib = {a["id"]: a for a in audiolib.load(proj)["assets"]}
            self.assertEqual(lib[lic["id"]]["clearance"]["by"], "Zed"); self.assertFalse(lib[lic["id"]]["clearance"]["override"])
            self.assertTrue(lib[nc["id"]]["clearance"]["override"])
            self.assertEqual(audiolib.usable(proj, lib[nc["id"]]), "")


class Freesound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj, _, _ = production(self.tmp.name)
        _, self.a = add(self.proj, tone(pathlib.Path(self.tmp.name) / "door.wav", 1.0), kind="sfx", source="freesound",
                        freesound_id="4242", license_url=CC0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_sends_nothing_and_the_real_client_is_refused(self):
        r = audiolib.verify(self.proj, self.a["id"])
        self.assertTrue(any("nothing was sent" in n for n in r.notes))
        with mock.patch.dict(os.environ, {"FREESOUND_API_KEY": FS_KEY}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")) as u:
            r = audiolib.verify(self.proj, self.a["id"], online=True)
            self.assertTrue(any("CINEMATIC_OFFLINE" in e for e in r.errors)); u.assert_not_called()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FREESOUND_API_KEY", None)
            r = audiolib.verify(self.proj, self.a["id"], online=True, http=http(FakeApi(script=[])))
            self.assertTrue(any("FREESOUND_API_KEY is not set" in e for e in r.errors))
        self.assertEqual(audiolib.get(self.proj, self.a["id"])["clearance"]["status"], "pending")

    def test_the_page_licence_must_match(self):
        api = FakeApi(script=[ok({"id": 4242, "name": "door", "username": "foley_ann", "license": CC0,
                                  "url": "https://freesound.org/people/foley_ann/sounds/4242/"})])
        with mock.patch.dict(os.environ, {"FREESOUND_API_KEY": FS_KEY}):
            r = audiolib.verify(self.proj, self.a["id"], online=True, http=http(api))
        self.assertTrue(r.ok, r.errors)
        method, url, headers, body = api.calls[0]
        self.assertEqual((method, url), ("GET", "https://freesound.org/apiv2/sounds/4242/?fields=id,name,username,license,url"))
        self.assertEqual(headers["Authorization"], f"Token {FS_KEY}"); self.assertIsNone(body)   # metadata only, no download
        a = audiolib.get(self.proj, self.a["id"])
        self.assertEqual((a["clearance"]["status"], a["creator"]), ("cleared", "foley_ann"))
        self.assertNotIn(FS_KEY, audiolib.lib_paths(self.proj)["json"].read_text())
        # another sound whose page says non-commercial: refused, whatever was recorded
        _, b = add(self.proj, tone(pathlib.Path(self.tmp.name) / "rain.wav", 1.0, 330), kind="sfx", source="freesound",
                   freesound_id="77", license_url=CC0)
        api = FakeApi(script=[ok({"id": 77, "license": "http://creativecommons.org/licenses/by-nc/4.0/", "username": "x"})])
        with mock.patch.dict(os.environ, {"FREESOUND_API_KEY": FS_KEY}):
            r = audiolib.verify(self.proj, b["id"], online=True, http=http(api))
        self.assertFalse(r.ok)
        self.assertEqual(audiolib.get(self.proj, b["id"])["clearance"]["status"], "refused")


def voiced(tmp):
    import narrate
    proj, en, hi = two_editions(tmp)
    for ed in (en, hi):
        assert voice.synth(ed, **NOLOG).ok
        assert narrate.build(ed, retime=False, **QUIET).ok
    return proj, en, hi


@unittest.skipUnless(HAVE_MIX, "needs numpy and ffmpeg")
class CueSheets(unittest.TestCase):
    def test_cues_are_placed_on_each_editions_own_timing(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = voiced(tmp)
            _, m = add(proj, tone(pathlib.Path(tmp) / "m.wav", 30.0), source="own", by="Zed")
            _, s = add(proj, tone(pathlib.Path(tmp) / "s.wav", 0.5, 900), kind="sfx", source="cc", license_url=CC0)
            for ed in (en, hi):
                self.assertTrue(cuesheet.init(ed, **QUIET).ok)
                t = L.load(ed / "audio" / "timing.json")
                seg = {x["id"]: x for x in t["segments"]}
                sheet = L.load(ed / "audio" / "cues.json")
                takes = L.load(ed / "script.json")["takes"]
                sec2 = takes[1]["section"]
                word = seg[3]["words"][1]["w"]
                sheet["music"].append({"id": "M2", "asset": m["id"], "from": {"line": 3, "word": word, "shift": -0.25},
                                       "to": {"section": sec2, "edge": "end"}, "gain_db": -12, "fade_in": 1, "fade_out": 2, "loop": True})
                sheet["sfx"] = [{"id": "S1", "asset": s["id"], "at": {"line": 5, "edge": "end", "shift": 0.1}}]
                sheet["gaps"] = [{"from": {"section": sec2, "edge": "start", "shift": -1.0}, "to": {"section": sec2, "edge": "start"}}]
                L.save(ed / "audio" / "cues.json", sheet)
                r, info = cuesheet.plan(ed)
                self.assertTrue(r.ok, r.errors)
                m2 = next(c for c in info["music"] if c["id"] == "M2")
                last2 = [l["id"] for l in takes[1]["lines"]][-1]
                first2 = takes[1]["lines"][0]["id"]
                self.assertAlmostEqual(m2["t0"], seg[3]["words"][1]["start"] - 0.25, places=3)
                self.assertAlmostEqual(m2["t1"], seg[last2]["end"], places=3)
                self.assertAlmostEqual(info["sfx"][0]["t"], seg[5]["end"] + 0.1, places=3)
                self.assertAlmostEqual(info["gaps"][0]["t0"], seg[first2]["start"] - 1.0, places=3)
                m1 = info["music"][0]
                self.assertEqual((m1["t0"], m1["t1"]), (0.0, t["total_duration"]))
            # each edition's times are its own
            pe, ph = cuesheet.plan(en)[1], cuesheet.plan(hi)[1]
            self.assertNotEqual(pe["sfx"][0]["t"], ph["sfx"][0]["t"])

    def test_bad_cues_and_uncleared_assets_stop_the_plan(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = voiced(tmp)
            _, pend = add(proj, tone(pathlib.Path(tmp) / "p.wav", 5.0), source="licensed", license="Store", license_ref="inv 1")
            _, nc = add(proj, tone(pathlib.Path(tmp) / "n.wav", 5.0, 300), source="cc",
                        license_url="https://creativecommons.org/licenses/by-nc/4.0/")
            _, fx = add(proj, tone(pathlib.Path(tmp) / "f.wav", 0.4, 800), kind="sfx", source="cc", license_url=CC0)
            cuesheet.init(en, **QUIET)
            sheet = L.load(en / "audio" / "cues.json")
            bad = [({"asset": pend["id"]}, "pending"), ({"asset": nc["id"]}, "refused"), ({"asset": "A999"}, "not in the library"),
                   ({"asset": fx["id"]}, "is sfx, used as music"), ({"from": {"line": 999}}, "line 999"),
                   ({"from": {"section": "nope"}}, "section 'nope'"), ({"from": {"t": 99999}}, "outside the film"),
                   ({"from": {"line": 2, "word": "zzzz"}}, "not a timed word"), ({"from": {"t": 10}, "to": {"t": 10.2}}, "at least 0.5s")]
            for change, word in bad:
                s2 = json.loads(json.dumps(sheet)); s2["music"][0].update(change)
                L.save(en / "audio" / "cues.json", s2)
                r, info = cuesheet.plan(en)
                self.assertTrue(any(word in e for e in r.errors), (change, r.errors))
                r = cuesheet.mix(en, **QUIET)
                self.assertFalse(r.ok)
                self.assertFalse((en / "audio" / "mix.m4a").exists())              # nothing uncleared is ever mixed
            s2 = json.loads(json.dumps(sheet)); s2["sfx"] = [{"id": "S1", "asset": "synth:bed", "at": {"t": 1}}]
            L.save(en / "audio" / "cues.json", s2)
            self.assertTrue(any("synth:bed is music" in e for e in cuesheet.plan(en)[0].errors))

    def test_editions_keep_their_own_cue_sheets_timing_and_mix(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = voiced(tmp)
            cuesheet.init(en, **QUIET); cuesheet.init(hi, **QUIET)
            self.assertEqual((L.load(en / "audio" / "cues.json")["lang"], L.load(hi / "audio" / "cues.json")["lang"]), ("en", "hi"))
            shutil.copyfile(en / "audio" / "cues.json", hi / "audio" / "cues.json")
            r, _ = cuesheet.plan(hi)
            self.assertTrue(any("is the en edition's cue sheet" in e for e in r.errors))
            self.assertFalse(editions.check(proj, "hi").ok)
            (hi / "audio" / "cues.json").unlink(); cuesheet.init(hi, **QUIET)
            t = L.load(hi / "audio" / "timing.json"); t["lang"] = "en"; L.save(hi / "audio" / "timing.json", t)
            self.assertTrue(any("is the en voice" in e for e in cuesheet.plan(hi)[0].errors))


@unittest.skipUnless(HAVE_MIX, "needs numpy and ffmpeg")
class Signal(unittest.TestCase):
    def test_ducking_dips_under_speech_and_starts_before_it(self):
        import cuesheet
        sr = cuesheet.SR
        voice_ = np.zeros(4 * sr)
        voice_[2 * sr:3 * sr] = 0.2 * np.sin(2 * np.pi * 200 * np.arange(sr) / sr)
        duck = {"db": -12.0, "threshold": 0.015, "attack": 0.08, "release": 0.6}
        g, speech = cuesheet.duck_curve(voice_, len(voice_), duck)
        self.assertAlmostEqual(g[int(1.0 * sr)], 1.0, places=3)                          # silence: full music
        self.assertAlmostEqual(20 * math.log10(g[int(2.6 * sr)]), -12.0, delta=0.3)       # speech: down 12 dB
        self.assertLess(g[int(2.0 * sr)], 0.95)                                          # already dipping as the word starts
        self.assertLess(g[int(3.2 * sr)], g[int(3.9 * sr)])                              # released slowly after
        self.assertGreater(g[int(3.9 * sr)], 0.6)

    def test_fades_gaps_and_the_bed(self):
        import cuesheet
        sr = cuesheet.SR
        g = cuesheet.ramp_gain(5 * sr, 0, 5, 1.0, 2.0)
        self.assertEqual(g[0], 0.0); self.assertAlmostEqual(g[int(0.5 * sr)], 0.5, places=2)
        self.assertEqual(g[int(2.5 * sr)], 1.0); self.assertAlmostEqual(g[int(4.0 * sr)], 0.5, places=2); self.assertAlmostEqual(g[-1], 0.0, places=3)
        gap = cuesheet.gap_curve(10 * sr, [{"t0": 4.0, "t1": 6.0, "fade": 0.5}])
        self.assertEqual(gap[int(5 * sr)], 0.0); self.assertEqual(gap[int(2 * sr)], 1.0); self.assertEqual(gap[int(8 * sr)], 1.0)
        self.assertAlmostEqual(gap[int(3.75 * sr)], 0.5, places=2); self.assertAlmostEqual(gap[int(6.25 * sr)], 0.5, places=2)
        bed = cuesheet.synth_bed(20.0, [10.0], seed=3)
        self.assertEqual(bed.shape, (20 * sr, 2))
        self.assertTrue(np.array_equal(bed, cuesheet.synth_bed(20.0, [10.0], seed=3)))   # deterministic
        self.assertLess(np.max(np.abs(bed)), 0.91)
        self.assertEqual(float(np.max(np.abs(bed[int(9.2 * sr):int(10.4 * sr)]))), 0.0)   # silent into the section change
        self.assertGreater(float(np.sqrt(np.mean(bed[: 8 * sr] ** 2))), 0.05)


@unittest.skipUnless(HAVE_MIX, "needs numpy and ffmpeg")
class Mix(unittest.TestCase):
    def test_mix_loudness_intelligibility_credits_resume_and_protection(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = voiced(tmp)
            _, m = add(proj, tone(pathlib.Path(tmp) / "score.wav", 40.0, 110, 0.5, channels=2), source="cc",
                       license_url=BY, creator="Composer K", title="Low Score", source_url="https://example.org/score")
            _, s = add(proj, tone(pathlib.Path(tmp) / "hit.wav", 0.3, 700, 0.6), kind="sfx", source="own", by="Zed")
            sfx = tone(en / "audio" / "sfx.wav", L.load(en / "audio" / "timing.json")["total_duration"], 60, 0.05, 48000, 2)
            protected = {f: audiolib.sha_file(f) for f in [en / "audio" / "narration.m4a", sfx,
                         audiolib.lib_paths(proj)["dir"] / m["file"], audiolib.lib_paths(proj)["dir"] / s["file"],
                         *sorted((en / "audio" / "voice" / "segments").glob("*.wav"))]}
            cuesheet.init(en, **QUIET)
            sheet = L.load(en / "audio" / "cues.json")
            sheet["music"].append({"id": "M2", "asset": m["id"], "from": {"line": 4}, "to": {"line": 9, "edge": "end"},
                                   "gain_db": -10, "loop": True})
            sheet["sfx"] = [{"id": "S1", "asset": s["id"], "at": {"line": 2}}]
            sheet["gaps"] = [{"from": {"line": 6}, "to": {"line": 7}}]
            L.save(en / "audio" / "cues.json", sheet)
            r = cuesheet.mix(en, **QUIET)
            self.assertTrue(r.ok, r.errors)
            rep = L.load(en / "audio" / "mix_report.json")
            self.assertEqual((rep["lang"], rep["built_by"]), ("en", "cuesheet.py"))
            self.assertLessEqual(abs(rep["lufs"] - (-15.0)), 1.0)                            # -15 LUFS integrated
            self.assertLessEqual(rep["true_peak_dbtp"], -1.0)
            self.assertEqual(rep["clipped_samples"], 0); self.assertLess(rep["sample_peak"], 0.95)
            self.assertGreaterEqual(rep["voice_over_music_db"], 10.0)                        # the narration stays on top
            self.assertAlmostEqual(rep["duration"], L.load(en / "audio" / "timing.json")["total_duration"], delta=0.25)
            got_i, got_tp = cuesheet.measure(en / "audio" / "mix.m4a")                       # measured again, independently
            self.assertLessEqual(abs(got_i + 15.0), 1.0)
            used = {a["id"]: a for a in rep["assets"]}
            self.assertEqual(set(used), {m["id"], s["id"]})
            self.assertTrue(used[m["id"]]["attribution_required"])
            credits = (en / "audio" / "music_credits.md").read_text()
            self.assertIn("Composer K", credits); self.assertIn(BY, credits); self.assertIn("synthesised", credits)
            self.assertEqual({f: audiolib.sha_file(f) for f in protected}, protected)       # originals and narration untouched
            self.assertFalse((hi / "audio" / "mix.m4a").exists())                            # the other edition untouched
            self.assertTrue(editions.check(proj, "en").ok)
            # resume
            h = audiolib.sha_file(en / "audio" / "mix.m4a")
            self.assertTrue(any("up to date" in n for n in cuesheet.mix(en, **QUIET).notes))
            sheet["music"][1]["gain_db"] = -14; L.save(en / "audio" / "cues.json", sheet)
            self.assertTrue(cuesheet.mix(en, **QUIET).ok)
            self.assertNotEqual(audiolib.sha_file(en / "audio" / "mix.m4a"), h)
            # a mix you changed, or one from mix_soundtrack.py, is never replaced without --force
            with open(en / "audio" / "mix.m4a", "ab") as fh:
                fh.write(b"\0")
            mine = audiolib.sha_file(en / "audio" / "mix.m4a")
            sheet["music"][1]["gain_db"] = -16; L.save(en / "audio" / "cues.json", sheet)
            r = cuesheet.mix(en, **QUIET)
            self.assertTrue(any("changed since" in e for e in r.errors)); self.assertEqual(audiolib.sha_file(en / "audio" / "mix.m4a"), mine)
            self.assertTrue(cuesheet.mix(en, force=True, **QUIET).ok)
            self.assertEqual(audiolib.sha_file(en / "audio" / "mix.m4a.bak"), mine)

    def test_a_mix_that_buries_the_voice_or_misses_loudness_is_not_written(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = voiced(tmp)
            _, m = add(proj, tone(pathlib.Path(tmp) / "loud.wav", 30.0, 300, 0.9), source="own", by="Zed")
            cuesheet.init(hi, **QUIET)
            sheet = L.load(hi / "audio" / "cues.json")
            sheet["music"] = [{"id": "M1", "asset": m["id"], "gain_db": 6, "duck": False, "loop": True}]
            L.save(hi / "audio" / "cues.json", sheet)
            r = cuesheet.mix(hi, **QUIET)
            self.assertTrue(any("over the music while it speaks" in e for e in r.errors), r.errors)
            self.assertFalse((hi / "audio" / "mix.m4a").exists())
            cuesheet_init = L.load(hi / "audio" / "cues.json")
            cuesheet_init["music"] = [{"id": "M1", "asset": "synth:bed", "gain_db": -8}]
            L.save(hi / "audio" / "cues.json", cuesheet_init)
            with mock.patch.object(cuesheet, "measure", return_value=(-21.0, -3.0)):
                r = cuesheet.mix(hi, **QUIET)
            self.assertTrue(any("integrated loudness -21.0" in e for e in r.errors), r.errors)
            self.assertFalse((hi / "audio" / "mix.m4a").exists())
            self.assertTrue(cuesheet.mix(hi, **QUIET).ok)
            self.assertEqual(L.load(hi / "audio" / "mix_report.json")["lang"], "hi")

    def test_missing_narration_or_a_foreign_mix_stops_it(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = two_editions(tmp)
            cuesheet.init(en, **QUIET)
            self.assertTrue(any("narrate.py" in e for e in cuesheet.mix(en, **QUIET).errors))
            proj2, en2, hi2 = voiced(pathlib.Path(tmp) / "b")
            cuesheet.init(en2, **QUIET)
            (en2 / "audio" / "mix.m4a").write_bytes(b"made by mix_soundtrack.py")
            r = cuesheet.mix(en2, **QUIET)
            self.assertTrue(any("not made by cuesheet.py" in e for e in r.errors))
            self.assertEqual((en2 / "audio" / "mix.m4a").read_bytes(), b"made by mix_soundtrack.py")


if __name__ == "__main__":
    unittest.main()
