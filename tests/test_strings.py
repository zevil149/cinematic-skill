"""Tests for milestone 4.4: strings between clusters, from explicit links only.

Offline (CINEMATIC_OFFLINE=1). The storyboard and scene-table rules need only the standard
library; drawing the strings needs skia-python and numpy.
"""
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
    import numpy as np
    import skia  # noqa: F401
    HAVE_SKIA = True
except ImportError:                          # pragma: no cover
    HAVE_SKIA = False


def single(tmp):
    proj = make_project(tmp)
    add_research(proj)
    quiet(outline.init, proj); fill_outline(proj)
    quiet(narration.init, proj); fill_narration(proj)
    return proj


def set_links(narr_path, links):
    n = L.load(narr_path)
    for s in n["sections"]:
        for l in s["lines"]:
            if l["id"] in links:
                l["links"] = links[l["id"]]
    L.save(narr_path, n)


class Storyboard(unittest.TestCase):
    def test_links_are_explicit_checked_and_otherwise_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = single(tmp)
            p = L.paths(proj)
            storyboard.build(proj)
            plain = p["storyboard"].read_bytes()
            self.assertNotIn(b'"links"', plain)                                       # no links written, none drawn
            set_links(p["narration"], {4: [1, 999, 4], 7: [5]})
            r = storyboard.build(proj)
            sc = {s["line"]: s for s in L.load(p["storyboard"])["scenes"]}
            self.assertEqual(sc[4]["links"], [1])                                     # the unknown and the self link dropped
            self.assertEqual(sc[7]["links"], [5])
            self.assertTrue(any("999" in w for w in r.warnings))
            self.assertEqual([l for l, s in sc.items() if "links" in s], [4, 7])     # nothing inferred anywhere else
            import visuals
            visuals.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            self.assertTrue(scenegen.generate(proj).ok)
            scene = (proj / "06_film" / "act_01" / "scene.py").read_text()
            self.assertIn("'links': [1]", scene); self.assertIn("'links': [5]", scene)
            self.assertEqual(scene.count("'links'"), 2)

    def test_editions_share_the_links_through_the_beats(self):
        from test_editions import production, write_english, write_hindi
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            en = editions.edition_dir(proj, "en")
            write_english(proj)
            set_links(L.paths(en)["narration"], {7: [1], 10: [4, 404]})
            r = beats.build(proj, log=lambda *a: None)
            bs = {b["id"]: b for b in L.load(L.paths(proj)["beats"])["beats"]}
            self.assertEqual(bs["B007"]["links"], ["B001"])
            self.assertEqual(bs["B010"]["links"], ["B004"])
            self.assertTrue(any("404" in w for w in r.warnings))
            self.assertEqual(sum(1 for b in bs.values() if "links" in b), 2)
            hi = write_hindi(proj)
            for ed in (en, hi):
                quiet(narration.export, ed)
                storyboard.build(ed)
                sc = L.load(ed / "04_scenes" / "storyboard.json")["scenes"]
                first = {}
                for s in sc:
                    first.setdefault(s["beat"], s["line"])
                linked = {s["line"]: s["links"] for s in sc if "links" in s}
                self.assertEqual(linked, {first["B007"]: [first["B001"]], first["B010"]: [first["B004"]]})


@unittest.skipUnless(HAVE_SKIA, "needs skia-python and numpy")
class Drawing(unittest.TestCase):
    def doc(self, tmp, n=6):
        d = pathlib.Path(tmp)
        segs, t = [], 1.0
        for i in range(1, n + 1):
            segs.append({"id": i, "caption": f"line {i}", "vo": f"line number {i}", "start": t, "end": t + 2.0, "duration": 2.0})
            t += 2.6
        L.save(d / "audio" / "timing.json", {"total_duration": t + 3.0, "segments": segs})
        import contextlib, io, prep_assets
        (d / "assets" / "prep").mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(io.StringIO()):
            prep_assets.textures(d / "assets" / "prep")                     # the board textures
        import engine
        return engine.Doc(d)

    def table(self, links=None):
        rows = []
        for i in range(1, 7):
            rows.append({"line": i, "section": "s1" if i <= 3 else "s2", "key_word": "", "typed": f"T{i}", "hero": "",
                         "visuals": [{"need": f"I{i}", "what": f"picture {i}", "status": "fallback", "media": "image", "kind": "photo"}]})
        for line, targets in (links or {}).items():
            rows[line - 1]["links"] = targets
        return rows

    def strings(self, film):
        import engine
        return [it for it in film.items if isinstance(it, engine.StringLine)]

    def test_strings_join_the_linked_clusters_and_persist(self):
        import scenekit
        with tempfile.TemporaryDirectory() as tmp:
            doc = self.doc(tmp)
            self.assertEqual(self.strings(scenekit.build_act(doc, self.table())), [])
            film = scenekit.build_act(doc, self.table({5: [2, 99, 5], 6: [5]}))
            st = self.strings(film)
            self.assertEqual(len(st), 2)                                              # 99 is not in the act; 5->5 is itself
            pos = scenekit.layout([r for r in self.table()])
            a = next(s for s in st if s.t_in == doc.L(5) + 0.4)
            self.assertEqual(a.a, (pos[2][0], pos[2][1] - scenekit.CARD_H * 0.45))
            self.assertEqual(a.b, (pos[5][0], pos[5][1] - scenekit.CARD_H * 0.45))
            self.assertTrue(all(s.t_out is None for s in st))                         # they stay for the pull-back
            film2 = scenekit.build_act(doc, self.table({5: [2], 2: [5]}))
            self.assertEqual(len(self.strings(film2)), 1)                             # one string per pair

    def test_the_string_is_on_screen_as_it_is_pulled(self):
        import engine
        import scenekit
        with tempfile.TemporaryDirectory() as tmp:
            doc = self.doc(tmp)

            def red(table):
                film = scenekit.build_act(doc, table)
                img = engine.Renderer(film, 480, 270, doc).frame(round((doc.L(5) + 1.8) * film.fps)).astype(int)
                return int(((img[..., 0] > img[..., 1] + 45) & (img[..., 0] > 90)).sum())
            self.assertGreater(red(self.table({5: [2]})), red(self.table()) + 60)   # the red string over the board


if __name__ == "__main__":
    unittest.main()
