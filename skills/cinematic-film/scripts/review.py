#!/usr/bin/env python3
"""The look review of one edition: stills and contact strips of every act, a checklist, and
automated flags, for the person who approves the look (docpipe: review@<lang>, gate "look").

  python3 review.py --project P/editions/hi [--size 960x540]

Writes 07_review/<lang>/act_NN/ at the production root (07_review/en/ for a single-language film):
  probe_open.png, L0012.png ..., probe_close.png   a still at each line's key word, the act's first
                                                    and last frames
  strip_NN.jpg                                      a contact strip of each camera move between
                                                    sections, and of the closing pull-back
  sheet.jpg                                         every still of the act on one sheet
  review.md                                         the checklist and what the flags found
review.json (in 07_review/<lang>/) records every still, strip and flag.

Flags help the person who looks; they never pass or fail the look. A still is flagged "blank"
when it is almost a single colour, "near-uniform" when there is hardly anything in it, "very
dark" when its average brightness is very low. The checklist is the part that matters: the hero
is lit and readable, nothing important is cut by the frame edge, type is not dark on dark, labels
do not collide, no frame is empty mid-move, and the edition's own language and script are on
screen.

Resume: the same scenes, timing, storyboard and prepared assets render nothing new. A review.md
you have written notes into is kept; the new checklist goes to review.latest.md beside it.
Needs skia-python, numpy and Pillow (the render tools need them too).
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "review.py"
BLANK_STD, UNIFORM_STD, DARK_MEAN = 3.0, 8.0, 14.0
STRIP_FRAMES = 8
CHECKLIST = [
    "The hero of every line is lit, in frame and readable at phone size",
    "Nothing important is cut by the frame edge",
    "Type is never dark on dark or light on light",
    "Labels and cards do not collide",
    "The spotlight follows the camera",
    "No frame is empty in the middle of a move (see the strips)",
    "Moves between sections read as one continuous camera, not cuts",
    "Images are the right ones for their lines (and designed cards are acceptable where an image is missing)",
    "Every word on screen is in this edition's language and script; Devanagari is shaped correctly (Hindi)",
]


def rp(proj):
    p = L.paths(proj)
    code = p["lang"] or "en"
    out = pathlib.Path(p["root"]) / "07_review" / code
    return {**p, "code": code, "out": out, "json": out / "review.json", "acts": p["film_dir"] / "acts.json"}


def sha_file(f):
    return hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()


def fingerprint(proj, size="960x540"):
    """What the review shows: the act scenes, their lines and timing, the storyboard and the prepared
    assets. A change in any of them makes a new review (and lapses its approval)."""
    import prepare
    p = rp(proj)
    here = pathlib.Path(__file__).resolve().parent
    files = [p["acts"], p["timing"], p["storyboard"], p["proj"] / "scene.py",
             here / "scenekit.py", here / "engine.py"]                 # how the starters and the engine draw
    files += sorted(p["film_dir"].glob("act_*/scene.py"))
    h = hashlib.sha256(size.encode())
    for f in files:
        h.update(str(f.name).encode() + (pathlib.Path(f).read_bytes() if pathlib.Path(f).exists() else b"<missing>"))
    h.update(prepare.fingerprint(proj).encode())
    h.update(b"made" if p["json"].exists() else b"not made")          # whether a review exists, not its contents
    return h.hexdigest()[:16]


def flags_of(img):
    """Automated observations on one still (an RGB array): never a verdict."""
    import numpy as np
    a = np.asarray(img, dtype=np.float32)
    y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    small = y[::4, ::4]
    std, mean = float(small.std()), float(small.mean())
    out = []
    if std < BLANK_STD:
        out.append("blank")
    elif std < UNIFORM_STD:
        out.append("near-uniform")
    if mean < DARK_MEAN:
        out.append("very dark")
    return out, round(mean, 1), round(std, 1)


def load_act(path):
    spec = importlib.util.spec_from_file_location(f"review_act_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


def strips_for(doc, lines, sections, t_end):
    """[(name, t0, t1)]: each move between sections, and the closing pull-back."""
    out, prev = [], None
    for ln in lines:
        sec = sections.get(ln)
        if prev is not None and sec != prev[1]:
            out.append((f"strip_{len(out) + 1:02d}", max(0.0, doc.E(prev[0]) - 0.3), doc.L(ln) + 0.9))
        prev = (ln, sec)
    if lines:
        out.append((f"strip_{len(out) + 1:02d}", doc.E(lines[-1]), max(doc.E(lines[-1]) + 0.5, t_end)))
    return out


def build(proj, size="960x540", log=print):
    p = rp(proj)
    r = L.Result()
    for need, what in ((p["acts"], "06_film/acts.json: generate the scene starters first (scenegen)"),
                       (p["timing"], "audio/timing.json: build the narration first (narrate.py)"),
                       (p["storyboard"], "04_scenes/storyboard.json")):
        if not need.exists():
            r.error(f"no {what}"); return r
    try:
        import numpy as np  # noqa: F401
        from PIL import Image, ImageDraw
        import skia  # noqa: F401
    except ImportError as e:
        r.error(f"the review renders with skia-python, numpy and Pillow; {e.name} is not installed "
                "(pip install -r requirements.txt)"); return r
    timing = L.load(p["timing"])
    if p["lang"] and timing.get("lang") not in (None, p["lang"]):
        r.error(f"audio/timing.json is the {timing.get('lang')} voice; this is the {p['code']} edition"); return r
    acts = L.load(p["acts"])
    if p["lang"] and acts.get("lang") not in (None, p["lang"]):
        r.error(f"06_film/acts.json is the {acts.get('lang')} edition's; this is {p['code']}"); return r
    key = fingerprint(proj, size)
    old = L.load(p["json"], {}) if p["json"].exists() else {}
    if old.get("input_hash") == key and all((p["out"] / f).exists() for a in old.get("acts", []) for f in a.get("files", [])):
        r.note(f"{p['code']} review is up to date ({len(old.get('acts', []))} act(s)); nothing rendered")
        r.extend(summary(old))
        return r
    from engine import Doc, Renderer
    import scenekit
    w, h = map(int, size.lower().split("x"))
    sb = {s["line"]: s for s in L.load(p["storyboard"]).get("scenes", [])}
    report = {"lang": p["code"], "built_by": BUILT_BY, "size": size, "acts": []}
    for act in acts.get("acts", []):
        n = act["act"]
        scene = p["proj"] / act["scene"]
        d = p["out"] / f"act_{n:02d}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            doc = Doc(p["proj"])
            film = load_act(scene).build_film(doc)
            ren = Renderer(film, w, h, doc)
        except BaseException as e:                              # noqa: BLE001 - a scene that does not build
            r.error(f"act {n}: {act['scene']} does not build: {type(e).__name__}: {str(e)[:300]}"); continue
        lines = [ln for ln in act.get("lines", []) if ln in doc.seg]
        fps = film.fps

        def still(t, name):
            fr = ren.frame(max(0, min(round(t * fps), round(film.duration * fps) - 1)))
            Image.fromarray(fr).save(d / f"{name}.png")
            fl, mean, std = flags_of(fr)
            return {"name": name, "t": round(t, 2), "file": f"act_{n:02d}/{name}.png", "flags": fl, "mean": mean, "std": std}
        probes = []
        tc = act.get("title_card")
        if tc:                                              # a film of several acts: the act's title card
            probes.append({**still(tc["t0"] + (tc["t1"] - tc["t0"]) * 0.7, "probe_title"), "line": None,
                           "what": f"title card: {tc.get('label', '')} {tc.get('title', '')}"})
        if lines:
            probes.append({**still(doc.L(lines[0]) + 0.2, "probe_open"), "line": None, "what": "the act opens"})
        for ln in lines:
            kw = sb.get(ln, {}).get("key_word", "")
            t = scenekit.word_time(doc, ln, kw)
            pr = still(t, f"L{int(ln):04d}")
            probes.append({**pr, "line": ln, "what": sb.get(ln, {}).get("narration", ""), "key_word": kw})
        end = min(act.get("t1", film.duration), film.duration)
        if end >= film.duration - 0.01:                     # the film's own fade to black is not the act's last look
            end -= getattr(film, "fade_out", 0.0)
        t_close = max(0.0, end - 0.3)
        probes.append({**still(t_close, "probe_close"), "line": None, "what": "the act's last frame"})
        strips = []
        sections = {ln: sb.get(ln, {}).get("section") for ln in lines}
        for name, s0, s1 in strips_for(doc, lines, sections, t_close):
            frames = [ren.frame(max(0, min(round((s0 + (s1 - s0) * i / (STRIP_FRAMES - 1)) * fps), round(film.duration * fps) - 1)))
                      for i in range(STRIP_FRAMES)]
            fl = sorted({f for fr in frames for f in flags_of(fr)[0]})
            sheet_ = contact([Image.fromarray(f) for f in frames], [f"{s0 + (s1 - s0) * i / (STRIP_FRAMES - 1):.1f}s" for i in range(STRIP_FRAMES)])
            sheet_.save(d / f"{name}.jpg", quality=85)
            strips.append({"name": name, "t0": round(s0, 2), "t1": round(s1, 2), "file": f"act_{n:02d}/{name}.jpg", "flags": fl})
        contact([Image.open(d / f"{x['name']}.png") for x in probes],
                [f"{x['name']} {x['t']}s" + (" !" if x["flags"] else "") for x in probes]).save(d / "sheet.jpg", quality=85)
        files = [x["file"].split("/", 1)[1] for x in probes] + [x["file"].split("/", 1)[1] for x in strips] + ["sheet.jpg", "review.md"]
        entry = {"act": n, "scene": act["scene"], "t0": act.get("t0"), "t1": act.get("t1"), "probes": probes, "strips": strips,
                 "files": [f"act_{n:02d}/{f}" for f in files]}
        write_md(d, p["code"], n, entry, r, old)
        report["acts"].append(entry)
        log(f"{p['code']} act {n}: {len(probes)} stills, {len(strips)} strips")
    if not r.ok:
        return r
    L.save(p["json"], report)
    report["input_hash"] = fingerprint(proj, size)
    L.save(p["json"], report)
    r.extend(summary(report))
    return r


def contact(images, labels, cols=4):
    from PIL import Image, ImageDraw
    tw = images[0].width // 2
    th = images[0].height // 2
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), (24, 24, 24))
    dr = ImageDraw.Draw(sheet)
    for i, (im, lab) in enumerate(zip(images, labels)):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        sheet.paste(im.convert("RGB").resize((tw, th)), (x, y))
        dr.text((x + 4, y + th + 3), lab, fill=(230, 230, 230))
    return sheet


def write_md(d, code, n, entry, r, old):
    md = [f"# Look review: {code} edition, act {n}", "",
          "Automated flags point at stills worth a second look; they do not pass or fail anything. "
          "The look is approved by a person (docpipe.py approve --project P look" + (f" --lang {code}" if code != "en" else "") + ").", "",
          "## Checklist", ""] + [f"- [ ] {c}" for c in CHECKLIST] + ["", "## Stills", "", "| Still | Time | Line | Key word | Flags |", "|---|---|---|---|---|"]
    for x in entry["probes"]:
        md.append(f"| [{x['name']}]({x['name']}.png) | {x['t']}s | {(x.get('what') or '').replace('|', '/')[:90]} | "
                  f"{x.get('key_word', '')} | {', '.join(x['flags']) or '-'} |")
    md += ["", "## Camera moves", "", "| Strip | From | To | Flags |", "|---|---|---|---|"]
    for s in entry["strips"]:
        md.append(f"| [{s['name']}]({s['name']}.jpg) | {s['t0']}s | {s['t1']}s | {', '.join(s['flags']) or '-'} |")
    md += ["", "Every still on one page: [sheet.jpg](sheet.jpg).", "", "## Notes", "", ""]
    text = "\n".join(md)
    f = d / "review.md"
    recorded = next((a.get("md_sha") for a in old.get("acts", []) if a.get("act") == n), None)
    if f.exists() and recorded and sha_file(f) != recorded:
        (d / "review.latest.md").write_text(text, encoding="utf-8")
        r.note(f"act {n}: your notes in review.md are kept; the new checklist is review.latest.md")
        entry["files"] = [x if not x.endswith("review.md") else x.replace("review.md", "review.latest.md") for x in entry["files"]]
        entry["md_sha"] = recorded
        return
    f.write_text(text, encoding="utf-8")
    entry["md_sha"] = sha_file(f)


def summary(report):
    r = L.Result()
    for a in report.get("acts", []):
        flagged = [x for x in a["probes"] if x["flags"]] + [s for s in a["strips"] if s["flags"]]
        for x in flagged:
            r.warn(f"act {a['act']} {x['name']}: {', '.join(x['flags'])} (look at it)")
        r.note(f"act {a['act']}: {len(a['probes'])} stills, {len(a['strips'])} strips in 07_review/{report['lang']}/act_{a['act']:02d}/")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--size", default="960x540")
    a = ap.parse_args()
    r = build(a.project, a.size)
    print(r.report(f"review ({rp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
