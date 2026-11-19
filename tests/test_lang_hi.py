"""Tests for milestone 3.1: the Hindi language foundation. Offline; standard library only, except
the camera word-timing test (it imports the engine, which needs skia-python).
"""
import os
import pathlib
import re
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
import doclib as L  # noqa: E402
import editions  # noqa: E402
import lang  # noqa: E402
import narration  # noqa: E402
import storyboard  # noqa: E402
from lang import hi as H  # noqa: E402
from test_docpipe import cli, quiet  # noqa: E402
from test_editions import production, write_english, write_hindi  # noqa: E402

try:
    import skia  # noqa: F401
    HAVE_SKIA = True
except Exception:                       # pragma: no cover
    HAVE_SKIA = False

hi = lang.get("hi")
en = lang.get("en")


class NumberWords(unittest.TestCase):
    def test_every_number_below_a_hundred_has_its_own_word(self):
        self.assertEqual(len(set(H.WORDS)), 100)
        spot = {0: "शून्य", 5: "पाँच", 6: "छह", 9: "नौ", 11: "ग्यारह", 15: "पंद्रह", 19: "उन्नीस", 21: "इक्कीस", 29: "उनतीस",
                33: "तैंतीस", 39: "उनतालीस", 44: "चवालीस", 49: "उनचास", 51: "इक्यावन", 59: "उनसठ", 67: "सड़सठ",
                69: "उनहत्तर", 79: "उन्यासी", 89: "नवासी", 90: "नब्बे", 99: "निन्यानवे"}
        for n, w in spot.items():
            self.assertEqual(H.int_words(n), w, n)

    def test_indian_scale(self):
        cases = {100: "एक सौ", 101: "एक सौ एक", 120: "एक सौ बीस", 999: "नौ सौ निन्यानवे", 1000: "एक हज़ार",
                 1001: "एक हज़ार एक", 1200: "एक हज़ार दो सौ", 50000: "पचास हज़ार", 100000: "एक लाख",
                 120000: "एक लाख बीस हज़ार", 352000: "तीन लाख बावन हज़ार", 1000000: "दस लाख",
                 10000000: "एक करोड़", 25000000: "दो करोड़ पचास लाख", 1000000000: "एक अरब"}
        for n, w in cases.items():
            self.assertEqual(H.int_words(n), w, n)

    def test_round_trip_words_to_values(self):
        for n in list(range(0, 2001)) + list(range(2001, 300000, 97)) + [10 ** 7, 3 * 10 ** 7 + 45, 10 ** 9 + 7]:
            self.assertEqual(H.numbers_in(H.int_words(n)), {float(n)} if n > 1 else set(), n)

    def test_years(self):
        cases = {1100: "ग्यारह सौ", 1857: "अठारह सौ सत्तावन", 1900: "उन्नीस सौ", 1903: "उन्नीस सौ तीन",
                 1947: "उन्नीस सौ सैंतालीस", 1999: "उन्नीस सौ निन्यानवे", 2000: "दो हज़ार", 2003: "दो हज़ार तीन",
                 2024: "दो हज़ार चौबीस"}
        for y, w in cases.items():
            self.assertEqual(H.year_words(y), w, y)
        for y in range(1100, 2100):
            self.assertEqual(H.numbers_in(H.year_words(y)), {float(y)}, y)


