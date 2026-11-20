"""Tests for milestone 4.3: title cards between the acts of a film of several acts.

Offline (CINEMATIC_OFFLINE=1), mock voices. A 15 minute production has three acts; a 5 minute one
has one, and must come out exactly as before. The act rules need only the standard library; the
pipeline tests need ffmpeg and numpy, the rendering test skia.
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

import doclib as L  # noqa: E402
import docpipe  # noqa: E402
import editions  # noqa: E402
import scenegen  # noqa: E402
import storyboard  # noqa: E402

try:
    from test_pipeline_audio import HAVE as HAVE_AUDIO, use_mock
except ImportError:                          # pragma: no cover
    HAVE_AUDIO = False
try:
    import skia  # noqa: F401
    HAVE_SKIA = True
except ImportError:                          # pragma: no cover
    HAVE_SKIA = False

HI_TITLES = {"2": "किटी हॉक की ओर", "3": "NASA से पहले की उड़ान"}


def dp(proj, **kw):
    out = io.StringIO()
    docpipe.OPTS.update(offline=True)
    try:
        with contextlib.redirect_stdout(out):
            ok = docpipe.run(proj, **kw)
    finally:
        docpipe.OPTS.update(offline=False)
    return ok, out.getvalue()


def approve(proj, name, lang=None):
    with contextlib.redirect_stdout(io.StringIO()):
        docpipe.approve(proj, name, lang)


def production(tmp, minutes, hi_titles=HI_TITLES, until="scenes"):
    """A two-edition production through its gates, its scripts written, voices set to the mock."""
    from test_editions import production as make, write_english, write_hindi
    proj = make(tmp, minutes=minutes)
    dp(proj); approve(proj, "outline")
    write_english(proj)
    dp(proj); approve(proj, "script", "en")
    dp(proj, lang="hi"); write_hindi(proj)
    hi = editions.edition_dir(proj, "hi")
    if hi_titles:
        n = L.load(hi / "03_script" / "narration.json"); n["act_titles"] = hi_titles; L.save(hi / "03_script" / "narration.json", n)
    dp(proj, lang="hi"); approve(proj, "script", "hi")
    en = editions.edition_dir(proj, "en")
    if HAVE_AUDIO:
        use_mock(en, hi)
    return proj, en, hi


class ActRules(unittest.TestCase):
    def test_act_starts(self):
        one = {"sections": [{"id": "a", "act": 0}, {"id": "b", "act": 1}]}
        three = {"sections": [{"id": "a", "act": 0}, {"id": "b", "act": 1}, {"id": "c", "act": 2}, {"id": "d", "act": 3}]}
        lines = [(1, "a"), (2, "b"), (3, "b"), (4, "c"), (5, "d"), (6, "d")]
        self.assertEqual(L.act_starts(one, lines[:3]), set())                  # the opening belongs to act 1
        self.assertEqual(L.act_starts(three, lines), {4, 5})
        self.assertEqual(L.section_acts(three), {"a": 1, "b": 1, "c": 2, "d": 3})


class Titles(unittest.TestCase):
    def test_sources_of_act_titles_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 15)
            outline = L.load(L.paths(proj)["outline"])
            r = L.Result()
            t = scenegen.act_titles(L.paths(en), outline, [2, 3], r)
            first2 = next(s["title"] for s in outline["sections"] if s.get("act") == 2)
            self.assertEqual((t[2]["title"], t[2]["label"]), (first2, "ACT 2"))       # the act's first section
            outline["act_titles"] = {"2": "Toward Kitty Hawk"}
            t = scenegen.act_titles(L.paths(en), outline, [2, 3], r)
            self.assertEqual(t[2]["title"], "Toward Kitty Hawk")                     # the outline's title
            n = L.load(en / "03_script" / "narration.json"); n["act_titles"] = {"3": "The long road"}; L.save(en / "03_script" / "narration.json", n)
            self.assertEqual(scenegen.act_titles(L.paths(en), outline, [2, 3], r)[3]["title"], "The long road")  # the edition's own
            t = scenegen.act_titles(L.paths(hi), outline, [2, 3], r)
            self.assertEqual((t[2]["title"], t[2]["label"]), (HI_TITLES["2"], "भाग 2"))
            self.assertTrue(r.ok, r.errors)
            # NASA is allowed by the Hindi lexicon; another Latin word is only a warning
            n = L.load(hi / "03_script" / "narration.json"); n["act_titles"]["2"] = "Kitty Hawk की ओर"; L.save(hi / "03_script" / "narration.json", n)
            r = L.Result()
            t = scenegen.act_titles(L.paths(hi), outline, [2, 3], r)
            self.assertTrue(r.ok); self.assertTrue(any("Kitty" in w for w in r.warnings), r.warnings)
            self.assertEqual(t[2]["title"], "Kitty Hawk की ओर")
            # Hindi never borrows the English titles
            n.pop("act_titles"); L.save(hi / "03_script" / "narration.json", n)
            r = L.Result()
            scenegen.act_titles(L.paths(hi), outline, [2, 3], r)
            self.assertFalse(r.ok); self.assertTrue(any("act_titles" in e for e in r.errors))

    def test_estimated_storyboard_holds_the_act_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 15)
            ok, out = dp(proj, lang="all", until="scenes")
            for ed in (en, hi):
                sc = L.load(ed / "04_scenes" / "storyboard.json")["scenes"]
                acts = L.section_acts(L.load(L.paths(proj)["outline"]))
                changes = [(a, b) for a, b in zip(sc, sc[1:]) if acts[a["section"]] != acts[b["section"]]]
                self.assertEqual(len(changes), 2)
                for a, b in changes:
                    self.assertAlmostEqual(b["start"] - a["end"], L.ACT_GAP, delta=0.02)


@unittest.skipUnless(HAVE_AUDIO, "needs ffmpeg and numpy")
class Pipeline(unittest.TestCase):
    def test_three_acts_hold_silence_and_open_on_their_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 15)
            dp(proj, lang="all"); approve(proj, "visuals")
            ok, out = dp(proj, lang="all", until="subtitles")
            self.assertTrue(ok, out)
            for ed, code in ((en, "en"), (hi, "hi")):
                t = L.load(ed / "audio" / "timing.json")
                segs = t["segments"]
                changes = [(a, b) for a, b in zip(segs, segs[1:]) if a["act"] != b["act"]]
                self.assertEqual([(a["act"], b["act"]) for a, b in changes], [(1, 2), (2, 3)])
                for a, b in changes:
                    self.assertAlmostEqual(b["start"] - a["end"], L.ACT_GAP, delta=0.01)   # held silence
                acts = L.load(ed / "06_film" / "acts.json")["acts"]
                self.assertNotIn("title_card", acts[0])
                for a in acts[1:]:
                    first = next(s for s in segs if s["id"] == a["lines"][0])
                    self.assertAlmostEqual(a["t0"], first["start"] - L.ACT_GAP, delta=0.02)
                    self.assertAlmostEqual(a["title_card"]["t1"], first["start"], delta=0.02)
                    scene = (ed / a["scene"]).read_text(encoding="utf-8")
                    self.assertIn("ACT = {", scene); self.assertIn("title=ACT", scene)
                    self.assertIn(a["title_card"]["title"], scene)
                # no subtitle is on screen during a card's silence
                cues = L.load(ed / "audio" / "subs.json")["cues"]
                for a in acts[1:]:
                    c0, c1 = a["title_card"]["t0"], a["title_card"]["t1"]
                    self.assertFalse([c for c in cues if c["t0"] < c1 - 0.05 and c["t1"] > c0 + 0.05], code)
            self.assertIn(HI_TITLES["3"], (hi / "06_film" / "act_03" / "scene.py").read_text(encoding="utf-8"))
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)
            # resume, and a scene you edited keeps your edit when the titles change
            ok, out = dp(proj, lang="all", until="subtitles")
            self.assertTrue(ok, out); self.assertIn("[narration@hi] up to date", out)
            act3 = hi / "06_film" / "act_03" / "scene.py"
            act3.write_text(act3.read_text(encoding="utf-8") + "\n# my change\n", encoding="utf-8")
            n = L.load(hi / "03_script" / "narration.json"); n["act_titles"]["3"] = "एक नई सुबह"; L.save(hi / "03_script" / "narration.json", n)
            r = scenegen.generate(hi)
            self.assertTrue(any("has your edits" in w for w in r.warnings))
            self.assertIn("# my change", act3.read_text(encoding="utf-8"))
            self.assertNotIn("एक नई सुबह", act3.read_text(encoding="utf-8"))           # your scene is not regenerated
            self.assertEqual(L.load(hi / "06_film" / "acts.json")["acts"][2]["title_card"]["title"], "एक नई सुबह")

    def test_hindi_without_titles_stops_at_its_scenes_and_english_goes_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 15, hi_titles=None)
            dp(proj, lang="all"); approve(proj, "visuals")
            ok, out = dp(proj, lang="all", until="scenegen")
            self.assertFalse(ok)
            self.assertIn("[scenegen@en]", out); self.assertIn("[scenegen@hi] blocked", out)
            self.assertIn("act_titles", out)
            self.assertTrue((en / "06_film" / "act_02" / "scene.py").exists())

    def test_one_act_films_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 5, hi_titles=None)
            dp(proj, lang="all"); approve(proj, "visuals")
            ok, out = dp(proj, lang="all", until="subtitles")
            self.assertTrue(ok, out)
            for ed in (en, hi):
                t = L.load(ed / "audio" / "timing.json")
                self.assertFalse(any("act" in s for s in t["segments"]))
                self.assertFalse(any(round(b["start"] - a["end"], 2) == L.ACT_GAP for a, b in zip(t["segments"], t["segments"][1:])))
                acts = L.load(ed / "06_film" / "acts.json")["acts"]
                self.assertEqual(len(acts), 1); self.assertNotIn("title_card", acts[0])
                self.assertNotIn("ACT =", (ed / "06_film" / "act_01" / "scene.py").read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_AUDIO and HAVE_SKIA, "needs ffmpeg, numpy and skia-python")
class Rendering(unittest.TestCase):
    def test_title_cards_render_in_both_editions(self):
        import numpy as np
        import review
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = production(tmp, 15)
            dp(proj, lang="all"); approve(proj, "visuals")
            self.assertTrue(dp(proj, lang="all", until="narration")[0])
            for ed, code in ((en, "en"), (hi, "hi")):
                r = review.build(ed, log=lambda *a: None)
                self.assertTrue(r.ok, r.errors)
                rv = L.load(proj / "07_review" / code / "review.json")
                for a in rv["acts"][1:]:
                    pt = next(x for x in a["probes"] if x["name"] == "probe_title")
                    self.assertNotIn("blank", pt["flags"])
                    img = np.asarray(Image.open(proj / "07_review" / code / pt["file"]).convert("L"), dtype=float)
                    mid = img[img.shape[0] // 3: 2 * img.shape[0] // 3, img.shape[1] // 4: 3 * img.shape[1] // 4]
                    self.assertGreater(float((mid > 170).mean()), 0.01, code)         # light type in the middle of the frame
                self.assertNotIn("probe_title", [x["name"] for x in rv["acts"][0]["probes"]])


if __name__ == "__main__":
    unittest.main()
