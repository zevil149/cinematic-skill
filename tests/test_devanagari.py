"""Tests for milestone 3.2: Devanagari rendering. HarfBuzz shaping, the bundled Noto Sans Devanagari
font, missing-glyph and shaping regressions, Hindi in BigText, Card, labels and captions, and
English rendering untouched.

The licence checks need nothing; the rest need skia-python, numpy, pillow and uharfbuzz (the CI
film job has them) and are skipped otherwise.
"""
import hashlib
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
FONTS = ROOT / "skills" / "cinematic-film" / "assets" / "fonts"
sys.path.insert(0, str(SCRIPTS))

try:
    import numpy as np
    import skia
    import uharfbuzz  # noqa: F401
    import engine as E
    import textshape as T
    HAVE = True
except Exception:                         # pragma: no cover
    HAVE = False

FONT_SHA256 = "14ec4af41f27482216d1c2229f417ff9b1425e1babb014e57d1d40d03229853e"
CONSONANTS = "कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह"
VOWELS = "अआइईउऊऋएऐओऔ"
SIGNS = "ािीुूृेैोौंःँ्"
NUKTA_FORMS = "क़ख़ग़ज़ड़ढ़फ़य़" + "क़ज़फ़"
DIGITS = "०१२३४५६७८९"
CONJUNCTS = ["क्ष", "त्र", "ज्ञ", "श्र", "द्ध", "द्व", "स्त", "स्त्री", "प्र", "क्र", "ट्र", "र्म", "र्य", "ष्ण", "ह्म", "न्द", "ङ्क"]


class LicencesAndIntegrity(unittest.TestCase):
    def test_bundled_font_and_licence(self):
        font = FONTS / "NotoSansDevanagari-VF.ttf"
        self.assertEqual(hashlib.sha256(font.read_bytes()).hexdigest(), FONT_SHA256)
        ofl = (FONTS / "OFL-NotoSansDevanagari.txt").read_text()
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", ofl)
        self.assertIn("The Noto Project Authors", ofl)
        readme = (FONTS / "README.md").read_text()
        self.assertIn(FONT_SHA256, readme)
        self.assertIn("SIL Open Font License 1.1", readme)
        self.assertIn("e123d230c160ebe949d731cc19017cdb354180d1", readme)
        self.assertIn("uharfbuzz", (ROOT / "requirements.txt").read_text())
        self.assertIn("*.ttf binary", (ROOT / ".gitattributes").read_text())


def res(fonts_dir=None):
    return E.Res(1.0, None, fonts_dir)


def ink(img):
    return int((img[..., :3].astype(int).sum(axis=2) < 600).sum())


