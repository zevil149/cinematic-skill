"""Text geometry of a film's scenes, for quality control: text that does not fit the card it is set
on, and on-screen text that the burned captions would cover.

Only items whose text the engine lays out in a way that can be measured exactly are checked:
  Card       its title and lines, measured with the font the card draws them in, against the card's
             inner width (inside its padding) and height
  PaperDoc   its header lines, against the paper's width
  BigText    words in world space, measured, for caption collisions
  Counter    its final number and caption, for caption collisions
Other text (map pin labels, stamps, ledgers, hand-drawn notes) is not measured; the report says how
many items of each kind were and were not checked. Everything is read from the scene; nothing is
rendered here except the caption layer, whose pixels give the captions' real place on screen.

Positions are taken when an item has settled (its entrance animation done) and is at least half
visible; a camera handheld wobble of a few pixels is ignored.
"""
import math

MEASURED = ("Card", "PaperDoc", "BigText", "Counter")
SETTLE = 0.6                  # seconds after t_in: entrance animations are done


def _items(film):
    """(item, parallax wrapper or None) for every item, Parallax unwrapped (typed words float on one)."""
    for it in film.items:
        if type(it).__name__ == "Parallax":
            yield it.item, it
        else:
            yield it, None


def _rot(dx, dy, deg):
    r = math.radians(deg)
    return dx * math.cos(r) - dy * math.sin(r), dx * math.sin(r) + dy * math.cos(r)


def overflows(film, res):
    """[{"kind", "text", "t", "what", "over"}]: text wider than the room its item gives it.
    "over" is the fraction by which it exceeds that room (0.1 = 10% too wide)."""
    from engine import text_width
    out = []
    for it, _ in _items(film):
        kind = type(it).__name__
        if kind == "Card":
            room = it.w - 2 * it.w * 0.08
            if it.title:
                tw = text_width(res, it.title, it.ts, "label", 0.0)
                if tw > room * 1.01:
                    out.append({"kind": kind, "text": it.title, "t": round(it.t_in, 2), "what": "title wider than the card",
                                "over": round(tw / room - 1, 3)})
            for ln in it.lines:
                tw = text_width(res, ln, it.bs, "labelm", 0.0)
                if tw > room * 1.01:
                    out.append({"kind": kind, "text": ln, "t": round(it.t_in, 2), "what": "line wider than the card",
                                "over": round(tw / room - 1, 3)})
            pad = it.w * 0.08
            y = -it.h / 2 + pad + it.ts * 0.85 + (it.ts * 0.55 if it.title else 0) + len(it.lines) * it.bs * 1.45
            bottom = y + (it.bs * 0.3 if it.lines else it.ts * 0.2)
            if bottom > it.h / 2 * 1.01:
                out.append({"kind": kind, "text": (it.title or (it.lines or [""])[0]), "t": round(it.t_in, 2),
                            "what": "text runs below the card", "over": round(bottom / (it.h / 2) - 1, 3)})
        elif kind == "PaperDoc":
            for txt, size, font in it.header:
                tw = text_width(res, txt, size, font, 0.08 if font == "mono" else 0.04)
                if tw > it.w * 0.98:
                    out.append({"kind": kind, "text": txt, "t": round(it.t_in, 2), "what": "header wider than the paper",
                                "over": round(tw / (it.w * 0.98) - 1, 3)})
    return out


