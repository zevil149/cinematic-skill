"""Tests for milestone 3.0: language plugins, editions/<lang>/ folders, the shared beats layer,
language isolation, and backward compatibility of single-language (English) projects.

Offline and standard library only, except the render test (skia, numpy, pillow, ffmpeg).
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
sys.path.insert(0, str(ROOT / "tests"))

import beats  # noqa: E402
import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import lang  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import storyboard  # noqa: E402
from test_docpipe import add_research, cli, fill_narration, fill_outline, make_project, quiet  # noqa: E402

try:
    import skia  # noqa: F401
    HAVE_RENDER = shutil.which("ffmpeg") is not None
except Exception:                       # pragma: no cover
    HAVE_RENDER = False

HI_LINES = ["राइट बंधुओं का विमान रेत से ऊपर उठा।", "बारह सेकंड, एक सौ बीस फ़ुट की उड़ान।", "उस दिन किसी ने इसका अर्थ नहीं समझा।"]


def production(tmp, langs=("en", "hi"), minutes=5):
    proj = pathlib.Path(tmp) / "doc"
    quiet(docpipe.new, proj, "The first powered flight", minutes, langs=list(langs))
    add_research(proj)
    quiet(outline.init, proj); fill_outline(proj)
    return proj


def write_english(proj):
    en = editions.edition_dir(proj, "en")
    quiet(narration.init, en)
    fill_narration(en)
    n = L.load(L.paths(en)["narration"])
    return en, n


def write_hindi(proj, typed="बारह सेकंड"):
    """Hindi lines for every beat, in Devanagari, with Hindi typed text and card labels."""
    hi = editions.edition_dir(proj, "hi")
    quiet(narration.init, hi)
    n = L.load(L.paths(hi)["narration"])
    for s in n["sections"]:
        for k, l in enumerate(s["lines"]):
            l["text"] = HI_LINES[(l["id"] - 1) % 3]
            if l["typed"] == "TODO":
                l["typed"] = typed
            if not l["claims"]:
                l["kind"] = "framing"
    L.save(L.paths(hi)["narration"], n)
    b = L.load(L.paths(proj)["beats"])
    for beat in b["beats"]:
        for im in beat["images"]:
            im.setdefault("labels", {})["hi"] = "पहली उड़ान की तस्वीर"
    L.save(L.paths(proj)["beats"], b)
    return hi


class LanguagePlugins(unittest.TestCase):
    def test_english_is_the_existing_rules(self):
        en = lang.get("en")
        for t in ("On December 17th, 1903, it cost $50,000.", "Twelve seconds. One hundred and twenty feet.", "In the 1920s, 45% fell."):
            self.assertEqual(en.spoken_text(t), L.spoken_text(t))
            self.assertEqual(en.est_seconds(t), L.est_seconds(t))
            self.assertEqual(en.key_word(t), storyboard.key_word(t))
            self.assertEqual(en.spoken_warnings(t), L.spoken_warnings(t))
        self.assertEqual((en.locale, en.wpm), ("en-US", 150))

    def test_hindi_writing_system(self):
        hi = lang.get("hi")
        self.assertEqual((hi.locale, hi.wpm, hi.scripts), ("hi-IN", 135, ("Devanagari",)))
        self.assertEqual(hi.check_script("राइट बंधुओं का विमान 1903 में उड़ा।"), [])
        self.assertTrue(hi.check_script("राइट Brothers का विमान"))
        self.assertEqual(hi.check_script("NASA का मिशन", allow={"NASA"}), [])
        self.assertIn("mixes", hi.check_script("Wrightबंधु")[0])
        self.assertTrue(hi.spoken_warnings("1903 में"))                  # Hindi number words come in 3.1
        self.assertEqual(hi.spoken_text("1903 में"), "1903 में")          # never English words in Hindi
        self.assertGreater(hi.est_seconds("राइट बंधुओं का विमान बारह सेकंड तक उड़ा"), 2)
        self.assertEqual(hi.key_word("विमान बारह सेकंड तक उड़ा।"), "उड़ा")

    def test_english_isolation_and_registry(self):
        en = lang.get("en")
        self.assertIn("Devanagari", en.check_script("near कोलकाता")[0])
        self.assertEqual(en.check_script("café, naïve, 1903!"), [])
        with self.assertRaises(KeyError) as e:
            lang.get("fr")
        self.assertIn("supported: en, hi", str(e.exception))
        self.assertIsNone(lang.script_of("7")); self.assertEqual(lang.script_of("७"), "Devanagari")


class Scaffold(unittest.TestCase):
    def test_new_production_with_editions(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            t = L.load(L.paths(proj)["topic"])
            self.assertEqual((t["editions"], t["default_edition"]), (["en", "hi"], "en"))
            for code in ("en", "hi"):
                ed = editions.edition_dir(proj, code)
                self.assertEqual(L.load(ed / "edition.json")["lang"], code)
                self.assertEqual(L.load(ed / "lexicon.json"), {"lang": code, "terms": {}, "allow": []})
                self.assertTrue((ed / "assets").is_symlink())
                for sub in ("03_script", "04_scenes", "06_film", "audio/takes", "out"):
                    self.assertTrue((ed / sub).is_dir(), sub)
                pe = L.paths(ed)
                self.assertEqual(pe["lang"], code)
                self.assertEqual(pe["outline"], L.paths(proj)["outline"])        # shared stages come from the root
                self.assertEqual(pe["narration"], ed / "03_script" / "narration.json")
                self.assertEqual(pe["image_needs"], proj / "03_beats" / "image_needs.json")
            self.assertEqual(cli("editions.py", "list", "--project", proj).stdout.split(), ["en", "(default)", "hi"])

    def test_add_is_idempotent_and_never_replaces_user_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp, ("en",))
            ed = editions.edition_dir(proj, "en")
            (ed / "lexicon.json").write_text('{"lang": "en", "terms": {"Kitty Hawk": {"spoken": "Kitty Hawk"}}, "allow": []}')
            (proj / "photos.json").write_text('{"photos": []}')
            (ed / "photos.json").write_text('{"photos": ["mine"]}')
            quiet(editions.add, proj, "en")
            self.assertIn("Kitty Hawk", (ed / "lexicon.json").read_text())
            self.assertEqual(L.load(ed / "photos.json"), {"photos": ["mine"]})
            self.assertEqual(L.load(L.paths(proj)["topic"])["editions"], ["en"])
            quiet(editions.add, proj, "hi")
            self.assertTrue((editions.edition_dir(proj, "hi") / "photos.json").is_symlink())
            with self.assertRaises(KeyError):
                quiet(editions.add, proj, "xx")

    def test_legacy_projects_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            p = L.paths(proj)
            self.assertFalse(p["multi"]); self.assertIsNone(p["lang"]); self.assertIsNone(p["edition"])
            self.assertEqual(p["image_needs"], proj / "04_scenes" / "image_needs.json")
            self.assertNotIn("editions", L.load(p["topic"]))
            self.assertFalse((proj / "editions").exists())
            add_research(proj); quiet(outline.init, proj); fill_outline(proj); quiet(narration.init, proj); fill_narration(proj)
            quiet(narration.export, proj)
            self.assertNotIn("lang", L.load(p["narration"]))
            self.assertNotIn("lang", L.load(p["script_json"]))
            storyboard.build(proj)
            self.assertNotIn("lang", L.load(p["storyboard"]))
            self.assertTrue(p["image_needs"].exists())
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "hi", check=False)
            self.assertIn("single-language (English) project", r.stderr)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "beats", check=False)
            self.assertIn("only in a production with editions", r.stderr)


class Isolation(unittest.TestCase):
    def test_hindi_edition_refuses_latin_unless_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi = write_hindi(proj)
            self.assertTrue(narration.check(hi).ok, narration.check(hi).errors)
            n = L.load(L.paths(hi)["narration"])
            n["sections"][0]["lines"][0]["text"] = "राइट Brothers का विमान रेत से उठा।"
            L.save(L.paths(hi)["narration"], n)
            r = narration.check(hi)
            self.assertFalse(r.ok)
            self.assertTrue(any("'Brothers' is Latin, not Hindi" in e for e in r.errors))
            L.save(hi / "lexicon.json", {"lang": "hi", "terms": {}, "allow": ["Brothers"]})
            self.assertTrue(narration.check(hi).ok)

    def test_english_edition_refuses_devanagari_but_legacy_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            en, n = write_english(proj)
            n["sections"][0]["lines"][0]["typed"] = "दिसंबर 17"
            L.save(L.paths(en)["narration"], n)
            self.assertTrue(any("Devanagari, not English" in e for e in narration.check(en).errors))
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj); quiet(outline.init, proj); fill_outline(proj); quiet(narration.init, proj); fill_narration(proj)
            n = L.load(L.paths(proj)["narration"])
            n["sections"][0]["lines"][0]["typed"] = "दिसंबर 17"
            L.save(L.paths(proj)["narration"], n)
            r = narration.check(proj)
            self.assertTrue(r.ok)
            self.assertTrue(any("Devanagari, not English" in w for w in r.warnings))

    def test_tags_must_match_the_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            en, n = write_english(proj)
            n["lang"] = "hi"
            L.save(L.paths(en)["narration"], n)
            self.assertTrue(any("tagged 'hi'" in e for e in narration.check(en).errors))
            self.assertTrue(any("narration.json is tagged 'hi'" in e for e in editions.check(proj, "en").errors))
            n["lang"] = "en"; L.save(L.paths(en)["narration"], n)
            beats.build(proj, log=lambda *a: None)
            L.save(L.paths(en)["timing"], {"lang": "hi", "segments": []})
            r = storyboard.build(en)
            self.assertFalse(r.ok)
            self.assertIn("the hi voice", r.errors[0])
            L.save(editions.edition_dir(proj, "hi") / "edition.json", {"lang": "en", "production": "../.."})
            self.assertTrue(any("says it is 'en'" in e for e in editions.check(proj, "hi").errors))


class Beats(unittest.TestCase):
    def test_build_from_source_and_keep_hand_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            en, n = write_english(proj)
            r = beats.build(proj, log=lambda *a: None)
            self.assertTrue(r.ok, r.errors)
            b = L.load(L.paths(proj)["beats"])
            lines = [l for s in n["sections"] for l in s["lines"]]
            self.assertEqual(b["source"], "en")
            self.assertEqual([x["id"] for x in b["beats"]], [f"B{l['id']:03d}" for l in lines])
            self.assertEqual(b["beats"][1]["typed"], {"en": "12 SECONDS"})
            needs = L.load(L.paths(proj)["image_needs"])["images"]
            self.assertEqual(len(needs), 9)
            self.assertEqual(needs[0]["beat"], "B001")
            self.assertFalse(L.paths(en)["scenes_dir"].joinpath("image_needs.json").exists())
            self.assertNotIn("beat", lines[0])                           # nothing written back into the narration
            b["beats"][0]["images"][0]["labels"] = {"hi": "पहली उड़ान"}
            b["beats"][0]["notes"] = "keep"
            L.save(L.paths(proj)["beats"], b)
            beats.build(proj, log=lambda *a: None)
            b2 = L.load(L.paths(proj)["beats"])
            self.assertEqual(b2["beats"][0]["images"][0]["labels"], {"hi": "पहली उड़ान"})
            self.assertEqual(b2["beats"][0]["notes"], "keep")

    def test_hindi_must_cover_every_beat_in_its_own_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi = write_hindi(proj)
            r = beats.check(proj, "hi")
            self.assertTrue(r.ok, r.errors)
            n = L.load(L.paths(hi)["narration"])
            first = n["sections"][0]["lines"]
            first[1]["typed"] = ""                                       # typed text lost
            dropped = first.pop()                                        # a beat with no line
            first[0]["beat"] = "B999"                                    # a beat that does not exist
            L.save(L.paths(hi)["narration"], n)
            b = L.load(L.paths(proj)["beats"])
            b["beats"][0]["images"][0]["labels"] = {"hi": "First flight photo"}   # an English card on the Hindi film
            L.save(L.paths(proj)["beats"], b)
            errs = " | ".join(beats.check(proj, "hi").errors)
            self.assertIn(f"beat {dropped['beat']}", errs)
            self.assertIn("'B999' is not in beats.json", errs)
            self.assertIn("give the hi line its own typed text", errs)
            self.assertIn("is Latin, not Hindi", errs)

    def test_hindi_skeleton_comes_from_beats(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi = editions.edition_dir(proj, "hi")
            quiet(narration.init, hi)
            n = L.load(L.paths(hi)["narration"])
            lines = [l for s in n["sections"] for l in s["lines"]]
            self.assertEqual(n["lang"], "hi")
            self.assertEqual(len(lines), len(L.load(L.paths(proj)["beats"])["beats"]))
            self.assertTrue(all(l["text"] == "TODO" and l["beat"] for l in lines))   # nothing copied from English
            self.assertEqual(lines[1]["typed"], "TODO")
            self.assertFalse(narration.check(hi).ok)


class TwoEditionPipeline(unittest.TestCase):
    def test_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            r = cli("docpipe.py", "run", "--project", proj, check=False)
            self.assertIn("[outline] passes its checks", r.stdout)
            cli("docpipe.py", "approve", "--project", proj, "outline")
            r = cli("docpipe.py", "run", "--project", proj, check=False)
            self.assertIn("[script@en] blocked", r.stdout)                  # English first, as the default edition
            write_english(proj)
            r = cli("docpipe.py", "run", "--project", proj, check=False)
            self.assertIn("approve --project", r.stdout); self.assertIn("script --lang en", r.stdout)
            cli("docpipe.py", "approve", "--project", proj, "script", "--lang", "en")
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "hi", "--offline", check=False)
            self.assertIn("[beats]", r.stdout)
            self.assertIn("[script@hi] blocked", r.stdout)                  # the Hindi skeleton has TODOs
            write_hindi(proj)
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "hi", "--offline", check=False)
            self.assertIn("script --lang hi", r.stdout)
            cli("docpipe.py", "approve", "--project", proj, "script", "--lang", "hi")
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "all", "--offline", check=False)
            self.assertIn("[scenes@en]", r.stdout); self.assertIn("[scenes@hi]", r.stdout)
            self.assertIn("[visuals] passes its checks", r.stdout)
            cli("docpipe.py", "approve", "--project", proj, "visuals")
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "all", "--offline")
            self.assertIn("[scenegen@en]", r.stdout); self.assertIn("[scenegen@hi]", r.stdout)
            en, hi = editions.edition_dir(proj, "en"), editions.edition_dir(proj, "hi")
            # separate, tagged outputs; one shared set of beats and images
            for code, ed in (("en", en), ("hi", hi)):
                self.assertEqual(L.load(ed / "script.json")["lang"], code)
                self.assertEqual(L.load(ed / "04_scenes" / "storyboard.json")["lang"], code)
                self.assertEqual(L.load(ed / "06_film" / "acts.json")["lang"], code)
                self.assertTrue((ed / "06_film" / "act_01" / "scene.py").exists() and (ed / "scene.py").exists())
                self.assertTrue((ed / "photos.json").is_symlink() or not (proj / "photos.json").exists())
            self.assertFalse((proj / "script.json").exists())
            en_sb, hi_sb = L.load(en / "04_scenes" / "storyboard.json"), L.load(hi / "04_scenes" / "storyboard.json")
            self.assertEqual([s["beat"] for s in en_sb["scenes"]], [s["beat"] for s in hi_sb["scenes"]])
            self.assertEqual([s["images"] for s in en_sb["scenes"]], [s["images"] for s in hi_sb["scenes"]])
            self.assertNotEqual([s["narration"] for s in en_sb["scenes"]], [s["narration"] for s in hi_sb["scenes"]])
            hi_scene = (hi / "06_film" / "act_01" / "scene.py").read_text()
            self.assertIn("पहली उड़ान की तस्वीर", hi_scene)                   # Hindi card titles
            self.assertNotIn("First flight photograph", hi_scene)
            self.assertIn("First flight photograph", (en / "06_film" / "act_01" / "scene.py").read_text())
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)
            # resume, per edition
            r = cli("docpipe.py", "run", "--project", proj, "--lang", "all", "--offline")
            for key in ("script@en", "beats", "script@hi", "scenes@hi", "visuals", "scenegen@hi"):
                self.assertIn(f"[{key}] up to date", r.stdout)
            n = L.load(L.paths(hi)["narration"]); n["sections"][0]["lines"][0]["text"] = "विमान रेत से ऊपर उठा।"
            L.save(L.paths(hi)["narration"], n)
            st = cli("docpipe.py", "status", "--project", proj).stdout
            self.assertRegex(st, r"script@hi\s+out of date")
            self.assertRegex(st, r"script@en\s+done")                      # editing Hindi never touches English


@unittest.skipUnless(HAVE_RENDER, "needs skia-python, numpy, pillow and ffmpeg")
class EditionIsAFilmProject(unittest.TestCase):
    def test_english_edition_renders_with_shared_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp, ("en",))
            en, _ = write_english(proj)
            beats.build(proj, log=lambda *a: None)
            quiet(narration.export, en)
            storyboard.build(en)
            import scenegen
            import visuals
            visuals.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            editions.link_shared(proj, en)
            scenegen.generate(en)
            subprocess.run([sys.executable, str(SCRIPTS / "prep_assets.py"), "--project", str(proj)], capture_output=True, check=True)
            sb = L.load(en / "04_scenes" / "storyboard.json")
            segs = [{"id": s["line"], "start": s["start"], "end": s["end"], "duration": s["duration"], "vo": s["narration"]} for s in sb["scenes"]]
            L.save(en / "audio" / "timing.json", {"total_duration": sb["duration"], "segments": segs})
            r = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "--project", str(en), "--probe", "3", "--size", "320x180"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            self.assertTrue((en / "out" / "probe" / "t0003.00.png").exists())


if __name__ == "__main__":
    unittest.main()
