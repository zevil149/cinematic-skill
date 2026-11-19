"""Tests for the documentary pipeline, phase 1: project, topic, research, outline, script, scenes.

  python3 -m unittest discover -s tests -v

Standard library only; no network, skia or ffmpeg needed.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doclib as L  # noqa: E402
import docpipe  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import research  # noqa: E402
import storyboard  # noqa: E402


def cli(tool, *args, check=True):
    r = subprocess.run([sys.executable, str(SCRIPTS / tool), *map(str, args)], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{tool} {' '.join(map(str, args))} failed:\n{r.stdout}\n{r.stderr}")
    return r


def quiet(fn, *a, **k):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class SpokenText(unittest.TestCase):
    def test_years_dates_money(self):
        cases = {
            "December 17th, 1903.": "December seventeenth, nineteen oh three.",
            "It cost $50,000.": "It cost fifty thousand dollars.",
            "In 2003 and 2024": "In two thousand and three and twenty twenty-four",
            "the 1920s": "the nineteen twenties",
            "the 1900s": "the nineteen hundreds",
            "45% of 1,200 men": "forty-five percent of one thousand two hundred men",
            "852 feet": "eight hundred and fifty-two feet",
            "3.5 miles": "three point five miles",
            "the 21st century": "the twenty-first century",
            "$2 million": "two million dollars",
        }
        for text, want in cases.items():
            self.assertEqual(L.spoken_text(text), want, text)

    def test_warnings(self):
        self.assertTrue(L.spoken_warnings("in 1903"))
        self.assertTrue(any("abbreviations" in w for w in L.spoken_warnings("near Kitty Hawk, N.C.")))
        self.assertEqual(L.spoken_warnings("Twelve seconds. One hundred and twenty feet."), [])

    def test_numbers_in(self):
        self.assertEqual(L.numbers_in("Twelve seconds. One hundred and twenty feet."), {12.0, 120.0})
        self.assertEqual(L.numbers_in("$50,000 in 1903, the 17th"), {50000.0, 1903.0, 17.0})
        self.assertEqual(L.numbers_in("one man and a plane"), set())


class LengthPlan(unittest.TestCase):
    def test_presets(self):
        for minutes, chapters, acts in ((5, 5, 1), (10, 8, 1), (20, 14, 3), (30, 21, 4)):
            p = L.length_plan(minutes)
            self.assertEqual((p["chapters"], p["acts"]), (chapters, acts), minutes)
            total = sum(s["target_seconds"] for s in p["sections"])
            self.assertAlmostEqual(total, minutes * 60, delta=2)
            self.assertEqual(p["sections"][0]["kind"], "cold_open")
            self.assertEqual(p["sections"][-1]["kind"], "close")
            self.assertEqual(p["words"], minutes * 150)

    def test_bounds(self):
        for bad in (0, 61, -5):
            with self.assertRaises(ValueError):
                L.length_plan(bad)


class Sources(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(L.source_tier({"url": "https://www.loc.gov/item/x"}), 1)
        self.assertEqual(L.source_tier({"url": "https://airandspace.si.edu/x"}), 1)
        self.assertEqual(L.source_tier({"url": "https://history.state.gov/x"}), 1)
        self.assertEqual(L.source_tier({"url": "https://en.wikipedia.org/wiki/X"}), 3)
        self.assertEqual(L.source_tier({"url": "https://www.nytimes.com/x"}), 2)
        self.assertEqual(L.source_tier({"title": "A book", "type": "book"}), 2)
        self.assertEqual(L.source_tier({"url": "https://en.wikipedia.org/wiki/X", "tier": 2}), 2)

    def test_claim_status(self):
        S = {"G": {"id": "G", "url": "https://www.nps.gov/wrbr"}, "W": {"id": "W", "url": "https://en.wikipedia.org/wiki/X"},
             "N1": {"id": "N1", "url": "https://www.bbc.co.uk/a"}, "N2": {"id": "N2", "url": "https://news.bbc.co.uk/b"},
             "N3": {"id": "N3", "url": "https://www.theguardian.com/c"}}
        st = lambda text, srcs, **k: L.claim_status({"text": text, "sources": srcs, **k}, S)
        self.assertEqual(st("It flew.", []), "unsupported")
        self.assertEqual(st("It flew.", ["missing"]), "unsupported")
        self.assertEqual(st("It flew 12 seconds.", ["W"]), "weak")
        self.assertEqual(st("It flew 12 seconds.", ["N1"]), "single-source")
        self.assertEqual(st("It flew 12 seconds.", ["N1", "N2"]), "single-source")     # same site twice
        self.assertEqual(st("It flew 12 seconds.", ["N1", "N3"]), "supported")
        self.assertEqual(st("It flew 12 seconds.", ["G"]), "supported")
        self.assertEqual(st("It flew.", ["N1"]), "supported")                           # no number to pin down
        self.assertEqual(st("It flew 12 seconds.", ["G"], disputed=True), "disputed")


def make_project(tmp, minutes=5):
    proj = pathlib.Path(tmp) / "doc"
    quiet(docpipe.new, proj, "The first powered flight", minutes, angle="two brothers, one rival")
    return proj


def add_research(proj):
    quiet(research.add_source, proj, url="https://www.nps.gov/wrbr/learn/historyculture/thefirstflight.htm",
          title="The First Flight", publisher="National Park Service", type="government")
    quiet(research.add_source, proj, url="https://airandspace.si.edu/collection-objects/1903-wright-flyer",
          title="1903 Wright Flyer", publisher="Smithsonian", type="museum")
    quiet(research.add_source, proj, url="https://en.wikipedia.org/wiki/Wright_Flyer", title="Wright Flyer", type="wiki")
    quiet(research.add_claim, proj, "On December 17, 1903 the first flight lasted 12 seconds and covered 120 feet.", ["S1", "S2"])
    quiet(research.add_claim, proj, "John T. Daniels took the photograph of the first flight.", ["S1"])
    quiet(research.add_claim, proj, "The Flyer was built of spruce and muslin.", ["S3"])                 # weak
    quiet(research.add_claim, proj, "The brothers ran a bicycle shop in Dayton, Ohio.", ["S2"])


def fill_outline(proj):
    p = L.paths(proj)
    o = L.load(p["outline"])
    year = 1896
    for s in o["sections"]:
        s["title"] = f"{s['kind']} {s['id']}"
        s["purpose"] = "what the viewer learns here"
        if s["kind"] == "chapter":
            s["period"] = str(year); year += 1
        s["claims"] = ["C1"] if s["kind"] != "close" else []
    L.save(p["outline"], o)


def fill_narration(proj):
    p = L.paths(proj)
    n = L.load(p["narration"])
    nid = 1
    for s in n["sections"]:
        s["lines"] = [
            {"id": nid, "text": "On December 17th, 1903, a machine left the sand.", "claims": ["C1"],
             "visual": "the date set big, then the photo", "hero": "the date", "typed": "DECEMBER 17, 1903",
             "images": [{"what": "First flight photograph", "kind": "photo", "query": "Wright first flight 1903"}]},
            {"id": nid + 1, "text": "Twelve seconds. One hundred and twenty feet.", "claims": ["C1"],
             "visual": "counters roll up", "hero": "the counters", "typed": "12 SECONDS"},
            {"id": nid + 2, "text": "Nobody watching knew what it meant yet.", "kind": "framing",
             "visual": "slow drift over the board", "hero": "the photo"},
        ]
        nid += 3
    L.save(p["narration"], n)


class Research(unittest.TestCase):
    def test_empty_research_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            r = research.check(proj)
            self.assertFalse(r.ok)
            self.assertTrue(any("no claims" in e for e in r.errors))

    def test_check_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            r = research.check(proj)
            self.assertTrue(r.ok, r.errors)
            self.assertTrue(any("C3" in w and "weak" in w for w in r.warnings))
            md = L.paths(proj)["research_md"].read_text()
            self.assertIn("**WEAK**", md)
            self.assertIn("https://www.nps.gov", md)

    def test_unknown_source_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            with self.assertRaises(SystemExit):
                quiet(research.add_claim, proj, "x", ["S99"])
            self.assertEqual(quiet(research.add_source, proj, url="https://www.nps.gov/wrbr/learn/historyculture/thefirstflight.htm"), "S1")
            p = L.paths(proj)
            c = L.load(p["claims"]); c["claims"].append({"id": "C1", "text": "dup", "sources": ["S9"]}); L.save(p["claims"], c)
            r = research.check(proj)
            self.assertFalse(r.ok)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            cli("research.py", "add-source", "--project", proj, "--url", "https://www.loc.gov/item/x", "--title", "X", "--type", "archive")
            cli("research.py", "add-claim", "--project", proj, "--text", "Wilbur wrote to the Smithsonian in 1899.", "--source", "S1")
            out = cli("research.py", "check", "--project", proj).stdout
            self.assertIn("1 supported", out)


class Outline(unittest.TestCase):
    def test_init_sizes_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp, minutes=20)
            add_research(proj)
            self.assertTrue(quiet(outline.init, proj))
            o = L.load(L.paths(proj)["outline"])
            self.assertEqual(len(o["sections"]), 18)
            self.assertEqual(o["acts"], 3)
            self.assertFalse(quiet(outline.init, proj))
            r = outline.check(proj)
            self.assertFalse(r.ok)                     # TODOs
            fill_outline(proj)
            r = outline.check(proj)
            self.assertTrue(r.ok, r.errors)
            self.assertIn("## Act 2", L.paths(proj)["outline_md"].read_text())

    def test_chronology_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            quiet(outline.init, proj)
            fill_outline(proj)
            p = L.paths(proj)
            o = L.load(p["outline"])
            chapters = [s for s in o["sections"] if s["kind"] == "chapter"]
            chapters[2]["period"] = "1850"
            o["sections"][3]["target_seconds"] += 120
            o["sections"][4]["claims"] = ["C42"]
            L.save(p["outline"], o)
            r = outline.check(proj)
            self.assertTrue(any("steps back" in w for w in r.warnings))
            self.assertTrue(any("add up to" in e for e in r.errors))
            self.assertTrue(any("C42" in e for e in r.errors))


class Narration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)
        add_research(self.proj)
        quiet(outline.init, self.proj)
        fill_outline(self.proj)
        quiet(narration.init, self.proj)
        fill_narration(self.proj)
        self.p = L.paths(self.proj)

    def tearDown(self):
        self.tmp.cleanup()

    def edit_first_line(self, **kw):
        n = L.load(self.p["narration"])
        n["sections"][1]["lines"][0].update(kw)
        L.save(self.p["narration"], n)
        return n["sections"][1]["lines"][0]["id"]

    def test_clean_script_passes(self):
        r = narration.check(self.proj)
        self.assertTrue(r.ok, r.errors)
        self.assertFalse([w for w in r.warnings if "UNSUPPORTED" in w or "no cited claim" in w])

    def test_number_not_in_claim(self):
        i = self.edit_first_line(text="It flew for 59 seconds over the sand.")
        r = narration.check(self.proj)
        self.assertTrue(any(f"line {i}" in w and "59" in w for w in r.warnings))

    def test_uncited_and_unknown(self):
        i = self.edit_first_line(claims=[])
        self.assertTrue(any(f"line {i}" in w and "UNSUPPORTED" in w for w in narration.check(self.proj).warnings))
        self.edit_first_line(claims=["C77"])
        self.assertFalse(narration.check(self.proj).ok)

    def test_unsupported_claim_is_an_error(self):
        c = L.load(self.p["claims"]); c["claims"].append({"id": "C9", "text": "It was a hoax.", "sources": []})
        L.save(self.p["claims"], c)
        self.edit_first_line(claims=["C9"], text="Some say it was a hoax.")
        r = narration.check(self.proj)
        self.assertFalse(r.ok)
        self.assertTrue(any("C9" in e for e in r.errors))

    def test_disputed_needs_hedge(self):
        c = L.load(self.p["claims"]); c["claims"][1]["disputed"] = True; L.save(self.p["claims"], c)
        i = self.edit_first_line(claims=["C2"], text="Daniels took the picture.")
        self.assertTrue(any(f"line {i}" in w and "disputed" in w for w in narration.check(self.proj).warnings))
        self.edit_first_line(claims=["C2"], text="Daniels, it is said, took the picture.")
        self.assertFalse(any(f"line {i}" in w and "disputed" in w for w in narration.check(self.proj).warnings))

    def test_todo_blocks(self):
        self.edit_first_line(text="TODO")
        self.assertFalse(narration.check(self.proj).ok)

    def test_spoken_fill(self):
        quiet(narration.fill_spoken, self.proj)
        n = L.load(self.p["narration"])
        self.assertEqual(n["sections"][0]["lines"][0]["spoken"], "On December seventeenth, nineteen oh three, a machine left the sand.")

    def test_export_feeds_the_film_tools(self):
        r = quiet(narration.export, self.proj)
        self.assertTrue(r.ok, r.errors)
        s = L.load(self.p["script_json"])
        self.assertEqual(s["generated_by"], "narration.py")
        self.assertTrue(all("spoken" in l and "hero" in l for t in s["takes"] for l in t["lines"]))
        self.assertTrue(any("nps.gov" in f for f in s["fact_notes"]))
        out = cli("make_beats.py", "--project", self.proj).stdout
        self.assertIn("0 warning(s)", out)

    def test_export_never_replaces_a_foreign_script(self):
        L.save(self.p["script_json"], {"title": "hand written", "takes": []})
        r = quiet(narration.export, self.proj)
        self.assertFalse(r.ok)
        self.assertEqual(L.load(self.p["script_json"])["title"], "hand written")
        self.assertTrue(quiet(narration.export, self.proj, force=True).ok)


class Storyboard(unittest.TestCase):
    def test_scenes_times_and_needs(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            add_research(proj)
            quiet(outline.init, proj); fill_outline(proj)
            quiet(narration.init, proj); fill_narration(proj)
            r = storyboard.build(proj)
            self.assertTrue(r.ok, r.errors)
            p = L.paths(proj)
            sb = L.load(p["storyboard"])
            starts = [s["start"] for s in sb["scenes"]]
            self.assertEqual(starts, sorted(starts))
            self.assertEqual(sb["timing"], "estimate")
            self.assertIn("establishing", sb["scenes"][0]["camera"])
            self.assertIn("final pull-back", sb["scenes"][-1]["camera"])
            self.assertEqual(sb["scenes"][0]["key_word"], "sand")
            needs = L.load(p["image_needs"])["images"]
            self.assertEqual(len(needs), 9)
            self.assertTrue(all(n["status"] == "needed" for n in needs))
            # with a real voice, its timing wins
            first = sb["scenes"][0]["line"]
            L.save(p["timing"], {"segments": [{"id": first, "start": 2.5, "duration": 3.25}]})
            storyboard.build(proj)
            sb = L.load(p["storyboard"])
            self.assertEqual((sb["scenes"][0]["start"], sb["scenes"][0]["duration"]), (2.5, 3.25))
            self.assertEqual(sb["timing"], "voice")


class Pipeline(unittest.TestCase):
    def test_end_to_end_with_gates_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp) / "doc"
            cli("docpipe.py", "new", proj, "--topic", "The first powered flight", "--minutes", "5")
            for d in ("00_topic", "01_research", "02_outline", "03_script", "04_scenes", "assets/photos", "audio/takes"):
                self.assertTrue((proj / d).is_dir(), d)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("[research] blocked", r.stdout)
            add_research(proj)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertIn("[outline] blocked", r.stdout)                    # skeleton written, TODOs left
            self.assertTrue(L.paths(proj)["outline"].exists())
            fill_outline(proj)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertIn("approve --project", r.stdout)
            r = cli("docpipe.py", "approve", "--project", proj, "script", check=False)
            self.assertNotEqual(r.returncode, 0)                            # not reached yet
            cli("docpipe.py", "approve", "--project", proj, "outline")
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertIn("[topic] up to date", r.stdout)
            self.assertIn("[outline] up to date", r.stdout)
            self.assertIn("[script] blocked", r.stdout)
            fill_narration(proj)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertIn("[script] passes its checks", r.stdout)
            cli("docpipe.py", "approve", "--project", proj, "script")
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes")
            self.assertIn("[scenes]", r.stdout)
            self.assertTrue(L.paths(proj)["storyboard"].exists())
            self.assertTrue(L.paths(proj)["script_json"].exists())
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes")
            for st in docpipe.NAMES[:docpipe.NAMES.index("scenes") + 1]:
                self.assertIn(f"[{st}] up to date", r.stdout)
            # editing the research reopens what depends on it, and lapses the approvals
            c = L.load(L.paths(proj)["claims"]); c["claims"][0]["notes"] = "rechecked"; L.save(L.paths(proj)["claims"], c)
            status = cli("docpipe.py", "status", "--project", proj).stdout
            self.assertRegex(status, r"research\s+out of date")
            self.assertRegex(status, r"outline\s+out of date")
            self.assertIn("planned", status)
            r = cli("docpipe.py", "run", "--project", proj, "--until", "scenes", check=False)
            self.assertIn("[outline] passes its checks", r.stdout)

    def test_new_refuses_a_used_folder_and_bad_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / "x"; d.mkdir(); (d / "keep.txt").write_text("mine")
            self.assertNotEqual(cli("docpipe.py", "new", d, "--topic", "t", check=False).returncode, 0)
            self.assertEqual((d / "keep.txt").read_text(), "mine")
            self.assertNotEqual(cli("docpipe.py", "new", pathlib.Path(tmp) / "y", "--topic", "t", "--minutes", "90",
                                    check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
