"""Tests for milestone 4.5: maps, pins and routes from explicit places in the storyboard.

Offline (CINEMATIC_OFFLINE=1). The map data is a small GeoJSON written here and built by the
assets stage from a local file: nothing is downloaded. The storyboard rules need only the
standard library; building the map and drawing it need numpy, Pillow and skia-python.
"""
import contextlib
import io
import json
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

import beats  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import scenegen  # noqa: E402
import storyboard  # noqa: E402
from test_docpipe import add_research, fill_narration, fill_outline, make_project, quiet  # noqa: E402

try:
    import numpy  # noqa: F401
    import skia  # noqa: F401
    from PIL import Image  # noqa: F401
    HAVE_SKIA = True
except ImportError:                          # pragma: no cover
    HAVE_SKIA = False

GEO = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Ohio"}, "geometry": {"type": "Polygon", "coordinates": [[[-85, 38.5], [-80.5, 38.5], [-80.5, 42], [-85, 42], [-85, 38.5]]]}},
    {"type": "Feature", "properties": {"name": "Carolina"}, "geometry": {"type": "Polygon", "coordinates": [[[-80.5, 34], [-75.5, 34], [-75.5, 37], [-80.5, 37], [-80.5, 34]]]}}]}
MAP = {"name": "east", "source": "geo/east.geojson", "projection": {"type": "equirect", "lon0": -80, "lat0": 38},
       "places": {"Dayton": [39.76, -84.19], "Kitty Hawk": [36.06, -75.70]},
       "labels": {"Kitty Hawk": {"hi": "किटी हॉक"}, "Dayton": {"hi": "डेटन"}}}


def write_map(root, maps=None):
    root = pathlib.Path(root)
    (root / "geo").mkdir(parents=True, exist_ok=True)
    (root / "geo" / "east.geojson").write_text(json.dumps(GEO))
    L.save(root / "map.json", {"maps": maps or [MAP]})


def set_lines(narr_path, fields):
    n = L.load(narr_path)
    for s in n["sections"]:
        for l in s["lines"]:
            l.update(fields.get(l["id"], {}))
    L.save(narr_path, n)


def single(tmp):
    proj = make_project(tmp)
    add_research(proj)
    quiet(outline.init, proj); fill_outline(proj)
    quiet(narration.init, proj); fill_narration(proj)
    return proj


class Storyboard(unittest.TestCase):
    def test_places_are_explicit_and_checked_against_map_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = single(tmp)
            p = L.paths(proj)
            write_map(proj)
            storyboard.build(proj)
            self.assertNotIn(b'"place"', p["storyboard"].read_bytes())             # no place given, none drawn
            set_lines(p["narration"], {1: {"place": "Dayton"}, 4: {"place": "Kitty Hawk"}, 7: {"place": "Atlantis"}})
            r = storyboard.build(proj)
            sc = {s["line"]: s for s in L.load(p["storyboard"])["scenes"]}
            self.assertEqual(sc[1]["place"], {"name": "Dayton", "map": "east", "label": "Dayton"})
            self.assertEqual(sc[4]["place"]["name"], "Kitty Hawk")
            self.assertNotIn("place", sc[7])                                          # unknown: dropped, not guessed
            self.assertTrue(any("Atlantis" in w for w in r.warnings))
            self.assertEqual(sorted(l for l, s in sc.items() if "place" in s), [1, 4])
            # a place on two maps needs the line to say which
            other = dict(MAP, name="west")
            write_map(proj, [MAP, other])
            r = storyboard.build(proj)
            self.assertTrue(any("several maps" in w for w in r.warnings))
            set_lines(p["narration"], {1: {"map": "west"}})
            storyboard.build(proj)
            self.assertEqual(L.load(p["storyboard"])["scenes"][0]["place"]["map"], "west")
            import visuals
            visuals.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            self.assertTrue(scenegen.generate(proj).ok)
            scene = (proj / "06_film" / "act_01" / "scene.py").read_text()
            self.assertIn("'place': {'name': 'Dayton', 'map': 'west', 'label': 'Dayton'}", scene)

    def test_editions_label_places_in_their_own_language(self):
        from test_editions import production, write_english, write_hindi
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_map(proj)
            en = editions.edition_dir(proj, "en")
            write_english(proj)
            set_lines(L.paths(en)["narration"], {1: {"place": "Dayton"}, 4: {"place": "Kitty Hawk", "map": "east"}})
            beats.build(proj, log=lambda *a: None)
            bs = {b["id"]: b for b in L.load(L.paths(proj)["beats"])["beats"]}
            self.assertEqual((bs["B001"]["place"], bs["B004"]["map"]), ("Dayton", "east"))
            hi = write_hindi(proj)
            for ed in (en, hi):
                quiet(narration.export, ed)
                storyboard.build(ed)
            hsc = [s for s in L.load(hi / "04_scenes" / "storyboard.json")["scenes"] if "place" in s]
            self.assertEqual([s["place"]["label"] for s in hsc], ["डेटन", "किटी हॉक"])
            esc = [s for s in L.load(en / "04_scenes" / "storyboard.json")["scenes"] if "place" in s]
            self.assertEqual([s["place"]["label"] for s in esc], ["Dayton", "Kitty Hawk"])
            # no Hindi label: the lexicon's spelling, else a pin without a label (and a warning)
            m = dict(MAP, labels={}); write_map(proj, [m])
            lx = L.load(hi / "lexicon.json"); lx.setdefault("terms", {})["Dayton"] = {"spoken": "डेटन"}; L.save(hi / "lexicon.json", lx)
            r = storyboard.build(hi)
            hsc = [s for s in L.load(hi / "04_scenes" / "storyboard.json")["scenes"] if "place" in s]
            self.assertEqual([s["place"]["label"] for s in hsc], ["डेटन", ""])
            self.assertTrue(any("no hi label" in w for w in r.warnings))


