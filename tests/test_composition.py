"""Tests for milestone 6.3: composition and typography fidelity.

  * a card's text is fitted: a long title wraps onto two balanced lines, then shrinks only if it
    must (never below CARD_FIT_MIN); long lines shrink; a crowded card scales its block; text that
    fits is set exactly as before; Hindi is measured shaped
  * each line's shot frames its whole hero (visuals and typed words, the parallax drift included)
    inside the safe area clear of the captions, through the push to the key word, and leaves the
    earlier lines' items out of frame instead of cutting them at the edge
  * the resolved fonts key the look review and the act renders; QC warns when a role the film uses
    falls back to the system default; QC reports still frames of bare board

Offline. Needs skia-python and numpy (ffmpeg for the fixture's tone).
"""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402

try:
    import numpy  # noqa: F401
    import skia  # noqa: F401
    import engine as E
    import scenekit as K
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False


def room(card):
    return card.w - 2 * card.w * 0.08


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class CardText(unittest.TestCase):
    def setUp(self):
        self.res = E.Res(0.5)

    def widths(self, card):
        return [(t, E.text_width(self.res, t, size, font, 0.0), size) for t, x, y, size, font, _ in card.layout(self.res)]

    def test_text_that_fits_is_set_as_before(self):
        c = E.Card(0, 0, 1600, 900, 0.0, title="CARD", lines=["one", "two"])
        lay = c.layout(self.res)
        pad, ts, bs = 1600 * 0.08, 900 * 0.16, 900 * 0.085
        y = -450 + pad + ts * 0.85
        self.assertEqual(lay[0][:4], ("CARD", -800 + pad, y, ts))
        y += ts * 0.55
        for (text, x, yy, size, font, kind), want in zip(lay[1:], ("one", "two")):
            y += bs * 1.45
            self.assertEqual((text, yy, size, font, kind), (want, y, bs, "labelm", "line"))

    def test_a_long_title_wraps_then_shrinks_only_if_it_must(self):
        c = E.Card(0, 0, 2700, 1650, 0.0, title="FIRST FLIGHT PHOTOGRAPH", title_size=170)
        self.assertGreater(E.text_width(self.res, c.title, 170, "label", 0.0), room(c))            # the audit's overflowing title
        got = self.widths(c)
        self.assertEqual([t for t, _, _ in got], ["FIRST FLIGHT", "PHOTOGRAPH"])                 # balanced break
        self.assertTrue(all(w <= room(c) and size == 170 for _, w, size in got), got)           # fits at full size
        c = E.Card(0, 0, 2700, 1650, 0.0, title="PHOTOGRAPHERS ARRIVED")              # its longer word needs about 85%
        got = self.widths(c)
        self.assertTrue(all(w <= room(c) * 1.001 for _, w, _ in got), got)
        self.assertLess(got[0][2], c.ts)                                                          # made smaller, as little as needed
        c = E.Card(0, 0, 2700, 1650, 0.0, title="ATITLEOFONEWORDFARTOOLONGFORANYCARDATALL")
        (_, w, size), = self.widths(c)
        self.assertAlmostEqual(size, c.ts * E.CARD_FIT_MIN)                                      # the floor: QC reports the rest
        self.assertGreater(w, room(c))

    def test_long_lines_and_crowded_cards(self):
        c = E.Card(0, 0, 2700, 1650, 0.0, title="T", lines=["a body line that is much too long to sit on this card at all"])
        (_, _, _), (_, w, size) = self.widths(c)
        self.assertLessEqual(w, room(c) * 1.001); self.assertLess(size, c.bs)
        c = E.Card(0, 0, 2700, 1650, 0.0, title="TITLE", lines=[f"line {i}" for i in range(8)])
        lay = c.layout(self.res)
        self.assertLessEqual(lay[-1][2] + lay[-1][3] * 0.3, c.h / 2 + 1e-6)                      # the block is scaled to fit

    def test_hindi_titles_are_fitted_by_their_shaped_width(self):
        c = E.Card(0, 0, 2700, 1650, 0.0, title="पहली संचालित उड़ान की ऐतिहासिक तस्वीर और उसका अर्थ", title_size=170)
        self.assertGreater(E.text_width(self.res, c.title, 170, "label", 0.0), room(c))
        got = self.widths(c)
        self.assertEqual(len(got), 2)
        self.assertTrue(all(w <= room(c) * 1.001 for _, w, _ in got), got)


