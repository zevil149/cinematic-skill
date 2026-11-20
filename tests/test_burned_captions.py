"""Tests for milestone 5.4: captions burned into the finished film (finish.py captions,
docpipe captions@<lang>).

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
    import numpy as np
    import skia  # noqa: F401
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SIZE = "320x180"
QUIET = dict(log=lambda *a: None)


def frame(video, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True)
    info = __import__("finish").probe(video)
    return np.frombuffer(r.stdout, np.uint8).reshape(info["h"], info["w"], 3).astype(int)


def band_diff(a, b):
    """How different the caption band (the bottom quarter) of two frames is."""
    h = a.shape[0]
    return float(np.abs(a[int(h * 0.74):] - b[int(h * 0.74):]).mean())


def finished(base, **kw):
    import finish
    import finish_fixture as F
    proj = F.make(base, **kw)
    assert finish.render_acts(proj, SIZE, 2, **QUIET).ok
    assert finish.join(proj, **QUIET).ok
    return proj


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Burned(unittest.TestCase):
    def test_captions_appear_with_their_lines_and_never_on_the_card_silence(self):
        import finish
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp)
            subs_before = {f: f.read_bytes() for f in (proj / "out").glob("subtitles.*")}
            r = finish.captions(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            film, cap = proj / "out" / "film.en.mp4", proj / "out" / "film.en.captions.mp4"
            fi, ci = finish.probe(film), finish.probe(cap)
            self.assertEqual((ci["frames"], ci["w"], ci["h"]), (fi["frames"], fi["w"], fi["h"]))
            self.assertEqual(ci["audio"], "aac")
            segs = L.load(proj / "audio" / "timing.json")["segments"]
            for s in segs:                                                                # each line: its caption is on screen
                t = (s["start"] + s["end"]) / 2
                self.assertGreater(band_diff(frame(cap, t), frame(film, t)), 5.0, s["id"])        # re-encoding alone is ~1.5
            card = L.load(proj / "06_film" / "acts.json")["acts"][1]
            mid = (card["t0"] + card["title_card"]["t1"]) / 2
            self.assertLess(band_diff(frame(cap, mid), frame(film, mid)), 3.0)              # the title card's silence is clean
            from captions import Captions
            self.assertIsNone(Captions("clean", 320, 180, L.load(proj / "audio" / "timing.json")).active(mid))
            self.assertEqual(L.load(proj / "out" / "finish.json")["captions"]["style"], "clean")
            self.assertEqual({f: f.read_bytes() for f in (proj / "out").glob("subtitles.*")}, subs_before)
            # resume, then a new style makes a new file
            stamp = cap.stat().st_mtime_ns
            self.assertTrue(any("up to date" in n for n in finish.captions(proj, **QUIET).notes))
            self.assertEqual(cap.stat().st_mtime_ns, stamp)
            L.save(proj / "captions.json", {"style": "highlighter"})
            self.assertTrue(finish.captions(proj, **QUIET).ok)
            self.assertEqual(L.load(proj / "out" / "finish.json")["captions"]["style"], "highlighter")
            L.save(proj / "captions.json", {"style": "neon"})
            self.assertTrue(any("not one of" in e for e in finish.captions(proj, **QUIET).errors))

    def test_hindi_captions_are_shaped_and_your_film_is_kept(self):
        import finish
        import textshape
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, code="hi", edition=True)
            real = textshape.shape
            with mock.patch.object(textshape, "shape", side_effect=real):
                pass                                                                      # burned in a subprocess; checked by pixels below
            self.assertTrue(finish.captions(proj, **QUIET).ok)
            cap, film = proj / "out" / "film.hi.captions.mp4", proj / "out" / "film.hi.mp4"
            s = L.load(proj / "audio" / "timing.json")["segments"][0]
            t = (s["start"] + s["end"]) / 2
            self.assertGreater(band_diff(frame(cap, t), frame(film, t)), 5.0)
            from captions import Captions
            layer = Captions("clean", 320, 180, L.load(proj / "audio" / "timing.json")).layer(t)
            got = frame(cap, t)[135:]
            want = layer[135:, :, 3] > 0                                                   # where the shaped Hindi caption draws
            self.assertGreater(float(np.abs(got - frame(film, t)[135:]).sum(axis=2)[want].mean()), 20)
            with open(cap, "ab") as fh:
                fh.write(b"\0")
            mine = cap.read_bytes()
            L.save(proj / "captions.json", {"style": "redbar"})
            r = finish.captions(proj, **QUIET)
            self.assertTrue(any("was not made by finish.py" in e for e in r.errors)); self.assertEqual(cap.read_bytes(), mine)
            self.assertTrue(finish.captions(proj, force=True, **QUIET).ok)
            self.assertEqual(cap.with_name("film.hi.captions.mp4.bak").read_bytes(), mine)
            L.save(proj / "captions.json", {"enabled": False})
            r = finish.captions(proj, **QUIET)
            self.assertTrue(r.ok); self.assertTrue(any("off" in n for n in r.notes))

    def test_a_line_before_an_act_change_does_not_linger_into_the_card(self):
        from captions import chunks_for
        import finish_fixture as F
        t = F.timing("en", 2)
        ends = {s["id"]: s["end"] for s in t["segments"]}
        ch = chunks_for(t, "clean")
        last2 = [c for c in ch if c["words"][-1][1] < ends[2] and c["words"][0][1] >= t["segments"][1]["start"]][-1]
        self.assertLessEqual(last2["t1"], ends[2] + 1e-6)                                   # line 2 ends as act 2's card begins
        last4 = ch[-1]
        self.assertAlmostEqual(last4["t1"], ends[4] + 0.25)                                 # elsewhere: as before
        legacy = {"total_duration": 9.0, "segments": [{"id": 1, "caption": "A short line.", "vo": "x", "start": 1.0, "end": 3.0},
                                                       {"id": 2, "caption": "Another one.", "vo": "y", "start": 5.0, "end": 7.0}]}
        self.assertAlmostEqual(chunks_for(legacy, "clean")[0]["t1"], 3.25)


if __name__ == "__main__":
    unittest.main()