def draw(fn, w=900, h=260):
    s = skia.Surface(w, h)
    with s as c:
        c.clear(skia.Color(255, 255, 255))
        fn(c)
    return s.makeImageSnapshot().toarray()


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and uharfbuzz")
class MissingGlyphs(unittest.TestCase):
    def test_no_empty_boxes_anywhere(self):
        r = res()
        corpus = [CONSONANTS, VOWELS, "".join("क" + s for s in SIGNS), NUKTA_FORMS, DIGITS + " । ॥", " ".join(CONJUNCTS),
                  "राइट बंधुओं का विमान बारह सेकंड तक उड़ा।", "सत्रह दिसंबर उन्नीस सौ तीन", "क्षत्रिय कृष्ण धर्म ज्ञान"]
        for role in ("cond", "label", "labelm", "serif", "mono", "hand"):
            for text in corpus:
                self.assertEqual(T.missing_glyphs(r, text, role), [], (role, text))

    def test_the_old_path_drew_empty_boxes(self):
        # what this milestone fixes: the role fonts have no Devanagari, so plain Skia drew glyph 0
        f = res().font("cond", 40)
        self.assertIn(0, list(f.textToGlyphs("कि")))

    def test_a_font_without_devanagari_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dejavu = next(iter(pathlib.Path("/usr/share/fonts").rglob("DejaVuSans.ttf")), None)
            if dejavu is None:
                self.skipTest("no DejaVu font to test with")
            shutil.copy(dejavu, pathlib.Path(tmp) / "deva.ttf")       # a project font that cannot show Hindi
            self.assertTrue(T.missing_glyphs(res(tmp), "कि", "label"))


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and uharfbuzz")
class Shaping(unittest.TestCase):
    def glyphs(self, text, role="labelm"):
        return T.shape(res(), text, 100, role).glyphs

    def test_pre_base_vowel_sign_is_drawn_first(self):
        g = self.glyphs("कि")
        self.assertEqual(len(g), 2)
        matra, ka = g
        self.assertLess(matra[2], ka[2])                                   # ि sits left of क
        self.assertEqual(ka[1], self.glyphs("क")[0][1])
        self.assertEqual((matra[4], ka[4]), (0, 0))                        # one cluster

    def test_conjuncts_join(self):
        self.assertEqual(len(self.glyphs("क्ष")), 1)                         # three code points, one glyph
        self.assertEqual(len(self.glyphs("ज्ञ")), 1)
        self.assertLess(len(self.glyphs("स्त्री")), len("स्त्री"))

    def test_half_forms(self):
        half_sa = self.glyphs("स्त")[0][1]
        self.assertNotEqual(half_sa, self.glyphs("स")[0][1])               # स् takes its half form before त

    def test_reph(self):
        g = self.glyphs("र्म")
        self.assertEqual(len(g), 2)
        ra, ma = self.glyphs("र")[0][1], self.glyphs("म")[0][1]
        ids = [x[1] for x in g]
        self.assertIn(ma, ids)
        self.assertNotIn(ra, ids)                                          # र becomes the reph mark above म

    def test_nukta_forms_agree(self):
        self.assertEqual([x[1] for x in self.glyphs("फ़")], [x[1] for x in self.glyphs("फ़")])

    def test_below_base_vowel_stays_with_its_letter(self):
        base, sign = self.glyphs("कु")
        adv = T.shape(res(), "क", 100, "labelm").width
        self.assertGreaterEqual(sign[2], base[2] - 1)
        self.assertLess(sign[2], base[2] + adv)                            # ु is under क, not after it

    def test_shaped_is_not_character_by_character(self):
        naive = list(skia.Font(T.DevaFonts().for_role("labelm")[0], 100).textToGlyphs("क्षत्रिय"))
        self.assertNotEqual([x[1] for x in self.glyphs("क्षत्रिय")], naive)

    def test_rendered_conjunct_differs_from_its_letters_side_by_side(self):
        r = res()
        shaped = draw(lambda c: E.draw_text(c, r, "क्ष", 40, 180, 160, "labelm", (0, 0, 0)))
        f = skia.Font(T.DevaFonts().for_role("labelm")[0], 160)

        def naive(c):
            x = 40
            for ch in "क्ष":
                c.drawString(ch, x, 180, f, skia.Paint(Color=skia.ColorBLACK)); x += f.measureText(ch)
        self.assertGreater(np.abs(shaped.astype(int) - draw(naive).astype(int)).mean(), 1.0)


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and uharfbuzz")
class Drawing(unittest.TestCase):
    def test_width_tracking_reveal_and_mixed_scripts(self):
        r = res()
        w0 = E.text_width(r, "राइट बंधु", 100, "label")
        self.assertGreater(w0, 200)
        self.assertGreater(E.text_width(r, "राइट बंधु", 100, "label", 0.1), w0)
        full = ink(draw(lambda c: E.draw_text(c, r, "राइट बंधु", 20, 180, 100, "label", (0, 0, 0))))
        part = ink(draw(lambda c: E.draw_text(c, r, "राइट बंधु", 20, 180, 100, "label", (0, 0, 0), reveal=4)))
        self.assertTrue(0 < part < full)
        mixed = T.shape(r, "NASA ने", 100, "label").glyphs
        self.assertIsNot(mixed[0][0].getTypeface(), mixed[-1][0].getTypeface())   # NASA keeps the Latin font
        self.assertEqual(T.missing_glyphs(r, "NASA ने 1903 में", "label"), [])

    def test_center_alignment_uses_the_shaped_width(self):
        r = res()
        img = draw(lambda c: E.draw_text(c, r, "क्षत्रिय", 450, 180, 100, "label", (0, 0, 0), align="center"), 900, 260)
        cols = np.where((img[..., :3].astype(int).sum(axis=2) < 600).any(axis=0))[0]
        self.assertLess(abs((cols.min() + cols.max()) / 2 - 450), 25)

    def test_project_font_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(FONTS / "NotoSansDevanagari-VF.ttf", pathlib.Path(tmp) / "deva.ttf")
            self.assertEqual(T.font_path(tmp), pathlib.Path(tmp) / "deva.ttf")
            self.assertEqual(T.font_path(None), T.BUNDLED)

    def test_missing_uharfbuzz_is_a_clear_error(self):
        saved = sys.modules.get("uharfbuzz")
        sys.modules["uharfbuzz"] = None
        try:
            with self.assertRaises(SystemExit) as e:
                T.DevaFonts()
            self.assertIn("pip install uharfbuzz", str(e.exception))
        finally:
            sys.modules["uharfbuzz"] = saved

    def test_english_never_takes_the_shaped_path(self):
        for text in ("DECEMBER 17, 1903", "Twelve seconds.", "café naïve", "12 SECONDS · 120 FEET", ""):
            self.assertFalse(T.needs_shaping(text))
        r = res()
        before = draw(lambda c: E.draw_text(c, r, "TWELVE SECONDS", 20, 180, 100, "cond", (0, 0, 0), track=0.05))
        orig = T.shape
        T.shape = lambda *a, **k: (_ for _ in ()).throw(AssertionError("English must not be shaped"))
        try:
            after = draw(lambda c: E.draw_text(c, r, "TWELVE SECONDS", 20, 180, 100, "cond", (0, 0, 0), track=0.05))
            self.assertEqual(E.text_width(r, "Twelve", 50, "serif"), sum(r.font("serif", 50).getWidths(r.font("serif", 50).textToGlyphs("Twelve"))))
        finally:
            T.shape = orig
        self.assertTrue(np.array_equal(before, after))


