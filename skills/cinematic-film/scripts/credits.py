"""The film's closing credits, in the edition's language, from the assets it actually uses (phase 6.4).

The lines come from rights.py's report: every image and clip the act scenes show, the music and
sounds the mix used, the map data the scenes draw, and the narration voice. Headings are the
edition's own (English or Hindi); titles, names and licences are given as their sources state them.
An edition that uses nothing that needs crediting (only designed cards, the synthesised bed and
effects) gets no credits sequence.

The sequence is drawn by the engine on the film's own board and look: a still page when it fits
the frame, otherwise a slow roll. It is rendered by finish.py render, after the acts, into
out/credits.<lang>.mp4 (silent), and finish.py join adds it after the film's last fade.
"""
import hashlib
import json
import pathlib

HEADINGS = {
    "en": {"title": "Credits", "image": "Photographs and documents", "video": "Film footage",
           "audio": "Music and sound", "map": "Map data", "voice": "Narration"},
    "hi": {"title": "आभार", "image": "तस्वीरें और दस्तावेज़", "video": "फ़िल्म फ़ुटेज",
           "audio": "संगीत और ध्वनि", "map": "नक्शे का डेटा", "voice": "वर्णन"},
}
SIZES = {"title": 180, "head": 96, "line": 64}
MAX_W = 3000                      # widest a credit line is set (world units at zoom 1 is 4K pixels)
LINE_SECS, MIN_SECS, MAX_SECS = 0.7, 7.0, 45.0


def entry_text(a):
    """One credit line: what it is, who made it, its licence, where it comes from."""
    parts = [a.get("what"), a.get("credit"), a.get("license"), a.get("provider")]
    seen, out = set(), []
    for x in parts:
        x = (x or "").strip()
        if x and x.lower() not in seen:
            seen.add(x.lower()); out.append(x)
    return " · ".join(out) or a.get("id", "")


def lines_for(report, code):
    """[(kind, text)] of the credits, or [] when nothing needs crediting."""
    h = HEADINGS.get(code, HEADINGS["en"])
    groups = [("image", [a for a in report.get("images", []) if a.get("usable")]),
              ("video", [a for a in report.get("footage", []) if a.get("usable")]),
              ("audio", [a for a in report.get("audio", []) if a.get("usable")]),
              ("map", report.get("maps", []))]
    if not any(g for _, g in groups):
        return []
    out = [("title", h["title"])]
    for kind, items in groups:
        if items:
            out.append(("head", h[kind]))
            seen = set()                                   # one line per distinct asset, not one per use:
            for a in items:                                # the same file shown in several scenes is credited once
                txt = entry_text(a)
                if txt not in seen:
                    seen.add(txt); out.append(("line", txt))
    nar = report.get("narration")
    if nar and nar.get("text"):
        out += [("head", h["voice"]), ("line", nar["text"])]
    return out


def _wrap(res, text, size, font, width):
    from engine import text_width
    words, rows, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and text_width(res, trial, size, font) > width:
            rows.append(cur); cur = w
        else:
            cur = trial
    rows.append(cur)
    return rows


def build_film(lines, look="wall", fonts_dir=None):
    """(Film, duration) of the credits."""
    from engine import BigText, Film, Res
    res = Res(1.0, None, fonts_dir)
    font = {"title": "cond", "head": "label", "line": "labelm"}
    rows, y = [], 0.0
    for kind, text in lines:
        size = SIZES[kind]
        y += size * (1.9 if kind == "head" and rows else 1.0 if kind == "title" else 1.45)
        for k, part in enumerate(_wrap(res, text, size, font[kind], MAX_W)):
            if k:
                y += size * 1.25
            rows.append((kind, part, y))
    height = y + SIZES["line"]
    dur = min(MAX_SECS, max(MIN_SECS, 3.0 + len(rows) * LINE_SECS))
    film = Film(dur, look=look)
    for kind, text, yy in rows:
        film.add(BigText(text, 0, yy, SIZES[kind], 0.3, font=font[kind], track=0.06 if kind == "title" else 0.0,
                         grunge=False, shadow=kind == "title", sfx=False))
    zoom = min(1.0, 3840 * 0.85 / (MAX_W + 200))
    view_h = 2160 / zoom * 0.8
    if height <= view_h:                                   # one page: a slow drift
        film.cam(0.0, 0, height / 2 - 40, zoom * 0.98)
        film.cam(dur, 0, height / 2 + 40, zoom)
    else:                                                  # a roll, top to bottom
        film.cam(0.0, 0, view_h / 2 - SIZES["title"], zoom)
        film.cam(1.2, 0, view_h / 2 - SIZES["title"], zoom)
        film.cam(dur - 1.5, 0, height - view_h / 2 + SIZES["line"], zoom)
        film.cam(dur, 0, height - view_h / 2 + SIZES["line"], zoom)
    film.auto_whoosh = False
    return film, dur


def key(lines, size, look, fonts_identity):
    here = pathlib.Path(__file__).resolve().parent
    h = hashlib.sha256(json.dumps([lines, size, look, fonts_identity], ensure_ascii=False, sort_keys=True).encode())
    for f in ("credits.py", "engine.py", "textshape.py"):
        h.update((here / f).read_bytes())
    return h.hexdigest()[:20]


def render(lines, out, size, proj, look="wall"):
    """Render the credits to out (H.264, silent stereo track) on the project's board. Returns (duration, frames)."""
    import subprocess
    from engine import Doc, Renderer
    proj = pathlib.Path(proj)
    film, dur = build_film(lines, look, proj / "fonts")
    w, h = map(int, size.lower().split("x"))
    r = Renderer(film, w, h, Doc(proj))
    n = int(round(dur * film.fps))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                           "-r", str(film.fps), "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "128k", "-t", f"{n / film.fps:.3f}", str(out)], stdin=subprocess.PIPE)
    try:
        for i in range(n):
            ff.stdin.write(r.frame(i).tobytes())
        ff.stdin.close()
    except BaseException:
        ff.kill(); ff.wait()
        raise
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed to encode the credits")
    return n / film.fps, n
