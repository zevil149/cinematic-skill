"""Tests for milestone 4.1: the assets stage (prepare.py, docpipe `assets`).

Offline (CINEMATIC_OFFLINE=1). Fixtures are made here: a JPEG drawn with Pillow, a test-pattern clip
made by ffmpeg, a small GeoJSON. Nothing is downloaded: the network is patched to fail wherever a
download could be attempted. Needs numpy and Pillow (ffmpeg for the footage test); the film job has
them, and without them the stage reports partial (tested too).
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import prepare  # noqa: E402
from test_docpipe import add_research, fill_narration, fill_outline, make_project, quiet  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402

try:
    import numpy  # noqa: F401
    from PIL import Image
    HAVE = True
except ImportError:                          # pragma: no cover
    HAVE = False
HAVE_FFMPEG = shutil.which("ffmpeg") is not None

GEO = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "North"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 1], [2, 1], [2, 3], [0, 3], [0, 1]]]}},
    {"type": "Feature", "properties": {"name": "South"}, "geometry": {"type": "Polygon", "coordinates": [[[0, -1], [2, -1], [2, 1], [0, 1], [0, -1]]]}}]}


def photo(path, seed=1, size=(640, 420)):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size)
    px = im.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = ((x * 3 + seed * 40) % 256, (y * 2 + seed * 10) % 256, ((x + y) * seed) % 256)
    im.save(path, quality=90)
    return path


def sha(f):
    return prepare.sha_file(f)


def quietly(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def project(tmp):
    proj = pathlib.Path(tmp) / "film"
    (proj / "assets" / "photos").mkdir(parents=True)
    photo(proj / "assets" / "photos" / "a.jpg", 1)
    photo(proj / "assets" / "photos" / "b.jpg", 2)
    L.save(proj / "photos.json", {"grade": "bw", "photos": [{"id": "P1", "file": "a.jpg", "kind": "photo"},
                                                             {"id": "P2", "file": "b.jpg", "kind": "doc", "crop": [0.1, 0, 0.9, 1]}]})
    return proj


@unittest.skipUnless(HAVE, "needs numpy and Pillow")
class Photos(unittest.TestCase):
    def test_graded_resumed_and_originals_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project(tmp)
            originals = {f: sha(f) for f in [proj / "photos.json", *sorted((proj / "assets" / "photos").glob("*"))]}
            r = prepare.run(proj)
            self.assertTrue(r.ok, r.errors); self.assertFalse(r.partial)
            prep = proj / "assets" / "prep"
            meta = L.load(prep / "photos" / "meta.json")
            self.assertEqual(set(meta), {"P1", "P2"})
            self.assertEqual(meta["P2"]["kind"], "doc")
            self.assertEqual(meta["P2"]["w"], int(640 * 0.8))                       # the crop was applied
            with Image.open(prep / "photos" / "P1.jpg") as im:
                self.assertEqual((im.width, im.height), (640, 420))
            for tex in ("cork.png", "paper.png", "slate.png"):
                self.assertTrue((prep / tex).exists())
            self.assertEqual({f: sha(f) for f in originals}, originals)               # sources are only read
            man = L.load(prep / "prepared.json")
            self.assertEqual(set(man["files"]), {"photos/P1.jpg", "photos/P2.jpg"})
            # resume: nothing changed, nothing graded again
            stamps = {f: f.stat().st_mtime_ns for f in prep.glob("photos/*.jpg")}
            r = prepare.run(proj)
            self.assertIn("0 graded now", " ".join(r.notes))
            self.assertEqual({f: f.stat().st_mtime_ns for f in stamps}, stamps)
            # one photo's crop changes: only it is graded again
            spec = L.load(proj / "photos.json"); spec["photos"][0]["crop"] = [0, 0, 0.5, 1]; L.save(proj / "photos.json", spec)
            r = prepare.run(proj)
            self.assertIn("1 graded now", " ".join(r.notes))
            self.assertEqual(L.load(prep / "photos" / "meta.json")["P1"]["w"], 320)
            self.assertEqual((prep / "photos" / "P2.jpg").stat().st_mtime_ns, stamps[prep / "photos" / "P2.jpg"])

    def test_your_prepared_files_are_kept_and_force_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project(tmp)
            prepare.run(proj)
            out = proj / "assets" / "prep" / "photos" / "P1.jpg"
            photo(out, 9, (300, 200))                                                 # you retouched the graded photo
            mine = sha(out)
            spec = L.load(proj / "photos.json"); spec["grade"] = "sepia"; L.save(proj / "photos.json", spec)
            r = prepare.run(proj)
            self.assertTrue(r.ok)
            self.assertTrue(any("P1" in w and "it is yours" in w for w in r.warnings), r.warnings)
            self.assertEqual(sha(out), mine)
            self.assertEqual(L.load(proj / "assets" / "prep" / "photos" / "meta.json")["P1"]["w"], 300)
            r = prepare.run(proj, force=True)
            self.assertEqual(sha(out.with_name("P1.jpg.bak")), mine)
            self.assertNotEqual(sha(out), mine)
            # a graded file made before this stage existed (by prep_assets.py) is yours too
            out2 = proj / "assets" / "prep" / "photos" / "P2.jpg"
            man = L.load(proj / "assets" / "prep" / "prepared.json"); man["files"].pop("photos/P2.jpg"); L.save(proj / "assets" / "prep" / "prepared.json", man)
            before = sha(out2)
            spec["grade"] = "natural"; L.save(proj / "photos.json", spec)
            r = prepare.run(proj)
            self.assertTrue(any("was not prepared by this tool" in w for w in r.warnings))
            self.assertEqual(sha(out2), before)

    def test_missing_and_unreadable_photos_are_partial_not_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project(tmp)
            (proj / "assets" / "photos" / "broken.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 500)
            spec = L.load(proj / "photos.json")
            spec["photos"] += [{"id": "P3", "file": "broken.jpg"}, {"id": "P4", "file": "gone.jpg"}, {"id": "P5"}]
            L.save(proj / "photos.json", spec)
            r = prepare.run(proj)
            self.assertTrue(r.ok, r.errors); self.assertTrue(r.partial)
            self.assertTrue(any("P3" in w and "cannot be read" in w for w in r.warnings))
            self.assertTrue(any("P4" in w and "designed card" in w for w in r.warnings))
            self.assertEqual(set(L.load(proj / "assets" / "prep" / "photos" / "meta.json")), {"P1", "P2"})

    def test_without_numpy_or_pillow_the_stage_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project(tmp)
            with mock.patch.dict(sys.modules, {"numpy": None}):
                r = prepare.run(proj)
            self.assertTrue(r.ok); self.assertTrue(r.partial)
            self.assertTrue(any("numpy is not installed" in w for w in r.warnings))
            self.assertFalse((proj / "assets" / "prep" / "photos").exists())


@unittest.skipUnless(HAVE and HAVE_FFMPEG, "needs numpy, Pillow and ffmpeg")
class Footage(unittest.TestCase):
    def test_clips_become_graded_frames_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project(tmp)
            clip = proj / "assets" / "footage" / "C1.mp4"; clip.parent.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=12", str(clip)], check=True)
            L.save(proj / "footage.json", {"footage": [{"id": "C1", "file": "C1.mp4", "clip_in": 0.5, "clip_dur": 1.0}]})
            before = sha(clip)
            r = prepare.run(proj)
            self.assertTrue(r.ok, r.errors); self.assertFalse(r.partial)
            meta = L.load(proj / "assets" / "prep" / "footage" / "meta.json")
            self.assertEqual(meta["C1"]["frames"], 12)
            frames = sorted((proj / "assets" / "prep" / "footage" / "C1").glob("f*.jpg"))
            stamp = frames[0].stat().st_mtime_ns
            prepare.run(proj)
            self.assertEqual(frames[0].stat().st_mtime_ns, stamp)                     # cached by signature
            self.assertEqual(sha(clip), before)
            L.save(proj / "footage.json", {"footage": [{"id": "C2", "file": "nope.mp4"}]})
            r = prepare.run(proj)
            self.assertTrue(r.ok); self.assertTrue(r.partial)
            self.assertTrue(any("C2" in w for w in r.warnings))


@unittest.skipUnless(HAVE, "needs numpy and Pillow")
class Maps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = project(self.tmp.name)
        (self.proj / "geo").mkdir()
        (self.proj / "geo" / "regions.geojson").write_text(json.dumps(GEO))
        self.spec = {"name": "region", "source": "geo/regions.geojson", "projection": {"type": "equirect"},
                     "places": {"Town": [2.0, 1.0]}}
        L.save(self.proj / "map.json", {"maps": [self.spec]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_boundaries_build_once(self):
        r = prepare.run(self.proj)
        self.assertTrue(r.ok, r.errors)
        out = self.proj / "assets" / "prep" / "map_region.json"
        data = L.load(out)
        self.assertEqual(set(data["regions"]), {"North", "South"})
        self.assertIn("Town", data["places"])
        stamp = out.stat().st_mtime_ns
        prepare.run(self.proj)
        self.assertEqual(out.stat().st_mtime_ns, stamp)
        self.spec["places"]["Port"] = [0.5, 1.5]; L.save(self.proj / "map.json", {"maps": [self.spec]})
        prepare.run(self.proj)
        self.assertIn("Port", L.load(out)["places"])
        bad = dict(self.spec, projection={"type": "nonsense"})
        L.save(self.proj / "map.json", {"maps": [bad]})
        r = prepare.run(self.proj)
        self.assertFalse(r.ok); self.assertTrue(any("could not be built" in e for e in r.errors))

    def test_an_uncached_download_is_refused_unless_asked_and_never_offline(self):
        url = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json"
        L.save(self.proj / "map.json", {"maps": [dict(self.spec, source=url)]})
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")) as net:
            r = prepare.run(self.proj)
            self.assertFalse(r.ok); self.assertTrue(any("--download-maps" in e for e in r.errors), r.errors)
            r = prepare.run(self.proj, download_maps=True)                           # CINEMATIC_OFFLINE=1 wins
            self.assertFalse(r.ok); self.assertTrue(any("Offline" in e for e in r.errors))
            net.assert_not_called()
            # already in the download cache: built without the network
            cache = self.proj / "assets" / "data"; cache.mkdir(parents=True)
            (cache / "states-10m.json").write_text(json.dumps(GEO))
            r = prepare.run(self.proj)
            self.assertTrue(r.ok, r.errors)
            net.assert_not_called()
        self.assertTrue((self.proj / "assets" / "prep" / "map_region.json").exists())


@unittest.skipUnless(HAVE, "needs numpy and Pillow")
class Pipeline(unittest.TestCase):
    def dp(self, proj, **kw):
        out = io.StringIO()
        docpipe.OPTS.update(offline=True)
        try:
            with contextlib.redirect_stdout(out):
                ok = docpipe.run(proj, **kw)
        finally:
            docpipe.OPTS.update(offline=False)
        return ok, out.getvalue()

    def test_single_language_order_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            quiet(outline.init, proj); fill_outline(proj)
            quiet(narration.init, proj); fill_narration(proj)
            self.dp(proj); quiet(docpipe.approve, proj, "outline")
            self.dp(proj); quiet(docpipe.approve, proj, "script")
            self.dp(proj); quiet(docpipe.approve, proj, "visuals")
            photo(proj / "assets" / "photos" / "mine.jpg", 3)
            spec = L.load(proj / "photos.json", {"grade": "bw", "photos": []})
            spec["photos"].append({"id": "MINE", "file": "mine.jpg"}); L.save(proj / "photos.json", spec)
            ok, out = self.dp(proj, until="scenegen")
            self.assertTrue(ok, out)
            self.assertLess(out.index("[visuals]"), out.index("[assets]")); self.assertLess(out.index("[assets]"), out.index("[scenegen]"))
            self.assertIn("MINE", L.load(proj / "assets" / "prep" / "photos" / "meta.json"))
            ok, out = self.dp(proj, until="scenegen")
            self.assertTrue(ok, out)
            if "partial" not in out:                                                  # every image was prepared
                self.assertIn("[assets] up to date", out)
            photo(proj / "assets" / "photos" / "mine.jpg", 5)                        # a new version of your photo
            ok, out = self.dp(proj, until="scenegen")
            self.assertIn("[assets]", out); self.assertNotIn("[assets] up to date", out)
            st = io.StringIO()
            with contextlib.redirect_stdout(st):
                docpipe.status(proj)
            self.assertRegex(st.getvalue(), r"assets\s+(done|partial)")
            self.assertNotRegex(st.getvalue(), r"assets\s+planned")

    def test_editions_share_one_prepared_set(self):
        from test_editions import production, write_english, write_hindi
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            self.dp(proj); quiet(docpipe.approve, proj, "outline")
            write_english(proj)
            self.dp(proj); quiet(docpipe.approve, proj, "script", "en")
            self.dp(proj, lang="hi"); write_hindi(proj)
            self.dp(proj, lang="hi"); quiet(docpipe.approve, proj, "script", "hi")
            self.dp(proj, lang="all"); quiet(docpipe.approve, proj, "visuals")
            photo(proj / "assets" / "photos" / "shared.jpg", 4)
            spec = L.load(proj / "photos.json", {"grade": "bw", "photos": []})
            spec["photos"].append({"id": "SHARED", "file": "shared.jpg"}); L.save(proj / "photos.json", spec)
            ok, out = self.dp(proj, lang="all", until="scenegen")
            self.assertTrue(ok, out)
            self.assertEqual(out.count("[assets]"), 1)                                # shared: once, not per edition
            self.assertLess(out.index("[assets]"), out.index("[scenegen@en]"))
            for code in ("en", "hi"):
                ed = editions.edition_dir(proj, code)
                self.assertIn("SHARED", L.load(ed / "assets" / "prep" / "photos" / "meta.json"))   # through the link
                self.assertTrue(prepare.ap_paths(ed)["root"] == pathlib.Path(proj).resolve())
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)


if __name__ == "__main__":
    unittest.main()