@unittest.skipUnless(HAVE_SKIA, "needs numpy, Pillow and skia-python")
class Drawing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        segs, t = [], 1.0
        for i in range(1, 7):
            segs.append({"id": i, "caption": f"line {i}", "vo": f"line number {i}", "start": t, "end": t + 2.0, "duration": 2.0})
            t += 2.6
        L.save(d / "audio" / "timing.json", {"total_duration": t + 3.0, "segments": segs})
        write_map(d)
        import prepare
        self.assertTrue(prepare.run(d).ok)                                        # the assets stage builds the map, offline
        import engine
        self.doc = engine.Doc(d)

    def tearDown(self):
        self.tmp.cleanup()

    def table(self, places=None):
        rows = []
        for i in range(1, 7):
            rows.append({"line": i, "section": "s1" if i <= 3 else "s2", "key_word": "", "typed": "", "hero": "",
                         "visuals": [{"need": f"I{i}", "what": f"picture {i}", "status": "fallback", "media": "image", "kind": "photo"}]})
        for line, pl in (places or {}).items():
            rows[line - 1]["place"] = pl
        return rows

    def items(self, film, cls):
        return [it for it in film.items if isinstance(it, cls)]

    def test_pins_routes_and_the_map_sheet(self):
        import engine
        import scenekit
        plain = scenekit.build_act(self.doc, self.table())
        self.assertEqual(self.items(plain, engine.GeoMap), [])
        film = scenekit.build_act(self.doc, self.table({
            2: {"name": "Dayton", "map": "east", "label": "Dayton"},
            5: {"name": "Kitty Hawk", "map": "east", "label": "किटी हॉक"},
            6: {"name": "Nowhere", "map": "east", "label": "x"}}))
        maps = self.items(film, engine.GeoMap)
        pins = self.items(film, engine.MapPin)
        routes = self.items(film, engine.Route)
        self.assertEqual(len(maps), 1)
        self.assertEqual([p.label for p in pins], ["Dayton", "किटी हॉक"])             # the unknown place is skipped
        self.assertEqual(len(routes), 1)                                          # Dayton to Kitty Hawk
        self.assertAlmostEqual(routes[0].t_in, self.doc.L(5) - 0.3)
        k = pins[0]
        self.assertEqual((k.x, k.y), maps[0].place("Dayton"))
        self.assertLess(pins[1].x - pins[0].x, scenekit.CLUSTER_X)               # one sheet, both pins on it
        # a map that is not prepared yet: no sheet, no pin, no crash
        film = scenekit.build_act(self.doc, self.table({2: {"name": "Dayton", "map": "missing", "label": "Dayton"}}))
        self.assertEqual(self.items(film, engine.GeoMap), [])

    def test_the_pin_is_on_screen_with_its_line(self):
        import engine
        import scenekit
        places = {2: {"name": "Dayton", "map": "east", "label": "Dayton"}, 5: {"name": "Kitty Hawk", "map": "east", "label": "Kitty Hawk"}}
        film = scenekit.build_act(self.doc, self.table(places))
        img = engine.Renderer(film, 480, 270, self.doc).frame(round((self.doc.L(5) + 1.0) * film.fps)).astype(int)
        base = scenekit.build_act(self.doc, self.table())
        img0 = engine.Renderer(base, 480, 270, self.doc).frame(round((self.doc.L(5) + 1.0) * base.fps)).astype(int)
        self.assertGreater(abs(img.mean() - img0.mean()), 3)                      # the map sheet is in the frame
        self.assertGreater(float(img.std()), 10)


if __name__ == "__main__":
    unittest.main()