class SpokenText(unittest.TestCase):
    def test_dates_money_percent_decimals_ordinals_digits(self):
        cases = {
            "17 दिसंबर 1903 को": "सत्रह दिसंबर उन्नीस सौ तीन को",
            "15 अगस्त 1947": "पंद्रह अगस्त उन्नीस सौ सैंतालीस",
            "₹1,00,000": "एक लाख रुपये",
            "₹1": "एक रुपया",
            "₹2 करोड़": "दो करोड़ रुपये",
            "$50,000": "पचास हज़ार डॉलर",
            "€3.5": "तीन दशमलव पाँच यूरो",
            "45% लोग": "पैंतालीस प्रतिशत लोग",
            "12.5%": "बारह दशमलव पाँच प्रतिशत",
            "3.14": "तीन दशमलव एक चार",
            "21वीं सदी": "इक्कीसवीं सदी",
            "1वीं बार": "पहली बार",
            "4वें दिन": "चौथे दिन",
            "17वाँ": "सत्रहवाँ",
            "१९०३ में": "उन्नीस सौ तीन में",
            "१२ सेकंड": "बारह सेकंड",
            "12 सेकंड, 120 फ़ुट": "बारह सेकंड, एक सौ बीस फ़ुट",
            "3,52,000 सैनिक": "तीन लाख बावन हज़ार सैनिक",
            "352,000 सैनिक": "तीन लाख बावन हज़ार सैनिक",
            "1500 सैनिक": "पंद्रह सौ सैनिक",
        }
        for text, want in cases.items():
            self.assertEqual(hi.spoken_text(text), want, text)

    def test_warnings(self):
        self.assertEqual(hi.spoken_warnings(hi.spoken_text("17 दिसंबर 1903 को")), [])
        self.assertTrue(any("digits" in w for w in hi.spoken_warnings("1903 में")))
        self.assertTrue(any("Latin words ['NASA']" in w for w in hi.spoken_warnings("NASA का मिशन")))
        self.assertTrue(any("symbols" in w for w in hi.spoken_warnings("रेत & हवा")))

    def test_rules_stay_with_their_language(self):
        self.assertEqual(en.spoken_text("In 1903, $50,000"), L.spoken_text("In 1903, $50,000"))
        self.assertEqual(en.numbers_in("बारह सेकंड"), set())            # English never reads Hindi words
        self.assertEqual(hi.numbers_in("twelve seconds"), set())        # and Hindi never reads English ones
        self.assertNotIn("nineteen", hi.spoken_text("1903 में"))


class ReadingNumbers(unittest.TestCase):
    def test_words_fractions_and_variants(self):
        cases = {"उन्नीस सौ तीन": {1903}, "दो हज़ार चौबीस": {2024}, "एक सौ बीस फ़ुट": {120}, "बारह सेकंड": {12},
                 "साढ़े तीन सौ": {350}, "डेढ़ सौ": {150}, "ढाई हज़ार": {2500}, "सवा दो": {2.25}, "पौने चार": {3.75},
                 "तीन दशमलव पाँच": {3.5}, "सत्रहवीं सदी": {17}, "पांच और पाँच": {5}, "छः लोग": {6},
                 "चौवालीस": {44}, "बीस तीस": {20, 30}, "एक लाख बीस हज़ार": {120000}, "१२ सेकंड": {12},
                 "1,00,000": {100000}, "100,000": {100000}, "उसने 12 सेकंड में 120 फ़ुट": {12, 120}}
        for text, want in cases.items():
            self.assertEqual(H.numbers_in(text), {float(v) for v in want}, text)

    def test_ek_as_an_article_is_not_a_number(self):
        self.assertEqual(H.numbers_in("एक आदमी ने एक विमान बनाया"), set())
        self.assertEqual(H.numbers_in("एक सौ"), {100.0})


class Timing(unittest.TestCase):
    def test_syllables(self):
        self.assertEqual(H.aksharas("राइट"), 3)
        self.assertEqual(H.aksharas("क्षमा"), 2)                       # क्ष is one syllable
        self.assertEqual(H.aksharas("उड़ा"), 2)                         # nukta letters count once
        self.assertEqual(H.aksharas("बंधुओं"), 3)

    def test_never_zero_and_paced(self):
        for line in ("राइट बंधुओं का विमान बारह सेकंड तक उड़ा।", "1903।", "१२", "NASA", "हाँ।"):
            self.assertGreater(hi.est_seconds(line), 0.25, line)
        self.assertEqual(hi.est_seconds(""), 0.0)
        self.assertGreater(hi.est_seconds("1903 में"), hi.est_seconds("में"))     # digits are timed as their words
        line = "राइट बंधुओं का विमान बारह सेकंड तक उड़ा"
        slow, fast = hi.configure(wpm=130).est_seconds(line), hi.configure(wpm=140).est_seconds(line)
        self.assertAlmostEqual(slow / fast, 140 / 130, places=6)
        self.assertEqual(en.configure(wpm=150).est_seconds("Twelve seconds."), L.est_seconds("Twelve seconds."))
        self.assertAlmostEqual(en.configure(wpm=145).est_seconds("Twelve seconds."), L.est_seconds("Twelve seconds.") * 150 / 145)

    def test_key_words(self):
        self.assertEqual(hi.key_word("राइट बंधुओं का विमान बारह सेकंड तक उड़ा।"), "उड़ा")
        self.assertEqual(hi.key_word("यह किताब उनके लिए थी।"), "किताब")      # pronouns and postpositions are skipped
        self.assertEqual(hi.key_word("किटी हॉक की रेत पर"), "रेत")
        self.assertEqual(hi.key_word("यह उनके लिए था।"), "था")                 # only function words: the last one
        self.assertEqual(hi.key_word(""), "")


