"""Tests for the engine's visual additions (phase 2, stage 2.3): moves inside a print, archive
footage, parallax planes and camera-move helpers. Renders real frames at 320x180.

Needs skia-python, numpy, pillow and ffmpeg (the CI film job has them); skipped otherwise.
"""
import json
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

try:
    import numpy as np
    import skia  # noqa: F401
    from PIL import Image
    import engine as E
    HAVE = shutil.which("ffmpeg") is not None
except Exception:                       # pragma: no cover
    HAVE = False


def make_proj(tmp):
    proj = pathlib.Path(tmp) / "p"
    (proj / "audio").mkdir(parents=True)
    (proj / "assets" / "prep" / "photos").mkdir(parents=True)
    (proj / "audio" / "timing.json").write_text(json.dumps({"total_duration": 8, "segments": [
        {"id": 1, "start": 0.5, "end": 3.0, "duration": 2.5, "vo": "the first flight lasted twelve seconds"}]}))
    rng = np.random.default_rng(3)
    a = (rng.random((300, 400, 3)) * 255).astype(np.uint8)
    a[:, :200] //= 3                                   # left half dark, so a pan changes what is seen
    Image.fromarray(a).save(proj / "assets" / "prep" / "photos" / "P1.jpg")
    (proj / "assets" / "prep" / "photos" / "meta.json").write_text(json.dumps({"P1": {"w": 400, "h": 300, "kind": "photo"}}))
    subprocess.run([sys.executable, str(SCRIPTS / "prep_assets.py"), "--project", str(proj)], capture_output=True)
    (proj / "assets" / "prep" / "photos" / "meta.json").write_text(json.dumps({"P1": {"w": 400, "h": 300, "kind": "photo"}}))
    return proj


def render(proj, items, t_list, cam=(0, 0, 0.9), fps=30):
    doc = E.Doc(proj)
    film = E.Film(doc.duration, fps=fps, look="charcoal")
    film.fade_in = film.fade_out = 0
    film.look["grain"] = 0
    for it in items:
        film.add(it)
    film.cam(0, cam[0], cam[1], cam[2]); film.cam(doc.duration, cam[0], cam[1], cam[2])
    r = E.Renderer(film, 320, 180, doc)
    return [r.frame(round(t * fps)).astype(np.int16) for t in t_list], r


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and ffmpeg")
class KenBurns(unittest.TestCase):
    def test_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            still, _ = render(proj, [E.Print("P1", 0, 0, 3000, t_in=0, pin=False)], [1, 6])
            # the photo is dark on its left half: brightness says which part of it is in view
            self.assertLess(abs(still[0].mean() - still[1].mean()), 1.0)        # a plain print holds still
            pan, _ = render(proj, [E.Print("P1", 0, 0, 3000, t_in=0, pin=False, move=E.ken_burns("pan_right", 0, 7, amount=0.5))], [1, 6])
            self.assertGreater(pan[1].mean() - pan[0].mean(), 5)               # panned from the dark half to the bright one
            static = {"t0": 0, "t1": 7, "from": (1.0, 0.5, 0.5), "to": (1.0, 0.5, 0.5)}
            same, _ = render(proj, [E.Print("P1", 0, 0, 3000, t_in=0, pin=False, move=static)], [1])
            self.assertLess(abs(same[0].mean() - still[0].mean()), 0.5)        # a zero move draws what a plain print draws

    def test_presets(self):
        for k in ("push", "pull", "pan_left", "pan_right", "pan_up", "pan_down", "drift"):
            m = E.ken_burns(k, 0, 4)
            z0, _, _ = E.move_state(m, 0, 0, None)
            z1, _, _ = E.move_state(m, 4, 0, None)
            self.assertGreaterEqual(min(z0, z1), 1.0)                          # never zooms out past the frame
        with self.assertRaises(ValueError):
            E.ken_burns("spin")
        self.assertEqual(E.move_state(E.ken_burns("push", None, None), 0, 2.0, 5.0)[0], 1.0)   # defaults to t_in


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and ffmpeg")
class Footage(unittest.TestCase):
    def test_prep_and_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            (proj / "assets" / "footage").mkdir(parents=True)
            clip = proj / "assets" / "footage" / "F1.webm"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
                            "-c:v", "libvpx", "-b:v", "300k", str(clip)], check=True)
            (proj / "footage.json").write_text(json.dumps({"grade": "bw", "footage": [
                {"id": "F1", "file": "F1.webm", "clip_in": 0.5, "clip_dur": 2.0},
                {"id": "F2", "file": "missing.webm"}]}))
            r = subprocess.run([sys.executable, str(SCRIPTS / "prep_footage.py"), "--project", str(proj)], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)                               # the missing clip is reported
            self.assertIn("F2", r.stdout)
            meta = json.loads((proj / "assets" / "prep" / "footage" / "meta.json").read_text())
            self.assertEqual(meta["F1"]["frames"], 24)                         # 2 s at 12 fps
            doc = E.Doc(proj)
            fm = doc.fmeta["F1"]
            ft = E.Footage("F1", 0, 0, 3000, t_in=0, pin=False, aspect=fm["w"] / fm["h"])
            frames, rend = render(proj, [ft], [0.2, 1.1])
            self.assertGreater(np.abs(frames[0] - frames[1]).mean(), 2)       # it plays
            self.assertEqual(ft.frame_index(rend.res, 1.0), 12)
            self.assertEqual(ft.frame_index(rend.res, 2.5), 6)                 # loops
            hold = E.Footage("F1", 0, 0, 3000, t_in=0, loop=False, aspect=1.33)
            self.assertEqual(hold.frame_index(rend.res, 9.0), 23)              # or holds its last frame
            for i in range(60):
                rend.res.footage_frame("F1", i % 24)
            self.assertLessEqual(len(rend.res.frames), 24)                     # bounded memory


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and ffmpeg")
class ParallaxAndCamera(unittest.TestCase):
    def test_parallax(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            base, _ = render(proj, [E.Print("P1", 0, 0, 1500, t_in=0, pin=False)], [1], cam=(400, 0, 0.6))
            flat, r = render(proj, [E.Parallax(E.Print("P1", 0, 0, 1500, t_in=0, pin=False), depth=1.0)], [1], cam=(400, 0, 0.6))
            self.assertEqual(np.abs(base[0] - flat[0]).max(), 0)                # depth 1 is the board itself
            deep, r = render(proj, [E.Parallax(E.Print("P1", 0, 0, 1500, t_in=0, pin=False), depth=0.5)], [1], cam=(400, 0, 0.6))
            self.assertGreater(np.abs(base[0] - deep[0]).mean(), 2)
            pr = E.Parallax(E.Print("P1", 0, 0, 1500, t_in=0), depth=0.5)
            r.res.cam = (400.0, 100.0, 0.6, 0.0)
            self.assertEqual(pr.offset(r.res), (200.0, 50.0))
            b0 = pr.item.bounds(r.res); b1 = pr.bounds(r.res)
            self.assertAlmostEqual(b1.left() - b0.left(), 200.0)
            self.assertEqual(pr.cues(), pr.item.cues())

    def test_camera_helpers(self):
        f = E.Film(10)
        f.push_in(1, 2, 100, 200, 0.5, 1.0)
        f.pan(3, 4, (0, 0), (5000, 0), 0.6)
        f.whip(5, (5000, 0), (-20000, 0), 0.4)
        f.reveal(6, 8, 0, 0)
        f.hold(8.5, 9.5, 10, 10)
        self.assertEqual(len(f.cam_keys), 10)
        self.assertEqual(len(f.focus_keys), 10)
        self.assertAlmostEqual(f.camera(2)[2], 1.0, places=1)
        self.assertTrue(any(c["type"] == "whoosh" and 4 < c["t"] < 5.5 for c in f.all_cues()))


def make_clip(proj, name, seconds=3, src="testsrc"):
    (proj / "assets" / "footage").mkdir(parents=True, exist_ok=True)
    clip = proj / "assets" / "footage" / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=duration={seconds}:size=320x240:rate=24",
                    "-c:v", "libvpx", "-b:v", "300k", str(clip)], check=True)
    return clip


