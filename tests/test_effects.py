"""Tests for milestone 5.1: the effects track (effects.py, docpipe effects@<lang>).

Offline (CINEMATIC_OFFLINE=1): mock voices; every sound is synthesised, nothing downloaded. The act
ranges need only the standard library; the rest needs skia-python, numpy and ffmpeg.
"""
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
import effects  # noqa: E402

try:
    import numpy as np
    import skia  # noqa: F401
    from test_pipeline_audio import HAVE as HAVE_AUDIO, dp, through_gates
    HAVE = HAVE_AUDIO
except ImportError:                          # pragma: no cover
    HAVE = False


def sha(f):
    return effects.sha_file(f)


def read_wav(f):
    import subprocess
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "f32le", "-ac", "1", "-ar", "48000", "pipe:1"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


class ActRanges(unittest.TestCase):
    def test_each_act_has_its_own_part_of_the_film(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            L.save(d / "06_film" / "acts.json", {"acts": [{"act": 2, "scene": "06_film/act_02/scene.py", "t0": 60.0},
                                                          {"act": 1, "scene": "06_film/act_01/scene.py", "t0": 0.9},
                                                          {"act": 3, "scene": "06_film/act_03/scene.py", "t0": 120.0}]})
            got = [(n, s, e) for n, _, s, e in effects.act_list(effects.ep(d), 180.0)]
            self.assertEqual(got, [(1, 0.0, 60.0), (2, 60.0, 120.0), (3, 120.0, 180.0)])   # no gaps, no overlaps
            (d / "06_film" / "acts.json").unlink()
            self.assertEqual(effects.act_list(effects.ep(d), 10.0), [])
            (d / "scene.py").write_text("def build_film(doc): pass\n")
            self.assertEqual([(n, s, e) for n, _, s, e in effects.act_list(effects.ep(d), 10.0)], [(1, 0.0, 10.0)])


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class EffectsTrack(unittest.TestCase):
    def test_scene_and_cue_sheet_cues_resume_and_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="all", until="subtitles")
            self.assertTrue(ok, out)
            self.assertLess(out.index("[narration@en]"), out.index("[effects@en]"))
            self.assertLess(out.index("[effects@en]"), out.index("[sound@en]"))          # the mix hears the effects
            for ed, code in ((en, "en"), (hi, "hi")):
                rep = L.load(ed / "audio" / "effects.json")
                self.assertEqual((rep["lang"], rep["built_by"]), (code, "effects.py"))
                self.assertGreater(len(rep["cues"]), 5)
                self.assertTrue(all(c["source"] == "scene" and c["act"] == 1 for c in rep["cues"]))
                self.assertTrue(L.load(ed / "audio" / "mix_report.json")["synth_sfx"])
                self.assertGreater(float(np.abs(read_wav(ed / "audio" / "sfx.wav")).max()), 0.05)
            ok, out = dp(proj, lang="all", until="subtitles")
            self.assertIn("[effects@hi] up to date", out); self.assertIn("[sound@hi] up to date", out)
            # explicit cues from the cue sheet, on the Hindi timing
            sheet = L.load(hi / "audio" / "cues.json")
            seg = {s["id"]: s for s in L.load(hi / "audio" / "timing.json")["segments"]}
            sheet["synth_cues"] = [{"kind": "boom", "at": {"line": 3}, "gain": 0.6},
                                   {"kind": "riser", "at": {"line": 7, "shift": -1.3}, "dur": 1.2, "gain": 0.5}]
            sheet["effects"] = {"gain": 0.8}
            L.save(hi / "audio" / "cues.json", sheet)
            before = sha(hi / "audio" / "sfx.wav")
            ok, out = dp(proj, lang="hi", until="subtitles")
            self.assertTrue(ok, out); self.assertNotIn("[effects@hi] up to date", out)
            rep = L.load(hi / "audio" / "effects.json")
            mine = [c for c in rep["cues"] if c["source"] == "cue sheet"]
            self.assertEqual([(c["type"], c["t"]) for c in mine],
                             [("boom", round(seg[3]["start"], 3)), ("riser", round(seg[7]["start"] - 1.3, 3))])
            self.assertEqual((rep["from_cue_sheet"], rep["scale"]), (2, 0.8))
            self.assertNotEqual(sha(hi / "audio" / "sfx.wav"), before)
            self.assertNotIn("[sound@hi] up to date", out)                                # and the mix follows
            # mistakes stop the effects stage and keep the last track
            good = sha(hi / "audio" / "sfx.wav")
            for bad in ({"kind": "explosion", "at": {"line": 3}}, {"kind": "boom", "at": {"line": 999}}):
                sheet["synth_cues"] = [bad]; L.save(hi / "audio" / "cues.json", sheet)
                r = effects.build(hi, log=lambda *a: None)
                self.assertFalse(r.ok)
                self.assertEqual(sha(hi / "audio" / "sfx.wav"), good)
            # a track you made is never replaced without --force
            sheet["synth_cues"] = []; L.save(hi / "audio" / "cues.json", sheet)
            (hi / "audio" / "sfx.wav").write_bytes((hi / "audio" / "sfx.wav").read_bytes()[:-2] + b"\x07\x09")   # your edit
            yours = sha(hi / "audio" / "sfx.wav")
            r = effects.build(hi, log=lambda *a: None)
            self.assertTrue(any("was not made by effects.py" in e for e in r.errors))
            self.assertEqual(sha(hi / "audio" / "sfx.wav"), yours)
            self.assertTrue(effects.build(hi, force=True, log=lambda *a: None).ok)
            self.assertEqual(sha(hi / "audio" / "sfx.wav.bak"), yours)
            self.assertEqual(L.load(en / "audio" / "effects.json")["lang"], "en")             # English untouched

    def test_without_skia_or_scenes_the_mix_goes_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            self.assertTrue(dp(proj, lang="hi", until="narration")[0])
            with mock.patch.dict(sys.modules, {"skia": None}):
                r = effects.build(hi, log=lambda *a: None)
            self.assertTrue(r.ok); self.assertTrue(r.partial)
            self.assertFalse((hi / "audio" / "sfx.wav").exists())
            (hi / "06_film" / "acts.json").rename(hi / "06_film" / "acts.moved")
            (hi / "scene.py").rename(hi / "scene.moved")
            r = effects.build(hi, log=lambda *a: None)
            self.assertTrue(r.ok); self.assertTrue(r.partial)
            self.assertTrue(any("no scenes" in w for w in r.warnings))


if __name__ == "__main__":
    unittest.main()
