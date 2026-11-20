"""Tests for milestone 5.2: rendering every act at its approved timing (finish.py render,
docpipe render@<lang>, after the look gate).

Offline. A tiny two-act fixture (tests/finish_fixture.py) renders in seconds at a small size; one
test drives a whole production through docpipe. Needs skia-python, numpy, Pillow and ffmpeg.
"""
import contextlib
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402

try:
    import numpy  # noqa: F401
    import skia  # noqa: F401
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SIZE = "160x90"
QUIET = dict(log=lambda *a: None)


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Acts(unittest.TestCase):
    def test_each_act_is_rendered_checked_and_resumed(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertTrue(r.ok, r.errors)
            st = L.load(proj / "out" / "finish.json")
            total = L.load(proj / "audio" / "timing.json")["total_duration"]
            acts = L.load(proj / "06_film" / "acts.json")["acts"]
            a1, a2 = st["acts"]["1"], st["acts"]["2"]
            self.assertEqual((a1["from"], a1["t0"]), (0.0, 0.0))
            self.assertAlmostEqual(a1["to"], acts[1]["t0"] + finish.OVERLAP, places=2)           # a quarter second past its edge
            self.assertAlmostEqual(a2["from"], acts[1]["t0"] - finish.OVERLAP, places=2)
            self.assertEqual(a2["to"], total)
            for rec in (a1, a2):
                info = finish.probe(proj / rec["file"])
                self.assertEqual((info["w"], info["h"], info["vcodec"]), (160, 90, "h264"))
                self.assertEqual(info["frames"], round(rec["to"] * 30) - round(rec["from"] * 30))
                self.assertEqual(info["audio"], "aac")                                         # the act's slice of the mix
            self.assertEqual(st["order"], [1, 2])
            # resume: nothing changed, nothing rendered; one act changed, only it is rendered again
            f1, f2 = proj / a1["file"], proj / a2["file"]
            m1, m2 = f1.stat().st_mtime_ns, f2.stat().st_mtime_ns
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertEqual(sum("up to date" in n for n in r.notes), 2)
            self.assertEqual((f1.stat().st_mtime_ns, f2.stat().st_mtime_ns), (m1, m2))
            sc = proj / "06_film" / "act_02" / "scene.py"
            sc.write_text(sc.read_text().replace("ACT TWO", "ACT 2"))
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(f1.stat().st_mtime_ns, m1); self.assertNotEqual(f2.stat().st_mtime_ns, m2)

    def test_a_failed_act_is_reported_and_nothing_incomplete_is_kept(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            sc = proj / "06_film" / "act_02" / "scene.py"
            sc.write_text(sc.read_text().replace("film.cam(0.0", "raise RuntimeError('a broken scene')\n    film.cam(0.0"))
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertFalse(r.ok)
            self.assertTrue(any(e.startswith("act 2: the render failed") for e in r.errors), r.errors)
            self.assertTrue(any("not rendered: the film is not complete" in e for e in r.errors))
            self.assertTrue((proj / "out" / "acts" / "act_01.mp4").exists())                  # the other act went on
            self.assertFalse((proj / "out" / "acts" / "act_02.mp4").exists())
            self.assertFalse(list((proj / "out" / "acts").glob("*.rendering.mp4")))
            self.assertNotIn("2", L.load(proj / "out" / "finish.json")["acts"])

    def test_your_render_is_kept_and_single_act_and_hindi(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(pathlib.Path(tmp) / "a")
            self.assertTrue(finish.render_acts(proj, SIZE, 2, **QUIET).ok)
            f = proj / "out" / "acts" / "act_01.mp4"
            with open(f, "ab") as fh:
                fh.write(b"\0")
            mine = f.read_bytes()
            sc = proj / "06_film" / "act_01" / "scene.py"
            sc.write_text(sc.read_text().replace("ACT ONE", "ACT 1"))
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertTrue(any("was not rendered by finish.py" in e for e in r.errors))
            self.assertEqual(f.read_bytes(), mine)
            self.assertTrue(finish.render_acts(proj, SIZE, 2, force=True, **QUIET).ok)
            self.assertEqual((f.with_name("act_01.mp4.bak")).read_bytes(), mine)
            one = F.make(pathlib.Path(tmp) / "b", acts=1)
            self.assertTrue(finish.render_acts(one, SIZE, 2, **QUIET).ok)
            rec = L.load(one / "out" / "finish.json")["acts"]
            self.assertEqual(list(rec), ["1"])
            self.assertEqual((rec["1"]["from"], rec["1"]["to"]), (0.0, L.load(one / "audio" / "timing.json")["total_duration"]))
            hi = F.make(pathlib.Path(tmp) / "c", code="hi", edition=True)
            self.assertTrue(finish.render_acts(hi, SIZE, 2, **QUIET).ok)
            self.assertEqual(L.load(hi / "out" / "finish.json")["lang"], "hi")
            t = L.load(hi / "audio" / "timing.json"); t["lang"] = "en"; L.save(hi / "audio" / "timing.json", t)
            self.assertTrue(any("is the en voice" in e for e in finish.render_acts(hi, SIZE, 2, **QUIET).errors))


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Pipeline(unittest.TestCase):
    def test_render_waits_for_each_editions_look(self):
        import docpipe
        from test_pipeline_audio import through_gates

        def dp(proj, **kw):
            out = io.StringIO()
            docpipe.OPTS.update(offline=True, size="96x54", workers=2)
            try:
                with contextlib.redirect_stdout(out):
                    ok = docpipe.run(proj, **kw)
            finally:
                docpipe.OPTS.update(offline=False, size="1920x1080", workers=0)
            return ok, out.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="all")
            self.assertFalse(ok)
            for code in ("en", "hi"):
                self.assertIn(f"[render@{code}] waits for the look of the {code} edition", out)
            self.assertFalse((en / "out" / "acts").exists())                                   # nothing rendered before the look
            with contextlib.redirect_stdout(io.StringIO()):
                docpipe.approve(proj, "look", "en")
            ok, out = dp(proj, lang="all")
            self.assertIn("[render@en]", out); self.assertIn("[render@hi] waits for the look", out)
            self.assertTrue((en / "out" / "acts" / "act_01.mp4").exists())
            self.assertFalse((hi / "out" / "acts").exists())
            ok, out = dp(proj, lang="en")
            self.assertIn("[render@en] up to date", out)


if __name__ == "__main__":
    unittest.main()