def prep(proj):
    return subprocess.run([sys.executable, str(SCRIPTS / "prep_footage.py"), "--project", str(proj)], capture_output=True, text=True)


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and ffmpeg")
class FootageFixes(unittest.TestCase):
    def test_start_point_past_the_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            make_clip(proj, "F1.webm", seconds=3)
            (proj / "footage.json").write_text(json.dumps({"footage": [{"id": "F1", "file": "F1.webm", "clip_in": 10.0}]}))
            r = prep(proj)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("clip_in 10.0s is past the end of the clip", r.stdout)
            self.assertFalse((proj / "assets" / "prep" / "footage" / "F1").exists())
            self.assertEqual(json.loads((proj / "assets" / "prep" / "footage" / "meta.json").read_text()), {})

    def test_hand_written_footage_without_aspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            make_clip(proj, "F1.webm")
            (proj / "footage.json").write_text(json.dumps({"footage": [{"id": "F1", "file": "F1.webm"}]}))
            self.assertEqual(prep(proj).returncode, 0)
            doc = E.Doc(proj)
            ft = E.Footage("F1", 0, 0, 3000, t_in=0, pin=False)                  # no aspect, as a person might write it
            frames, r = render(proj, [ft], [0.5])
            self.assertGreater(frames[0].std(), 5)
            self.assertAlmostEqual(ft.size(r.res)[1], 3000 * 240 / 320, delta=2)   # shape from the prepared clip
            x, y = doc.on(E.Footage("F1", 100, 200, 3000), 0.5, 0.5)                # doc.on reads the footage sizes
            self.assertAlmostEqual(x, 100, places=3); self.assertAlmostEqual(y, 200, places=3)
            with self.assertRaises(SystemExit) as e:
                E.Footage("F9", 0, 0, 3000).size_from(doc.fmeta)
            self.assertIn("run prep_footage.py", str(e.exception))

    def test_replaced_clip_is_prepared_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_proj(tmp)
            make_clip(proj, "F1.webm", seconds=2)
            (proj / "footage.json").write_text(json.dumps({"footage": [{"id": "F1", "file": "F1.webm"}]}))
            prep(proj)
            first = (proj / "assets" / "prep" / "footage" / "F1" / "f00001.jpg").read_bytes()
            self.assertEqual(prep(proj).returncode, 0)                            # unchanged: kept
            self.assertEqual((proj / "assets" / "prep" / "footage" / "F1" / "f00001.jpg").read_bytes(), first)
            make_clip(proj, "F1.webm", seconds=2, src="smptebars")                # a new pick replaced the clip
            prep(proj)
            self.assertNotEqual((proj / "assets" / "prep" / "footage" / "F1" / "f00001.jpg").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
