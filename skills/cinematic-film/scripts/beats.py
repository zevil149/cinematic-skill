#!/usr/bin/env python3
"""Beats: the language-neutral spine shared by every edition of a documentary. A beat is one hero
on screen: what the camera shows, the claims behind it and the images it needs. Each edition's
narration lines point to beats, so English and Hindi show the same images, maps and moves, each
timed by its own voice.

  python3 beats.py build --project P [--from en]    # from the source edition's narration
  python3 beats.py check --project P [hi]            # does an edition cover every beat, in its language?

Reads   editions/<source>/03_script/narration.json, editions/<lang>/03_script/narration.json
Writes  03_beats/beats.json, 03_beats/beats.md, 03_beats/image_needs.json (what visuals.py fetches)

A source line belongs to beat "beat" if it names one, else to its own beat B<line id>. Nothing is
written back into the narration. Rebuilding keeps what was added to beats.json by hand: card
titles in other languages ("labels": {"hi": "..."} on an image) and notes.

Every edition must cover every beat, and wherever the source shows typed text, the edition's
line for that beat must give its own (never the source's words). An image's fallback card shows
its label in the edition's language, so each image needs a label for every other edition.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import editions  # noqa: E402
import lang  # noqa: E402

GEN = "beats.py"


def beat_of(line):
    return line.get("beat") or f"B{int(line['id']):03d}"


def edition_lines(root, code):
    n = L.load(editions.edition_dir(root, code) / "03_script" / "narration.json", {})
    return [(s, l) for s in n.get("sections", []) for l in s.get("lines", [])], n


def build(root, source=None, log=print):
    root = pathlib.Path(root)
    p = L.paths(root)
    r = L.Result()
    source = source or editions.default_edition(root)
    lines, n = edition_lines(root, source)
    if not lines:
        r.error(f"edition {source} has no narration yet; write and approve its script first"); return r
    if n.get("lang", source) != source:
        r.error(f"editions/{source}/03_script/narration.json is tagged {n.get('lang')!r}"); return r
    old = {b["id"]: b for b in L.load(p["beats"], {"beats": []}).get("beats", [])}
    order, beats = [], {}
    for s, l in lines:
        bid = beat_of(l)
        if bid not in beats:
            order.append(bid)
            beats[bid] = {"id": bid, "section": s["id"], "hero": l.get("hero", ""), "visual": l.get("visual", ""),
                          "claims": [], "images": [], "typed": {}, "source_lines": {source: []}}
        b = beats[bid]
        b["source_lines"][source].append(l["id"])
        b["claims"] += [c for c in l.get("claims", []) if c not in b["claims"]]
        if l.get("typed"):
            b["typed"][source] = (b["typed"].get(source, "") + " · " if b["typed"].get(source) else "") + l["typed"]
        for im in l.get("images", []):
            b["images"].append(dict(im))
        if l.get("place") and "place" not in b:             # explicit: the place this beat is at, on a map.json map
            b["place"] = l["place"]
            if l.get("map"):
                b["map"] = l["map"]
    # explicit links between beats (a line's "links": the ids of the lines it is tied to), never inferred
    line_beat = {l["id"]: beat_of(l) for _, l in lines}
    for _, l in lines:
        for target in l.get("links") or []:
            tb = line_beat.get(target)
            if tb is None:
                r.warn(f"line {l['id']}: links to line {target!r}, which is not in the {source} script; ignored")
            elif tb != beat_of(l) and tb not in beats[beat_of(l)].setdefault("links", []):
                beats[beat_of(l)]["links"].append(tb)
    for b in beats.values():
        if not b.get("links"):
            b.pop("links", None)
    needs, k = [], 0
    for bid in order:
        b = beats[bid]
        prev = old.get(bid, {})
        for key in ("notes",):
            if key in prev:
                b[key] = prev[key]
        for code, t in prev.get("typed", {}).items():
            if code != source:
                b["typed"][code] = t
        prev_imgs = {(im.get("what"), im.get("kind")): im for im in prev.get("images", [])}
        for im in b["images"]:
            keep = prev_imgs.get((im.get("what"), im.get("kind")), {})
            if keep.get("labels"):
                im["labels"] = {**keep["labels"], **im.get("labels", {})}
            k += 1
            im["id"] = f"I{k:03d}"
            need = {"id": im["id"], "beat": bid, "scene": bid, "line": None, "what": im.get("what", ""),
                    "kind": im.get("kind", "photo"), "query": im.get("query") or im.get("what", ""),
                    "commons": im.get("commons", ""), "file": im.get("file", ""),
                    "status": "have" if im.get("file") else "needed"}
            for key in ("license", "credit", "clip_in", "clip_dur"):
                if key in im:
                    need[key] = im[key]
            needs.append(need)
    data = {"generated_by": GEN, "source": source, "beats": [beats[b] for b in order]}
    L.save(p["beats"], data)
    L.save(p["image_needs"], {"title": n.get("title", ""), "timing": "beats", "images": needs})
    L.write_text(p["beats_md"], render_md(data))
    r.note(f"{len(order)} beats from edition {source}, {len(needs)} images")
    return r


def check(root, code, r=None):
    """Does edition `code` cover every beat, with its own typed text and image labels?"""
    r = r or L.Result()
    p = L.paths(root)
    data = L.load(p["beats"], {})
    if not data.get("beats"):
        r.error("no beats yet: build them from the source edition (beats.py build)"); return r
    source = data["source"]
    if code == source:
        return r
    lines, n = edition_lines(root, code)
    if not lines:
        r.error(f"edition {code} has no narration yet"); return r
    lg = lang.get(code)
    allow = editions.allowed_words(editions.edition_dir(root, code))
    ids = {b["id"]: b for b in data["beats"]}
    covered, typed = {}, {}
    for s, l in lines:
        if not l.get("beat"):
            r.error(f"edition {code} line {l.get('id')}: says nothing about which beat it tells (add \"beat\")"); continue
        if l["beat"] not in ids:
            r.error(f"edition {code} line {l['id']}: beat {l['beat']!r} is not in beats.json"); continue
        covered.setdefault(l["beat"], []).append(l["id"])
        if l.get("typed"):
            typed[l["beat"]] = l["typed"]
    for b in data["beats"]:
        if b["id"] not in covered:
            r.error(f"edition {code}: beat {b['id']} ({b['hero'] or b['section']}) has no line")
        if b["typed"].get(source) and not typed.get(b["id"]):
            r.error(f"edition {code}: beat {b['id']} shows typed text in {source} ({b['typed'][source]!r}); "
                    f"give the {code} line its own typed text")
        for im in b.get("images", []):
            label = (im.get("labels") or {}).get(code)
            if not label:
                r.error(f"edition {code}: image {im.get('id')} ({im.get('what')!r}) of beat {b['id']} has no "
                        f"{code} label for its fallback card (beats.json: \"labels\": {{\"{code}\": \"...\"}})")
            else:
                for prob in lg.check_script(label, allow):
                    r.error(f"edition {code}: image {im.get('id')} label: {prob}")
    r.note(f"edition {code}: {len(covered)} of {len(ids)} beats covered")
    return r


def render_md(data):
    out = [f"# Beats (from the {data['source']} edition)", "", "Generated by beats.py; add labels and notes in beats.json.", "",
           "| Beat | Section | Hero | Typed | Images | Claims |", "|---|---|---|---|---|---|"]
    for b in data["beats"]:
        typed = "; ".join(f"{k}: {v}" for k, v in b["typed"].items())
        imgs = ", ".join(f"{im['id']} {im.get('what', '')}" for im in b["images"])
        out.append(f"| {b['id']} | {b['section']} | {b['hero']} | {typed} | {imgs} | {', '.join(b['claims'])} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--project", required=True); b.add_argument("--from", dest="source")
    c = sub.add_parser("check"); c.add_argument("--project", required=True); c.add_argument("lang", nargs="?")
    a = ap.parse_args()
    if a.cmd == "build":
        r = build(a.project, a.source)
    else:
        r = L.Result()
        for code in ([a.lang] if a.lang else editions.editions_of(a.project)):
            check(a.project, code, r)
    print(r.report("beats"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