def _local_boxes(it, res):
    """[(text, x0, y0, x1, y1)] in the item's local frame (Card, PaperDoc) or world (BigText, Counter)."""
    from engine import text_width
    kind = type(it).__name__
    boxes = []
    if kind == "Card":
        pad = it.w * 0.08
        x0 = -it.w / 2 + pad
        y = -it.h / 2 + pad + it.ts * 0.85
        if it.title:
            boxes.append((it.title, x0, y - it.ts * 0.8, x0 + text_width(res, it.title, it.ts, "label", 0.0), y + it.ts * 0.2))
            y += it.ts * 0.55
        for ln in it.lines:
            y += it.bs * 1.45
            boxes.append((ln, x0, y - it.bs * 0.8, x0 + text_width(res, ln, it.bs, "labelm", 0.0), y + it.bs * 0.2))
    elif kind == "PaperDoc":
        y = -it.h / 2 + it.h * 0.09
        for txt, size, font in it.header:
            tw = text_width(res, txt, size, font, 0.08 if font == "mono" else 0.04)
            boxes.append((txt, -tw / 2, y + size * 0.2, tw / 2, y + size * 1.2))
            y += size * 1.45
    elif kind == "BigText":
        tw = text_width(res, it.text, it.size, it.font, it.track)
        boxes.append((it.text, it.x - tw / 2, it.y - it.size * 0.8, it.x + tw / 2, it.y + it.size * 0.2))
    elif kind == "Counter":
        txt = f"{it.prefix}{it.value:,}{it.suffix}"
        tw = text_width(res, txt, it.size, it.font, 0.03)
        boxes.append((txt, it.x - tw / 2, it.y - it.size * 0.8, it.x + tw / 2, it.y + it.size * 0.2))
    return boxes


def _world(it, x, y):
    if type(it).__name__ in ("Card", "PaperDoc"):
        dx, dy = _rot(x, y, it.rot)
        return it.x + dx, it.y + dy
    return x, y


def screen_text(film, res, t, W, H):
    """[(kind, text, (x0, y0, x1, y1))] of measured text on screen at t, in pixels of a W x H frame."""
    cx, cy, z, rot = film.camera(t)
    k = z * W / 3840.0
    out = []
    for it, par in _items(film):
        kind = type(it).__name__
        if kind not in MEASURED or not it.visible(t) or t < it.t_in + SETTLE or it.fade(t) < 0.5:
            continue
        ox, oy = ((cx - par.anchor[0]) * (1 - par.depth), (cy - par.anchor[1]) * (1 - par.depth)) if par else (0.0, 0.0)
        for text, x0, y0, x1, y1 in _local_boxes(it, res):
            pts = []
            for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                wx, wy = _world(it, px, py)
                wx, wy = wx + ox, wy + oy
                sx, sy = _rot(wx - cx, wy - cy, rot)
                pts.append((W / 2 + k * sx, H / 2 + k * sy))
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            box = (min(xs), min(ys), max(xs), max(ys))
            if box[2] < 0 or box[0] > W or box[3] < 0 or box[1] > H:
                continue
            out.append((kind, text, box))
    return out


def caption_box(cap, t, alpha=0.5):
    """(x0, y0, x1, y1) of the caption's opaque pixels at t (alpha over 0.5), or None."""
    import numpy as np
    if cap.active(t) is None:
        return None
    a = np.asarray(cap.layer(t))[..., 3]
    ys, xs = np.nonzero(a >= int(255 * alpha))
    if not len(xs):
        return None
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def collisions(films, cap, W, H, res_of, min_cover=0.25):
    """[{"t", "kind", "text", "cover"}]: measured text at least min_cover under an opaque caption, at
    the middle of each caption chunk. films: [(start, end, film)] covering the timeline."""
    out = []
    for ch in cap.chunks:
        t = (ch["t0"] + ch["t1"]) / 2
        film = next((f for s, e, f in films if s <= t < e), None)
        if film is None:
            continue
        cb = caption_box(cap, t)
        if cb is None:
            continue
        for kind, text, b in screen_text(film, res_of(film), t, W, H):
            ix = max(0.0, min(b[2], cb[2]) - max(b[0], cb[0]))
            iy = max(0.0, min(b[3], cb[3]) - max(b[1], cb[1]))
            area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
            cover = ix * iy / area
            if cover >= min_cover:
                out.append({"t": round(t, 2), "kind": kind, "text": text, "cover": round(cover, 2)})
    return out


def census(films):
    """{kind: count} of the items with text, measured or not."""
    texty = MEASURED + ("MapPin", "Stamp", "Ledger", "OpenLedger", "PenMark", "Chalk", "XMarker")
    out = {}
    for _, _, film in films:
        for it, _ in _items(film):
            kind = type(it).__name__
            if kind in texty:
                out[kind] = out.get(kind, 0) + 1
    return out