@unittest.skipUnless(HAVE, "needs skia-python, numpy, pillow and uharfbuzz")
class HindiInTheFilm(unittest.TestCase):
    def test_bigtext_card_label_and_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp) / "p"
            (proj / "audio").mkdir(parents=True); (proj / "assets" / "prep").mkdir(parents=True)
            (proj / "audio" / "timing.json").write_text(json.dumps({"total_duration": 4, "segments": [
                {"id": 1, "start": 0.2, "end": 3, "duration": 2.8, "vo": "राइट बंधुओं का विमान बारह सेकंड तक उड़ा"}]}))
            subprocess.run([sys.executable, str(SCRIPTS / "prep_assets.py"), "--project", str(proj)], capture_output=True, check=True)
            doc = E.Doc(proj)

            def frame(items):
                film = E.Film(4, look="charcoal"); film.fade_in = 0; film.look["grain"] = 0
                for it in items:
                    film.add(it)
                film.cam(0, 0, 0, 0.5); film.cam(4, 0, 0, 0.5)
                return E.Renderer(film, 640, 360, doc).frame(60).astype(int)
            empty = frame([])
            for item in (E.BigText("सत्रह दिसंबर १९०३", 0, 0, 500, 0.0),
                         E.BigText("क्षत्रिय स्त्री धर्म", 0, 0, 400, 0.0, font="label", grunge=False, type_on=0.5),
                         E.Card(0, 0, 3600, 1600, 0.0, title="पहली उड़ान", lines=["बारह सेकंड, एक सौ बीस फ़ुट", "NASA ने इसे याद रखा"])):
                self.assertGreater(np.abs(frame([item]) - empty).mean(), 1.0, type(item).__name__)
            # a stamp is dark red ink on a dark board: measure it against the same stamp in English
            hi_stamp = np.abs(frame([E.Stamp("असफल", 0, 0, size=400, t_in=0.0)]) - empty).mean()
            en_stamp = np.abs(frame([E.Stamp("FAILED", 0, 0, size=400, t_in=0.0)]) - empty).mean()
            self.assertGreater(hi_stamp, 0.6 * en_stamp)
            from captions import Captions, words_with_times
            seg = {"id": 1, "start": 0.0, "end": 4.0, "caption": "राइट बंधुओं का विमान बारह सेकंड तक उड़ा।"}
            times = [t for _, t in words_with_times(seg)]
            self.assertEqual(times, sorted(times)); self.assertGreater(len(set(round(b - a, 3) for a, b in zip(times, times[1:]))), 1)
            for style in ("highlighter", "clean", "paper", "redbar"):
                layer = Captions(style, 640, 360, {"segments": [seg]}).layer(2.0)
                self.assertIsNotNone(layer, style)
                self.assertGreater(int((layer[..., 3] > 0).sum()), 500, style)


if __name__ == "__main__":
    unittest.main()
