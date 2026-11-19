"""Tests for phase 2 stages 2.4 and 2.5: scene starters per act, and the visuals and scenegen
stages in docpipe. Generation tests use the standard library only; the render test needs
skia-python, numpy, pillow and ffmpeg and is skipped without them.
"""
import io
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
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402
import docpipe  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import scenegen  # noqa: E402
import storyboard  # noqa: E402
import visuals as V  # noqa: E402
from test_docpipe import add_research, cli, fill_narration, fill_outline, make_project, quiet  # noqa: E402
from test_visuals import COMMONS, FakeNet, Resp  # noqa: E402

try:
    import skia  # noqa: F401
    from PIL import Image
    HAVE_RENDER = shutil.which("ffmpeg") is not None
except Exception:                          # pragma: no cover
    HAVE_RENDER = False


def doc_project(tmp, minutes=5):
    proj = make_project(tmp, minutes)
    add_research(proj)
    quiet(outline.init, proj); fill_outline(proj)
    quiet(narration.init, proj); fill_narration(proj)
    storyboard.build(proj)
    return proj


def offline_visuals(proj):
    V.run(proj, offline=True, providers=["commons"], log=lambda *a: None)


class Generate(unittest.TestCase):
    def test_one_act_starter_and_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp)
            offline_visuals(proj)
            r = scenegen.generate(proj)
            self.assertTrue(r.ok, r.errors)
            acts = L.load(proj / "06_film" / "acts.json")["acts"]
            self.assertEqual([a["act"] for a in acts], [1])
            act = (proj / "06_film" / "act_01" / "scene.py").read_text()
            compile(act, "act", "exec")
            self.assertIn("from scenekit import build_act", act)
            self.assertIn("'status': 'fallback'", act)
            root = (proj / "scene.py").read_text()
            compile(root, "root", "exec")
            self.assertIn(scenegen.ROOT_MARK, root)
            self.assertTrue(any("designed cards" in w for w in r.warnings))

    def test_long_film_splits_into_acts(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp, minutes=20)
            offline_visuals(proj)
            scenegen.generate(proj)
            acts = L.load(proj / "06_film" / "acts.json")["acts"]
            self.assertEqual([a["act"] for a in acts], [1, 2, 3])
            self.assertTrue(all((proj / a["scene"]).exists() for a in acts))
            starts = [a["t0"] for a in acts]
            self.assertEqual(starts, sorted(starts))
            self.assertFalse(set(acts[0]["lines"]) & set(acts[1]["lines"]))

    def test_edits_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp)
            offline_visuals(proj)
            scenegen.generate(proj)
            act = proj / "06_film" / "act_01" / "scene.py"
            act.write_text(act.read_text() + "\n# my edit\n")
            r = scenegen.generate(proj)
            self.assertIn("# my edit", act.read_text())
            self.assertTrue(any("has your edits" in w for w in r.warnings))
            scenegen.generate(proj)                                   # still kept on later runs
            self.assertIn("# my edit", act.read_text())
            scenegen.generate(proj, force=True)
            self.assertNotIn("# my edit", act.read_text())
            self.assertIn("# my edit", act.with_suffix(".py.bak").read_text())

    def test_foreign_root_scene_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp)
            offline_visuals(proj)
            (proj / "scene.py").write_text("# my own scene\n")
            r = scenegen.generate(proj)
            self.assertEqual((proj / "scene.py").read_text(), "# my own scene\n")
            self.assertTrue(any("not written by scenegen" in w for w in r.warnings))