class Lexicon(unittest.TestCase):
    def test_apply(self):
        terms = {"Kitty Hawk": {"spoken": "किटी हॉक"}, "Kitty": {"spoken": "किटी"}, "Wright": {"spoken": "राइट"},
                 "NASA": {"spoken": "नासा"}}
        lg = hi.configure(lexicon={"terms": terms})
        self.assertEqual(lg.spoken_text("Wright बंधु Kitty Hawk पहुँचे, nasa ने 1903 में"),
                         "राइट बंधु किटी हॉक पहुँचे, नासा ने उन्नीस सौ तीन में")
        self.assertEqual(lg.spoken_text("Wrightson"), "Wrightson")          # whole words only
        self.assertEqual(hi.spoken_text("Wright"), "Wright")                # the registered language has no lexicon
        self.assertEqual(en.configure(lexicon={"terms": {}}).spoken_text("In 1903"), L.spoken_text("In 1903"))

    def test_edition_lexicon_checks_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            r = cli("editions.py", "lexicon", "--project", proj, "hi", "--add", "Kitty Hawk", "किटी हॉक", "--allow", "NASA")
            self.assertIn("Kitty Hawk -> किटी हॉक", r.stdout)
            cli("editions.py", "lexicon", "--project", proj, "hi", "--add", "Wright", "राइट")
            lx = L.load(editions.edition_dir(proj, "hi") / "lexicon.json")
            self.assertEqual(set(lx["terms"]), {"Kitty Hawk", "Wright"})                 # earlier entries kept
            self.assertEqual(lx["allow"], ["NASA"])
            r = cli("editions.py", "lexicon", "--project", proj, "hi", "--add", "Dayton", "Dayton", check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("'Dayton' is spoken as 'Dayton'", r.stdout)                    # a Hindi voice needs Devanagari

    def test_hindi_spoken_text_uses_the_lexicon_and_keeps_the_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi_ed = write_hindi(proj)
            L.save(hi_ed / "lexicon.json", {"lang": "hi", "terms": {"NASA": {"spoken": "नासा"}}, "allow": ["NASA"]})
            n = L.load(L.paths(hi_ed)["narration"])
            n["sections"][0]["lines"][0]["text"] = "NASA ने 17 दिसंबर 1903 का दिन याद रखा।"
            n["sections"][0]["lines"][0]["kind"] = "framing"
            L.save(L.paths(hi_ed)["narration"], n)
            quiet(narration.fill_spoken, hi_ed)
            line = L.load(L.paths(hi_ed)["narration"])["sections"][0]["lines"][0]
            self.assertEqual(line["text"], "NASA ने 17 दिसंबर 1903 का दिन याद रखा।")
            self.assertEqual(line["spoken"], "नासा ने सत्रह दिसंबर उन्नीस सौ तीन का दिन याद रखा।")
            r = narration.check(hi_ed)
            self.assertTrue(r.ok, r.errors)


class FactCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = production(self.tmp.name)
        write_english(self.proj)
        beats.build(self.proj, log=lambda *a: None)
        self.hi = write_hindi(self.proj)

    def tearDown(self):
        self.tmp.cleanup()

    def set_line(self, text, claims=("C1",)):
        n = L.load(L.paths(self.hi)["narration"])
        line = n["sections"][1]["lines"][0]
        line.update(text=text, claims=list(claims)); line.pop("kind", None)
        L.save(L.paths(self.hi)["narration"], n)
        return line["id"]

    def warnings_for(self, i):
        return [w for w in narration.check(self.hi).warnings if f"line {i}:" in w and "no cited claim contains" in w]

    def test_hindi_numbers_match_the_english_claim(self):
        # C1: "On December 17, 1903 the first flight lasted 12 seconds and covered 120 feet."
        for text in ("उड़ान बारह सेकंड चली।", "उड़ान १२ सेकंड चली, एक सौ बीस फ़ुट।", "सत्रह दिसंबर उन्नीस सौ तीन।", "17 दिसंबर 1903।"):
            self.assertEqual(self.warnings_for(self.set_line(text)), [], text)

    def test_a_wrong_number_is_caught_in_words_or_digits(self):
        for text, bad in (("उड़ान उनसठ सेकंड चली।", "59"), ("उड़ान 59 सेकंड चली।", "59"), ("उड़ान साढ़े बारह सेकंड चली।", "12.5")):
            w = self.warnings_for(self.set_line(text))
            self.assertTrue(w and bad in w[0], (text, w))

    def test_a_claim_may_carry_hindi_words(self):
        c = L.load(L.paths(self.proj)["claims"])
        c["claims"].append({"id": "C9", "text": "The brothers built the machine.", "text_hi": "दोनों भाइयों ने तीन साल लगाए।",
                            "sources": ["S1"]})
        L.save(L.paths(self.proj)["claims"], c)
        self.assertEqual(self.warnings_for(self.set_line("इसमें तीन साल लगे।", ["C9"])), [])


class HindiEditionTiming(unittest.TestCase):
    def test_storyboard_and_beat_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi_ed = write_hindi(proj)
            quiet(narration.fill_spoken, hi_ed)
            self.assertTrue(quiet(narration.export, hi_ed).ok)
            r = storyboard.build(hi_ed)
            self.assertTrue(r.ok, r.errors)
            sc = L.load(L.paths(hi_ed)["storyboard"])["scenes"]
            self.assertTrue(all(s["duration"] > 0.25 for s in sc))
            self.assertTrue(all(s["key_word"] and not re.search(r"[A-Za-z]", s["key_word"]) for s in sc))
            starts = [s["start"] for s in sc]
            self.assertEqual(starts, sorted(starts)); self.assertEqual(len(set(starts)), len(starts))
            out = cli("make_beats.py", "--project", hi_ed).stdout
            md = (hi_ed / "beats.md").read_text()
            self.assertNotIn("| 0.0s |", md)
            self.assertIn("beats", out)
            # pace: a slower Hindi edition takes longer
            ed = L.load(hi_ed / "edition.json"); total_135 = sc[-1]["end"]
            ed["wpm"] = 120; L.save(hi_ed / "edition.json", ed)
            storyboard.build(hi_ed)
            self.assertGreater(L.load(L.paths(hi_ed)["storyboard"])["scenes"][-1]["end"], total_135)


@unittest.skipUnless(HAVE_SKIA, "the engine needs skia-python")
class CameraWordTiming(unittest.TestCase):
    def test_hindi_word_times(self):
        import engine
        doc = engine.Doc.__new__(engine.Doc)
        vo = "राइट बंधुओं का विमान बारह सेकंड तक उड़ा"
        doc.seg = {1: {"start": 10.0, "end": 14.0, "vo": vo}, 2: {"start": 20.0, "end": 22.0, "vo": "the first flight lasted twelve seconds"}}
        t_first, t_mid, t_last = doc.W(1, "राइट"), doc.W(1, "बारह"), doc.W(1, "उड़ा")
        self.assertAlmostEqual(t_first, 10.04, places=3)
        self.assertTrue(10.04 < t_mid < t_last < 14.0)
        self.assertAlmostEqual(t_mid, 10.0 + 4.0 * H.aksharas("राइट बंधुओं का विमान ") / H.aksharas(vo) + 0.04, places=6)
        with self.assertRaises(ValueError):
            doc.W(1, "हवा")
        letters = len("thefirstflightlasted")
        self.assertAlmostEqual(doc.W(2, "twelve"), 20.0 + 2.0 * letters / len("thefirstflightlastedtwelveseconds") + 0.04)


if __name__ == "__main__":
    unittest.main()
