"""Tests for milestone 4.2: the look review (review.py, docpipe review@<lang>, gate "look").

Offline (CINEMATIC_OFFLINE=1): mock voices, designed cards (no archive images). Rendering needs
skia-python, numpy, Pillow and ffmpeg (the film job has them). The flag rules need only numpy.
"""
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import review  # noqa: E402

try:
    import numpy as np
    HAVE_NP = True
except ImportError:                          # pragma: no cover
    HAVE_NP = False
try:
    import skia  # noqa: F401
    from test_pipeline_audio import HAVE as HAVE_AUDIO, through_gates
    HAVE_RENDER = HAVE_NP and HAVE_AUDIO
except ImportError:                          # pragma: no cover
    HAVE_RENDER = False


def dp(proj, **kw):
    out = io.StringIO()
    docpipe.OPTS.update(offline=True)
    try:
        with contextlib.redirect_stdout(out):
            ok = docpipe.run(proj, **kw)
    finally:
        docpipe.OPTS.update(offline=False)
    return ok, out.getvalue()


def status(proj):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        docpipe.status(proj)
    return out.getvalue()


@unittest.skipUnless(HAVE_NP, "needs numpy")
class Flags(unittest.TestCase):
    def test_flags_point_at_frames_worth_a_look(self):
        rng = np.random.default_rng(1)
        blank = np.full((90, 160, 3), 120, np.uint8)
        dark = (rng.random((90, 160, 3)) * 20).astype(np.uint8)             # mean about 10
        busy = (rng.random((90, 160, 3)) * 255).astype(np.uint8)
        flat = (np.full((90, 160, 3), 100) + rng.random((90, 160, 3)) * 28).astype(np.uint8)   # std about 5
        self.assertEqual(review.flags_of(blank)[0], ["blank"])
        self.assertIn("very dark", review.flags_of(np.zeros((90, 160, 3), np.uint8))[0])
        self.assertIn("very dark", review.flags_of(dark)[0])
        self.assertEqual(review.flags_of(busy)[0], [])
        self.assertEqual(review.flags_of(flat)[0], ["near-uniform"])


@unittest.skipUnless(HAVE_RENDER, "needs skia-python, numpy, Pillow and ffmpeg")
class LookReview(unittest.TestCase):
    def test_per_edition_review_and_look_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="all")
            self.assertFalse(ok)                                                       # waiting for two looks
            for code in ("en", "hi"):
                self.assertIn(f"[review@{code}] passes its checks", out)
                self.assertIn(f"approve --project {proj} look --lang {code}", out)
            self.assertLess(out.index("[subtitles@hi]"), out.index("[review@en]"))     # the look never holds up audio
            self.assertTrue((hi / "out" / "subtitles.hi.srt").exists())
            for code, ed in (("en", en), ("hi", hi)):
                rv = L.load(proj / "07_review" / code / "review.json")
                self.assertEqual((rv["lang"], rv["built_by"]), (code, "review.py"))
                a = rv["acts"][0]
                lines = L.load(ed / "06_film" / "acts.json")["acts"][0]["lines"]
                self.assertEqual([x["line"] for x in a["probes"] if x["line"]], lines)  # a still per line
                self.assertEqual(a["probes"][0]["name"], "probe_open"); self.assertEqual(a["probes"][-1]["name"], "probe_close")
                self.assertGreaterEqual(len(a["strips"]), 1)
                d = proj / "07_review" / code / "act_01"
                for f in ("sheet.jpg", "review.md", "L0001.png", "strip_01.jpg"):
                    self.assertTrue((d / f).exists(), f)
                md = (d / "review.md").read_text(encoding="utf-8")
                self.assertIn("- [ ] The hero of every line is lit", md)
                self.assertIn("do not pass or fail", md)
            hi_md = (proj / "07_review" / "hi" / "act_01" / "review.md").read_text(encoding="utf-8")
            self.assertTrue(any("ऀ" <= ch <= "ॿ" for ch in hi_md))            # the Hindi lines, in Hindi
            self.assertRegex(status(proj), r"review@en\s+awaiting approval\s+\[gate\]")
            # approvals are per edition
            with contextlib.redirect_stdout(io.StringIO()):
                docpipe.approve(proj, "look", "en")
            st = status(proj)
            self.assertRegex(st, r"review@en\s+done"); self.assertRegex(st, r"review@hi\s+awaiting approval")
            ok, out = dp(proj, lang="all")
            self.assertIn("[review@en] up to date", out)
            # a scene edit lapses that edition's look approval, and only that one
            act = en / "06_film" / "act_01" / "scene.py"
            act.write_text(act.read_text() + "\n# a change to the English act\n")
            ok, out = dp(proj, lang="all")
            self.assertIn("[review@en] passes its checks", out)
            self.assertNotIn("[review@hi] up to date", out)                            # still waiting for its own look
            self.assertRegex(status(proj), r"review@en\s+awaiting approval")
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)

    def test_resume_and_your_notes_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            self.assertTrue(dp(proj, lang="hi", until="subtitles")[0])
            r = review.build(hi, log=lambda *a: None)
            self.assertTrue(r.ok, r.errors)
            d = proj / "07_review" / "hi" / "act_01"
            stamp = (d / "L0001.png").stat().st_mtime_ns
            r = review.build(hi, log=lambda *a: None)
            self.assertTrue(any("up to date" in n for n in r.notes))
            self.assertEqual((d / "L0001.png").stat().st_mtime_ns, stamp)
            md = d / "review.md"
            md.write_text(md.read_text(encoding="utf-8") + "\nThe second card is too low.\n", encoding="utf-8")
            notes = md.read_text(encoding="utf-8")
            act = hi / "06_film" / "act_01" / "scene.py"
            act.write_text(act.read_text() + "\n# moved a card\n")
            r = review.build(hi, log=lambda *a: None)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(md.read_text(encoding="utf-8"), notes)                    # your notes stay
            self.assertTrue((d / "review.latest.md").exists())
            self.assertTrue(any("your notes" in n for n in r.notes))

    def test_a_review_needs_the_narration_and_its_own_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            self.assertTrue(dp(proj, lang="all", until="scenegen")[0])
            r = review.build(hi, log=lambda *a: None)
            self.assertTrue(any("narrate.py" in e for e in r.errors))
            self.assertTrue(dp(proj, lang="all", until="narration")[0])
            t = L.load(hi / "audio" / "timing.json"); t["lang"] = "en"; L.save(hi / "audio" / "timing.json", t)
            self.assertTrue(any("is the en voice" in e for e in review.build(hi, log=lambda *a: None).errors))
            self.assertFalse((proj / "07_review" / "hi" / "review.json").exists())


if __name__ == "__main__":
    unittest.main()
