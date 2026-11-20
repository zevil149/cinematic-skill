"""Tests for optional milestone 6.7: render robustness and fewer lossy generations.

  * an act render interrupted part-way resumes from the chunks it had finished (render.py
    --resume-dir), and a changed key, range, size or quality starts over; finished renders leave no
    chunks behind
  * finish.py renders a film of several acts at a near-lossless intermediate quality (the join
    encodes them again) and a one-act film at the delivery quality (copied as it is)

Offline, on the tiny fixture. Needs skia-python, numpy and ffmpeg.
"""
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
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
    HAVE = shutil.which("ffmpeg") is not None and os.name == "posix"
except ImportError:                          # pragma: no cover
    HAVE = False

QUIET = dict(log=lambda *a: None)


def render_cmd(proj, out, key, chunk=20):
    return [sys.executable, str(SCRIPTS / "render.py"), "--project", str(proj), "--t0", "0", "--t1", "4.5", "--size", "160x90",
            "--workers", "1", "--crf", "18", "--out", str(out), "--resume-dir", "out/parts", "--resume-key", key, "--chunk", str(chunk)]


def done(parts):
    """Finished chunks (a chunk being encoded is a .part.mp4 until its encoder is done)."""
    return sorted(p.name for p in parts.glob("c_*.mp4") if not p.name.endswith(".part.mp4"))


@unittest.skipUnless(HAVE, "needs skia-python, numpy, ffmpeg and POSIX process groups")
class Resume(unittest.TestCase):
    def test_an_interrupted_render_resumes_from_its_finished_chunks(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp, acts=1)
            parts = proj / "out" / "parts"
            out = proj / "out" / "act.mp4"
            env = dict(os.environ, CINEMATIC_ACT="1")
            for attempt in range(3):                                                         # stop it once a chunk is done
                proc = subprocess.Popen(render_cmd(proj, out, "k1"), env=env, start_new_session=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                t0 = time.time()
                while time.time() - t0 < 120 and proc.poll() is None and not done(parts):
                    time.sleep(0.02)
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    break
                proc.wait(); shutil.rmtree(parts, ignore_errors=True); out.unlink(missing_ok=True)
            else:
                self.skipTest("the render finished before it could be interrupted")
            self.assertFalse(out.exists())
            made = done(parts)
            self.assertTrue(made)
            res = subprocess.run(render_cmd(proj, out, "k1"), env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr[-800:])
            n = int(re.search(r"(\d+) of (\d+) chunk\(s\) already made", res.stdout).group(1))
            self.assertGreaterEqual(n, len(made))                                            # nothing made twice
            self.assertEqual(finish.probe(out)["frames"], 135)                                 # 4.5 s at 30 fps, whole
            self.assertFalse(parts.exists())                                                   # written: chunks removed
            # a new key (another scene, size, quality...) starts over
            parts.mkdir(parents=True)
            (parts / "resume.json").write_text('{"key": "old"}'); (parts / "c_0000000_0000020.mp4").write_bytes(b"stale")
            res = subprocess.run(render_cmd(proj, out, "k2"), env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr[-800:])
            self.assertIn("0 of 7 chunk(s) already made", res.stdout)
            self.assertEqual(finish.probe(out)["frames"], 135)

    def test_finish_keeps_no_chunks_and_picks_the_act_quality(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            two = F.make(pathlib.Path(tmp) / "a")
            self.assertTrue(finish.render_acts(two, "160x90", 2, **QUIET).ok)
            st = L.load(two / "out" / "finish.json")
            self.assertEqual({r["crf"] for r in st["acts"].values()}, {finish.INTERMEDIATE_CRF})   # the join encodes them again
            self.assertEqual(list((two / "out" / "acts").glob(".act_*.parts")), [])
            self.assertTrue(finish.join(two, **QUIET).ok)
            one = F.make(pathlib.Path(tmp) / "b", acts=1)
            self.assertTrue(finish.render_acts(one, "160x90", 2, **QUIET).ok)
            self.assertEqual(L.load(one / "out" / "finish.json")["acts"]["1"]["crf"], finish.CRF)   # copied as it is
            self.assertTrue(finish.join(one, **QUIET).ok)
            # resumable acts: a stopped render leaves its chunks, and the next one uses them
            import qc
            parts = one / "out" / "acts" / ".act_01.parts"
            parts.mkdir()
            r = qc.build(one, **QUIET)
            self.assertTrue(any(w.startswith("interrupted renders: .act_01.parts") for w in r.warnings), r.warnings)


if __name__ == "__main__":
    unittest.main()
