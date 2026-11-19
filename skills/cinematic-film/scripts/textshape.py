"""Complex-script text for the engine: Devanagari (Hindi) shaped by HarfBuzz, drawn by Skia.

Devanagari cannot be drawn one character at a time: a vowel sign like ि is written before the
consonant it follows (कि), consonants join into conjuncts and half forms (क्ष, स्त), र becomes a reph
above the next letter (र्म), and marks sit on their base. HarfBuzz turns a string into the right
glyphs at the right places; this module hands those to Skia.

engine.draw_text and engine.text_width call in here only when a string contains Devanagari;
every other string is drawn exactly as before, so English rendering is unchanged.

A string is split into runs: Devanagari runs (with the spaces, digits and punctuation around them)
are shaped with the Devanagari font; Latin runs (an allowed term such as NASA) keep the role's
usual font. Each text role gets a matching weight (and width, for the condensed role).

Font: <project>/fonts/deva.ttf if present, else the bundled Noto Sans Devanagari
(assets/fonts/, SIL OFL), else an installed "Noto Sans Devanagari".
Needs uharfbuzz (pip install uharfbuzz).
"""
import pathlib
import re
import unicodedata

import skia

BUNDLED = pathlib.Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoSansDevanagari-VF.ttf"
DEVANAGARI = re.compile(r"[ऀ-ॿ꣠-ꣿ᳐-᳿]")
JOINERS = "‌‍"
# role -> (weight, width) on the variable font's axes
ROLE_STYLE = {"cond": (700, 75.0), "label": (750, 100.0), "labelm": (500, 100.0), "serif": (450, 100.0),
              "mono": (500, 100.0), "hand": (400, 100.0)}


def needs_shaping(text):
    return bool(text) and DEVANAGARI.search(text) is not None


def _tag(s):
    return (ord(s[0]) << 24) | (ord(s[1]) << 16) | (ord(s[2]) << 8) | ord(s[3])


def font_path(fonts_dir=None):
    if fonts_dir and (pathlib.Path(fonts_dir) / "deva.ttf").exists():
        return pathlib.Path(fonts_dir) / "deva.ttf"
    if BUNDLED.exists():
        return BUNDLED
    return None


class DevaFonts:
    """Per-Res cache: the Devanagari typeface and HarfBuzz font for each role's weight and width."""

    def __init__(self, fonts_dir=None):
        try:
            import uharfbuzz as hb
        except ImportError:
            raise SystemExit("Hindi (Devanagari) text needs uharfbuzz: pip install uharfbuzz")
        self.hb = hb
        path = font_path(fonts_dir)
        if path is not None:
            self.data = path.read_bytes()
            self.base = skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(self.data))
        else:
            self.base = skia.FontMgr().matchFamilyStyle("Noto Sans Devanagari", skia.FontStyle())
            if self.base is None:
                raise SystemExit("no Devanagari font: the bundled assets/fonts/NotoSansDevanagari-VF.ttf is missing")
            self.data = self.base.serialize().toarray()
        self.path = path
        self.face = hb.Face(self.data)
        self.upem = self.face.upem
        axes = {a.tag for a in (self.base.getVariationDesignParameters() or [])}
        self.variable = _tag("wght") in axes and _tag("wdth") in axes
        self.cache = {}

    def for_role(self, role):
        if role not in self.cache:
            wght, wdth = ROLE_STYLE.get(role, (450, 100.0))
            tf, font = self.base, self.hb.Font(self.face)
            if self.variable:
                Coord = skia.FontArguments.VariationPosition.Coordinate
                coords = skia.FontArguments.VariationPosition.Coordinates([Coord(_tag("wght"), float(wght)), Coord(_tag("wdth"), float(wdth))])
                args = skia.FontArguments()
                args.setVariationDesignPosition(skia.FontArguments.VariationPosition(coords))
                tf = self.base.makeClone(args)
                font.set_variations({"wght": float(wght), "wdth": float(wdth)})
            self.cache[role] = (tf, font)
        return self.cache[role]


def runs(text):
    """[(start, end, is_devanagari)]: Devanagari with its marks and joiners in one kind of run,
    everything else in the other; spaces, digits and punctuation stay with the run they are in."""
    out, cur, start = [], None, 0
    for i, ch in enumerate(text):
        if DEVANAGARI.match(ch) or ch in JOINERS or (cur is True and unicodedata.category(ch).startswith("M")):
            kind = True
        elif unicodedata.category(ch)[0] in "LM":
            kind = False
        else:
            kind = cur                                   # neutral: keeps the current run
        if cur is None:
            cur = kind
        elif kind is not None and kind != cur:
            out.append((start, i, cur)); start, cur = i, kind
    out.append((start, len(text), bool(cur)))
    return out


class Shaped:
    """Glyphs of one string at one size: fonts, glyph ids, positions from the pen start, clusters."""

    def __init__(self, glyphs, width):
        self.glyphs = glyphs          # [(skia.Font, glyph id, x, y, cluster)]
        self.width = width

    def draw(self, c, x, y, paint, reveal=None):
        n = None if reveal is None else int(reveal)
        builder = skia.TextBlobBuilder()
        run, font = [], None
        for f, g, gx, gy, cl in self.glyphs:
            if n is not None and cl >= n:
                continue
            if f is not font and run:
                builder.allocRunPos(font, [r[0] for r in run], [skia.Point(r[1], r[2]) for r in run]); run = []
            font = f
            run.append((g, gx, gy))
        if run:
            builder.allocRunPos(font, [r[0] for r in run], [skia.Point(r[1], r[2]) for r in run])
        blob = builder.make()
        if blob is not None:
            c.drawTextBlob(blob, x, y, paint)


def shape(res, text, size, role="serif", track=0.0):
    """Shape text for res (engine.Res) at size, with tracking (em fraction) between clusters."""
    cache = res.__dict__.setdefault("_shaped", {})
    key = (text, role, round(size, 3), track)
    if key in cache:
        return cache[key]
    deva = res.__dict__.get("_deva")
    if deva is None:
        deva = res._deva = DevaFonts(res.fonts_dir)
    latin_font = res.font(role, size)
    glyphs, x, gap = [], 0.0, track * size
    last_cluster = None
    for a, b, is_deva in runs(text):
        if is_deva:
            tf, hbfont = deva.for_role(role)
            f = skia.Font(tf, size)
            f.setSubpixel(True); f.setEdging(skia.Font.Edging.kAntiAlias)
            buf = deva.hb.Buffer()
            buf.add_str(text[a:b])
            buf.guess_segment_properties()
            deva.hb.shape(hbfont, buf, {})
            s = size / deva.upem
            for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
                cl = a + info.cluster
                if last_cluster is not None and cl != last_cluster and gap:
                    x += gap
                glyphs.append((f, info.codepoint, x + pos.x_offset * s, -pos.y_offset * s, cl))
                x += pos.x_advance * s
                last_cluster = cl
        else:
            ids = latin_font.textToGlyphs(text[a:b])
            widths = latin_font.getWidths(ids)
            for k, (g, w) in enumerate(zip(ids, widths)):
                cl = a + k
                if last_cluster is not None and cl != last_cluster and gap:
                    x += gap
                glyphs.append((latin_font, g, x, 0.0, cl))
                x += w
                last_cluster = cl
    sh = Shaped(glyphs, x)
    if len(cache) > 512:
        cache.clear()
    cache[key] = sh
    return sh


def missing_glyphs(res, text, role="serif"):
    """The characters a font cannot show (they would be drawn as the empty box, glyph 0)."""
    return [text[cl] for _, g, _, _, cl in shape(res, text, 40, role).glyphs if g == 0]
