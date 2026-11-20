"""Tests for milestone 5.5: the finished film's quality control and delivery manifest (qc.py,
docpipe qc@<lang>).

Offline, on the tiny two-act fixture (English and Hindi). Needs skia-python, numpy and ffmpeg.
"""
import os
import pathlib
import shutil
import subprocess
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


def finished(base, captions=False, **kw):
    import finish
    import finish_fixture as F
    import subtitles
    proj = F.make(base, **kw)
    assert subtitles.build(proj, log=lambda *a: None).ok
    assert finish.render_acts(proj, SIZE, 2, **QUIET).ok
    assert finish.join(proj, **QUIET).ok
    if captions:
        assert finish.captions(proj, **QUIET).ok
    else:
        L.save(proj / "captions.json", {"enabled": False})
        assert finish.captions(proj, **QUIET).ok
    return proj


def replace_film(proj, vf=None, af=None, extra=()):
    """Re-encode the joined film through a filter, and record it as the join's (a fault made on purpose)."""
    import finish
    p = finish.fp(proj)
    tmp = p["film"].with_name("faulty.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(p["film"])]
    if vf:
        cmd += ["-vf", vf]
    if af:
        cmd += ["-af", af]
    subprocess.run(cmd + list(extra) + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp)], check=True)
    tmp.replace(p["film"])
    st = finish.load_state(p); st["join"]["sha256"] = finish.sha_file(p["film"]); L.save(p["state"], st)


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class QC(unittest.TestCase):
    def test_a_good_film_passes_and_is_delivered(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, captions=True)
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual([w for w in r.warnings if not w.startswith("fonts:")], [])   # the fades, the title card's silence and the pauses are not faults (a font fallback depends on the machine: test_composition)
            rep = L.load(proj / "out" / "qc.en.json")
            self.assertTrue(rep["complete"])
            names = {c["check"] for c in rep["checks"]}
            for want in ("film", "audio stream", "duration", "frames", "act order", "act 2 join", "sound during lines", "clipping",
                         "subtitle sync", "captions visible", "SRT cues", "VTT cues", "text fit", "caption clearance"):
                self.assertIn(want, names)
            m = L.load(proj / "out" / "delivery.en.json")
            self.assertTrue(m["complete"])
            kinds = {f["kind"] for f in m["files"]}
            self.assertTrue({"film", "film with captions", "subtitles", "soundtrack", "quality control"} <= kinds)
            film = next(f for f in m["files"] if f["kind"] == "film")
            import finish
            self.assertEqual(film["sha256"], finish.sha_file(proj / film["path"]))
            self.assertEqual(m["film"]["acts"], [1, 2]); self.assertEqual(m["film"]["captions"], "clean")
            self.assertIn("**Complete**", (proj / "out" / "qc.en.md").read_text())

    def test_black_frames_and_missing_narration_block_delivery(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp)
            segs = L.load(proj / "audio" / "timing.json")["segments"]
            s3 = segs[2]
            replace_film(proj, vf=f"drawbox=c=black:t=fill:enable='between(t,{s3['start']:.2f},{s3['start'] + 1.5:.2f})'",
                         af=f"volume=0:enable='between(t,{s3['start'] - 0.1:.2f},{s3['end'] + 0.1:.2f})'")
            r = qc.build(proj, **QUIET)
            self.assertFalse(r.ok)
            self.assertTrue(any(e.startswith("black frames") for e in r.errors), r.errors)
            self.assertTrue(any(e.startswith("sound during lines") and "3" in e for e in r.errors), r.errors)
            self.assertFalse(L.load(proj / "out" / "delivery.en.json")["complete"])
            self.assertIn("Not complete", (proj / "out" / "qc.en.md").read_text())
            # declared on purpose: the black is allowed; the missing line still blocks
            L.save(proj / "qc.json", {"allow_black": [[s3["start"] - 0.2, s3["start"] + 1.8]]})
            r = qc.build(proj, **QUIET)
            self.assertFalse(any(e.startswith("black frames") for e in r.errors), r.errors)
            self.assertTrue(any(e.startswith("sound during lines") for e in r.errors))

    def test_an_incomplete_render_and_stale_subtitles_are_found(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, code="hi", edition=True)
            subs = L.load(proj / "audio" / "subs.json")
            subs["cues"][-1]["t0"] += 4.0; subs["cues"][-1]["t1"] += 9.0
            L.save(proj / "audio" / "subs.json", subs)
            replace_film(proj, extra=("-t", "8"))
            r = qc.build(proj, **QUIET)
            for want in ("duration", "frames", "subtitle sync", "subtitle end"):
                self.assertTrue(any(e.startswith(want) for e in r.errors), (want, r.errors))
            self.assertFalse(L.load(proj / "out" / "delivery.hi.json")["complete"])
            (proj / "out" / "film.hi.mp4").unlink()
            r = qc.build(proj, **QUIET)
            self.assertTrue(any("missing" in e for e in r.errors))

    def test_a_silent_gap_where_nothing_pauses_is_a_warning(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, acts=1)
            segs = L.load(proj / "audio" / "timing.json")["segments"]
            mid = segs[1]["end"] - 1.4                              # inside line 2, which keeps some sound
            replace_film(proj, af=f"volume=0:enable='between(t,{mid:.2f},{mid + 1.3:.2f})'")
            r = qc.build(proj, **QUIET)
            self.assertTrue(any(w.startswith("silence") for w in r.warnings), (r.warnings, r.errors))

    def test_the_pipeline_checks_last_and_only_after_the_look(self):
        import contextlib
        import docpipe
        import io
        self.assertEqual(docpipe.EDITION_ORDER[-1], "qc")
        self.assertIn("qc", docpipe.AFTER_LOOK)
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                r = docpipe.stage_qc(proj)
            self.assertTrue(r.ok, r.errors)
            h = docpipe.single_hash(proj, L.paths(proj), ("qc:",))
            self.assertEqual(h, docpipe.single_hash(proj, L.paths(proj), ("qc:",)))   # resumable: nothing it reads changed
            L.save(proj / "qc.json", {"allow_black": [[1, 2]]})
            self.assertNotEqual(h, docpipe.single_hash(proj, L.paths(proj), ("qc:",)))


if __name__ == "__main__":
    unittest.main()