def frame(film, t):
    cx, cy, z, _ = film.camera(t)
    return cx - 1920 / z, cy - 1080 / z, cx + 1920 / z, cy + 1080 / z, z


def within_safe(box, f, slack=0.03):
    x0, y0, x1, y1, z = f
    w, h = x1 - x0, y1 - y0
    l, t, r, b = K.SAFE
    return (box[0] >= x0 + (l - slack) * w and box[2] <= x1 - (r - slack) * w and
            box[1] >= y0 + (t - slack) * h and box[3] <= y1 - (b - slack) * h)


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Framing(unittest.TestCase):
    def test_frame_on_rules(self):
        a, b = (-1350, -825, 1350, 825), (-1080, -2400, 1080, -2040)
        x, y, z = K.frame_on([a, b])
        fw, fh = 3840 / (z * K.PUSH), 2160 / (z * K.PUSH)
        self.assertLessEqual(2700, fw * (1 - 0.2) + 1); self.assertLessEqual(3225, fh * (1 - 0.28) + 1)   # whole in the push
        self.assertEqual(K.frame_on([a], 0.9)[2], 0.9)                                          # a scene's own zoom is kept
        self.assertIsNone(K.frame_on([None]))
        # an earlier card the frame would cut: left out, by a closer centred shot or a move
        hero = (1000, -300, 3000, 100)
        nb = (-3300, -800, -500, 800)
        x, y, z = K.frame_on([hero], avoid=[nb])
        fr = (x - 1920 / z, y - 1080 / z, x + 1920 / z, y + 1080 / z)
        self.assertFalse(K._cut(nb, fr)); self.assertTrue(within_safe(hero, (*fr, z)))
        # a parallax plane's drift is allowed for
        x, y, z = K.frame_on([b], planes=[(0.0, -2220.0, 1.08)])
        dy = (y - (-2220.0)) * (1 - 1.08)
        self.assertTrue(within_safe((b[0], b[1] + dy, b[2], b[3] + dy), (x - 1920 / z, y - 1080 / z, x + 1920 / z, y + 1080 / z, z)))

    def test_a_built_act_frames_every_hero_and_cuts_no_neighbour(self):
        import finish_fixture as F
        from engine import Doc
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp, acts=1)
            card = {"need": "I1", "what": "First flight photograph", "status": "fallback", "media": "image", "kind": "photo"}
            table = [{"line": 1, "section": "s1", "typed": "DECEMBER 17, 1903", "key_word": "engine", "visuals": [card]},
                     {"line": 2, "section": "s1", "typed": "12 SECONDS", "key_word": "frame", "visuals": []},
                     {"line": 3, "section": "s1", "typed": "", "visuals": [dict(card, need="I2")]},
                     {"line": 4, "section": "s2", "typed": "120 FEET", "visuals": [dict(card, need="I3")]}]
            doc = Doc(proj)
            film = K.build_act(doc, table, look="wall")
            heroes = {}
            for it in film.items:
                inner = it.item if isinstance(it, E.Parallax) else it
                if isinstance(inner, (E.Card, E.BigText)):
                    heroes.setdefault(round(inner.t_in), []).append(it)
            segs = {s["id"]: s for s in L.load(proj / "audio" / "timing.json")["segments"]}
            for n in (1, 2, 3, 4):
                s = segs[n]
                t = s["end"] - 0.25                                                            # settled, after the push, still on the line
                f = frame(film, t)
                mine = [it for it in film.items if (it.item if isinstance(it, E.Parallax) else it).t_in >= s["start"] - 0.2
                        and (it.item if isinstance(it, E.Parallax) else it).t_in < s["end"]
                        and isinstance(it.item if isinstance(it, E.Parallax) else it, (E.Card, E.BigText))]
                for it in mine:
                    bx = K.item_box(doc, it)
                    pl = K.parallax_of(it)
                    if pl:
                        cx, cy = film.camera(t)[:2]
                        dx, dy = (cx - pl[0]) * (1 - pl[2]), (cy - pl[1]) * (1 - pl[2])
                        bx = (bx[0] + dx, bx[1] + dy, bx[2] + dx, bx[3] + dy)
                    self.assertTrue(within_safe(bx, f), (n, getattr(it, "text", None), bx, f))
                earlier = [it for it in film.items if isinstance(it.item if isinstance(it, E.Parallax) else it, (E.Card, E.BigText))
                           and (it.item if isinstance(it, E.Parallax) else it).t_in < s["start"] - 0.2]
                for it in earlier:
                    self.assertFalse(K._cut(K.item_box(doc, it), f[:4]), (n, "cuts an earlier item at the frame edge"))


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Fonts(unittest.TestCase):
    def test_project_fonts_are_pinned_into_review_and_render_keys(self):
        import finish
        import finish_fixture as F
        import review
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp, acts=1)
            p = finish.fp(proj)
            acts = finish.acts_of(p, L.load(p["timing"])["total_duration"])
            n, scene, s, e, a, b = acts[0]
            k0, r0 = finish.act_key(p, scene, a, b, "160x90", 18), review.fingerprint(proj)
            fonts = proj / "fonts"; fonts.mkdir()
            shutil.copyfile(SCRIPTS.parent / "assets" / "fonts" / "NotoSansDevanagari-VF.ttf", fonts / "cond.ttf")
            ident = E.font_identity(fonts)
            self.assertTrue(ident["cond"].startswith("cond.ttf sha256:"), ident)
            k1, r1 = finish.act_key(p, scene, a, b, "160x90", 18), review.fingerprint(proj)
            self.assertNotEqual(k0, k1); self.assertNotEqual(r0, r1)                           # a font change lapses the look
            self.assertEqual(r1, review.fingerprint(proj))                                     # and is stable

    def test_qc_warns_about_fallback_fonts_and_empty_holds(self):
        import finish
        import finish_fixture as F
        import layoutcheck as LC
        import qc
        import subtitles
        q = dict(log=lambda *a: None)
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp, acts=1)
            assert subtitles.build(proj, **q).ok and finish.render_acts(proj, "160x90", 2, **q).ok and finish.join(proj, **q).ok
            L.save(proj / "captions.json", {"enabled": False}); finish.captions(proj, **q)
            real = E.resolve_typeface
            fake = lambda role, d=None: (real(role, d)[0], "system default (Fake): install one of ['X']") if role == "cond" else real(role, d)  # noqa: E731
            with mock.patch.object(E, "resolve_typeface", side_effect=fake):
                r = qc.build(proj, **q)
            self.assertTrue(r.ok, r.errors)
            self.assertTrue(any(w.startswith("fonts: cond: system default (Fake)") for w in r.warnings), r.warnings)
            (proj / "fonts").mkdir()
            shutil.copyfile(SCRIPTS.parent / "assets" / "fonts" / "NotoSansDevanagari-VF.ttf", proj / "fonts" / "cond.ttf")
            r = qc.build(proj, **q)
            self.assertFalse(any(w.startswith("fonts:") for w in r.warnings), r.warnings)
        # a camera parked on bare board, away from everything
        f = E.Film(10, look="wall")
        f.add(E.Card(0, 0, 2700, 1650, 0.0, title="HERE"))
        f.cam(0, 0, 0, 0.6); f.cam(2.0, 0, 0, 0.6); f.cam(3.0, 40000, 0, 0.6); f.cam(10, 40000, 0, 0.6)
        doc = mock.Mock(meta={}, fmeta={}, dir=pathlib.Path(tmp))
        holds = LC.empty_holds([(0, 11, f)], doc, 10.0)
        self.assertEqual(len(holds), 1); self.assertGreaterEqual(holds[0][1] - holds[0][0], 5)
        self.assertEqual(LC.empty_holds([(0, 11, f)], doc, 10.0, allowed=[(2.5, 10.5)]), [])


if __name__ == "__main__":
    unittest.main()
