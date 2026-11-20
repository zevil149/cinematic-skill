"""Tests for milestone 5.3: joining the acts into the film (finish.py join, docpipe join@<lang>).

Offline, on the tiny two-act fixture. Needs skia-python, numpy and ffmpeg.
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
    import numpy as np
    import skia  # noqa: F401
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SIZE = "160x90"
QUIET = dict(log=lambda *a: None)


def frame_mean(video, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "gray", "pipe:1"], capture_output=True, check=True)
    return float(np.frombuffer(r.stdout, np.uint8).mean())


def audio_rms(video, t0, t1):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(video), "-vn", "-f", "f32le",
                        "-ac", "1", "-ar", "8000", "pipe:1"], capture_output=True, check=True)
    a = np.frombuffer(r.stdout, np.float32)
    return float(np.sqrt((a ** 2).mean())) if len(a) else 0.0


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Join(unittest.TestCase):
    def test_two_acts_join_in_order_on_the_timeline(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            self.assertTrue(finish.render_acts(proj, SIZE, 2, **QUIET).ok)
            r = finish.join(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            total = L.load(proj / "audio" / "timing.json")["total_duration"]
            film = proj / "out" / "film.en.mp4"
            info = finish.probe(film)
            self.assertAlmostEqual(info["duration"], total, delta=0.1)                          # the film is the timeline
            self.assertEqual(info["frames"], round(total * 30))
            self.assertEqual((info["w"], info["h"], info["audio"]), (160, 90, "aac"))
            j = L.load(proj / "out" / "finish.json")["join"]
            card = L.load(proj / "06_film" / "acts.json")["acts"][1]["t0"]
            self.assertEqual(j["order"], [1, 2])
            self.assertEqual(len(j["crossfades"]), 1)
            self.assertAlmostEqual(j["crossfades"][0]["at"] + j["crossfades"][0]["duration"] / 2, card, places=2)  # centred on the act change
            # the sound is the one continuous mix: no gap at the join
            self.assertGreater(audio_rms(film, card - 0.4, card + 0.4), 0.01)                      # sound through the act change
            self.assertAlmostEqual(audio_rms(film, card - 0.4, card + 0.4), audio_rms(proj / "audio" / "mix.m4a", card - 0.4, card + 0.4), delta=0.02)
            # resume
            stamp = film.stat().st_mtime_ns
            r = finish.join(proj, **QUIET)
            self.assertTrue(any("up to date" in n for n in r.notes)); self.assertEqual(film.stat().st_mtime_ns, stamp)
            # an act rendered from older inputs is not joined
            sc = proj / "06_film" / "act_02" / "scene.py"
            sc.write_text(sc.read_text().replace("ACT TWO", "ACT 2"))
            r = finish.join(proj, **QUIET)
            self.assertTrue(any("older scenes" in e for e in r.errors)); self.assertEqual(film.stat().st_mtime_ns, stamp)
            self.assertTrue(finish.render_acts(proj, SIZE, 2, **QUIET).ok)
            self.assertTrue(finish.join(proj, **QUIET).ok)
            self.assertNotEqual(film.stat().st_mtime_ns, stamp)

    def test_one_act_is_copied_and_mismatched_acts_are_normalised(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            one = F.make(pathlib.Path(tmp) / "a", acts=1)
            self.assertTrue(finish.render_acts(one, SIZE, 2, **QUIET).ok)
            r = finish.join(one, **QUIET)
            self.assertTrue(r.ok, r.errors)
            j = L.load(one / "out" / "finish.json")["join"]
            self.assertEqual((j["order"], j["crossfades"]), ([1], []))
            act = finish.probe(one / "out" / "acts" / "act_01.mp4")
            self.assertEqual(finish.probe(one / "out" / "film.en.mp4")["frames"], act["frames"])     # the video stream, copied
            # an act re-encoded at another size by hand (and recorded as its render) is normalised, with a warning
            two = F.make(pathlib.Path(tmp) / "b")
            self.assertTrue(finish.render_acts(two, SIZE, 2, **QUIET).ok)
            a2 = two / "out" / "acts" / "act_02.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a2), "-vf", "scale=192:108", "-c:a", "copy",
                            str(a2.with_name("x.mp4"))], check=True)
            a2.with_name("x.mp4").replace(a2)
            st = L.load(two / "out" / "finish.json"); st["acts"]["2"]["sha256"] = finish.sha_file(a2); L.save(two / "out" / "finish.json", st)
            r = finish.join(two, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertTrue(any("normalised" in w for w in r.warnings))
            self.assertEqual(finish.probe(two / "out" / "film.en.mp4")["w"], 160)

    def test_missing_acts_mix_and_your_film(self):
        import finish
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            self.assertTrue(any("not rendered" in e for e in finish.join(proj, **QUIET).errors))
            self.assertTrue(finish.render_acts(proj, SIZE, 2, **QUIET).ok)
            (proj / "out" / "acts" / "act_02.mp4").rename(proj / "out" / "acts" / "gone.mp4")
            r = finish.join(proj, **QUIET)
            self.assertTrue(any("act 2 is not rendered" in e for e in r.errors))
            self.assertFalse((proj / "out" / "film.en.mp4").exists())
            (proj / "out" / "acts" / "gone.mp4").rename(proj / "out" / "acts" / "act_02.mp4")
            mix = proj / "audio" / "mix.m4a"; mix.rename(mix.with_name("mix.away"))
            self.assertTrue(any("no audio/mix.m4a" in e for e in finish.join(proj, **QUIET).errors))
            mix.with_name("mix.away").rename(mix)
            self.assertTrue(finish.join(proj, **QUIET).ok)
            film = proj / "out" / "film.en.mp4"
            with open(film, "ab") as fh:
                fh.write(b"\0")
            mine = film.read_bytes()
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=14", "-c:a", "aac",
                            str(mix)], check=True)                                           # a new mix: the film would be joined again
            r = finish.join(proj, **QUIET)
            self.assertTrue(any("was not joined by finish.py" in e for e in r.errors)); self.assertEqual(film.read_bytes(), mine)
            self.assertTrue(finish.join(proj, force=True, **QUIET).ok)
            self.assertEqual(film.with_name("film.en.mp4.bak").read_bytes(), mine)


if __name__ == "__main__":
    unittest.main()