class PipelinePhase2(unittest.TestCase):
    def test_visuals_gate_and_scenegen_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            quiet(outline.init, proj); fill_outline(proj)
            quiet(narration.init, proj); fill_narration(proj)
            cli("docpipe.py", "run", "--project", proj, check=False)
            cli("docpipe.py", "approve", "--project", proj, "outline")
            cli("docpipe.py", "run", "--project", proj, check=False)
            cli("docpipe.py", "approve", "--project", proj, "script")
            r = cli("docpipe.py", "run", "--project", proj, "--offline", check=False)
            self.assertIn("[visuals] passes its checks", r.stdout)
            self.assertTrue((proj / "05_visuals" / "assets.json").exists())
            cli("docpipe.py", "approve", "--project", proj, "visuals")
            r = cli("docpipe.py", "run", "--project", proj, "--offline")
            self.assertIn("[scenegen]", r.stdout)
            self.assertTrue((proj / "06_film" / "act_01" / "scene.py").exists())
            st = cli("docpipe.py", "status", "--project", proj).stdout
            self.assertRegex(st, r"scenegen\s+done")
            self.assertRegex(st, r"visuals\s+done\s+\[gate\]")
            r = cli("docpipe.py", "run", "--project", proj, "--offline")
            self.assertIn("[scenegen] up to date", r.stdout)
            # choosing a fallback in selection.json reopens visuals and lapses its approval
            L.save(proj / "05_visuals" / "selection.json", {"I001": "fallback"})
            r = cli("docpipe.py", "run", "--project", proj, "--offline", check=False)
            self.assertIn("[visuals] passes its checks", r.stdout)

    def test_partial_when_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp)
            res = L.Result()
            res.partial = True
            orig = docpipe.STAGES
            try:
                docpipe.STAGES = [s if s[0] != "visuals" else ("visuals", lambda p: res, s[2], False) for s in orig]
                st = L.load(L.paths(proj)["state"])
                for name in ("topic", "research", "outline", "script", "scenes"):
                    st["stages"][name] = {"status": "done", "inputs": L.hash_files(docpipe._inputs(L.paths(proj), *dict((x[0], x[2]) for x in orig)[name])),
                                          "approved": L.hash_files(docpipe._inputs(L.paths(proj), *dict((x[0], x[2]) for x in orig)[name]))}
                L.save(L.paths(proj)["state"], st)
                quiet(docpipe.run, proj, until="visuals")
                self.assertEqual(docpipe.load_state(proj)["stages"]["visuals"]["status"], "partial")
                out = io.StringIO()
                import contextlib
                with contextlib.redirect_stdout(out):
                    docpipe.run(proj, until="visuals")
                self.assertNotIn("[visuals] up to date", out.getvalue())        # deferred work is retried
            finally:
                docpipe.STAGES = orig


def make_image(path, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    a = (rng.random((360, 480, 3)) * 255).astype("uint8")
    Image.fromarray(a).save(path, "JPEG")
    return path.read_bytes()


@unittest.skipUnless(HAVE_RENDER, "needs skia-python, numpy, pillow and ffmpeg")
class RenderActs(unittest.TestCase):
    def test_generated_acts_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = doc_project(tmp, minutes=20)
            jpg = make_image(pathlib.Path(tmp) / "x.jpg", 5)
            net = FakeNet({"commons.wikimedia.org": lambda u: Resp(COMMONS), "upload.wikimedia.org": lambda u: Resp(jpg, "image/jpeg")})
            http = V.make_http(proj); http.opener = net; http.sleep = lambda s: None; http.log = lambda *a: None
            V.run(proj, http=http, providers=["commons"], log=lambda *a: None)
            subprocess.run([sys.executable, str(SCRIPTS / "prep_assets.py"), "--project", str(proj)], capture_output=True, check=True)
            scenegen.generate(proj)
            # a scratch "voice": timing from the storyboard estimates, so the scenes have times to work with
            sb = L.load(L.paths(proj)["storyboard"])
            n = L.load(L.paths(proj)["narration"])
            vo = {l["id"]: L.spoken_text(l["text"]) for s in n["sections"] for l in s["lines"]}
            segs = [{"id": s["line"], "start": s["start"], "end": s["end"], "duration": s["duration"], "vo": vo[s["line"]]} for s in sb["scenes"]]
            (proj / "audio").mkdir(exist_ok=True)
            L.save(proj / "audio" / "timing.json", {"total_duration": sb["duration"], "segments": segs})
            acts = L.load(proj / "06_film" / "acts.json")["acts"]
            for a in (acts[0], acts[1]):
                t = round((a["t0"] + a["t1"]) / 2, 1)
                env = {**os.environ, "CINEMATIC_ACT": str(a["act"])}
                r = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "--project", str(proj), "--probe", str(t), "--size", "320x180"],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr[-1500:])
                png = proj / "out" / "probe" / f"t{t:07.2f}.png"
                self.assertTrue(png.exists())
                import numpy as np
                self.assertGreater(np.asarray(Image.open(png)).std(), 5)         # not an empty frame
            r = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "--project", str(proj), "--probe", "1"],
                               capture_output=True, text=True, env={**os.environ, "CINEMATIC_ACT": "9"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("this film has acts", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
