#!/usr/bin/env python3
"""Scene-by-scene storyboard: one scene per narration line (one hero per line), with its start
and end time, the visual direction, a suggested camera move for scene.py, and every image the
film needs.

  python3 storyboard.py --project P

Reads   03_script/narration.json (or script.json), audio/timing.json when a voice exists
Writes  04_scenes/storyboard.json, 04_scenes/storyboard.md, 04_scenes/image_needs.json

Times are estimates at the scratch-voice pace until audio/timing.json exists; then they are the
real ones. Run it again after every new voice. The camera suggestions follow references/film.md:
a whip or pull-back to open a section, a push-in landing on the line's key word (the last
strong word, since lines put it last), and a final pull-back over the whole board.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

STOP = set("a an the and or but of to in on at for with from by is was were be been it its this that these those "
           "he she they we you i his her their our as so than then there here not no".split())
IMAGE_KINDS = ("photo", "doc", "paper", "map", "own", "ai", "color", "footage")


def key_word(spoken):
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", spoken)
    for w in reversed(words):
        if w.lower() not in STOP and len(w) > 2:
            return w
    return words[-1] if words else ""


def camera_for(first_in_section, first_in_film, last_in_film, line):
    if first_in_film:
        return "establishing: start close on the hero, ease back to reveal its place"
    if last_in_film:
        return "final pull-back over the whole board (zoom 0.13 to 0.3)"
    if first_in_section:
        return "whip or pull-back to this section's cluster (0.8 to 1.2 s), land 0.3 s after the hero appears"
    if line.get("typed") and re.search(r"\d", line.get("typed", "")):
        return "push in on the number as it rolls up"
    return "drift, then push in to land on the key word"


def build(proj, write=True):
    p = L.paths(proj)
    r = L.Result()
    if p["narration"].exists():
        src = L.load(p["narration"])
        sections = [(s["id"], s.get("take", s["id"]), s["lines"]) for s in src.get("sections", [])]
    elif p["script_json"].exists():
        src = L.load(p["script_json"])
        sections = [(t.get("section", t["take"]), t["take"], t["lines"]) for t in src.get("takes", [])]
    else:
        r.error("no narration.json or script.json to storyboard"); return r
    import lang
    lg = lang.for_paths(p, src)
    timing = {}
    if p["timing"].exists():
        tj = L.load(p["timing"])
        if p["lang"] and tj.get("lang") and tj["lang"] != p["lang"]:
            r.error(f"audio/timing.json is the {tj['lang']} voice; this is the {p['lang']} edition"); return r
        timing = {s["id"]: s for s in tj.get("segments", [])}
    beat_needs = None
    if p["edition"]:
        # an edition's images come from the shared beats, shown with the first line that tells each beat
        if not p["image_needs"].exists():
            r.error("no beats yet: build them from the source edition (beats.py build) first"); return r
        beat_needs = {}
        for nd in L.load(p["image_needs"]).get("images", []):
            beat_needs.setdefault(nd["beat"], []).append(nd["id"])
    flat = [(sid, take, k, l) for sid, take, lines in sections for k, l in enumerate(lines)]
    if not flat:
        r.error("the script has no lines"); return r
    per_section = {sid: len(lines) for sid, _, lines in sections}
    act_open = L.act_starts(L.load(p["outline"], {}) if p["outline"].exists() else {}, [(l["id"], sid) for sid, _, _, l in flat])
    scenes, needs, cursor = [], [], L.LEAD
    for n, (sid, take, k, l) in enumerate(flat):
        spoken = l.get("spoken") or lg.spoken_text(l.get("text", ""))
        if l["id"] in timing:
            start, dur = timing[l["id"]]["start"], timing[l["id"]]["duration"]
        else:
            start, dur = cursor, lg.est_seconds(spoken)
        gap = l.get("gap_after", L.TAKE_GAP if k == per_section[sid] - 1 else L.GAP)
        if n + 1 < len(flat) and flat[n + 1][3]["id"] in act_open:
            gap = max(gap, L.ACT_GAP)                        # the next act's title card holds in silence
        cursor = start + dur + gap
        first_sec = k == 0
        sc = {"scene": f"{sid}-{k + 1:02d}", "section": sid, "take": take, "line": l["id"],
              "start": round(start, 2), "end": round(start + dur, 2), "duration": round(dur, 2),
              "narration": l.get("text", ""), "visual": l.get("visual", ""), "hero": l.get("hero", ""),
              "typed": l.get("typed", ""), "key_word": lg.key_word(spoken),
              "camera": camera_for(first_sec, n == 0, n == len(flat) - 1, l),
              "transition": "section change" if first_sec and n else "",
              "claims": l.get("claims", []), "images": []}
        if beat_needs is not None:
            bid = l.get("beat") or f"B{int(l['id']):03d}"
            sc["beat"] = bid
            sc["images"] = beat_needs.pop(bid, [])          # the first line of a beat shows its images
        for im in ([] if beat_needs is not None else l.get("images", [])):
            kind = im.get("kind", "photo")
            if kind not in IMAGE_KINDS:
                r.warn(f"line {l['id']}: image kind {kind!r} is not one of {IMAGE_KINDS}")
            need = {"id": f"I{len(needs) + 1:03d}", "line": l["id"], "scene": sc["scene"], "what": im.get("what", ""),
                    "kind": kind, "query": im.get("query") or im.get("what", ""), "commons": im.get("commons", ""),
                    "file": im.get("file", ""), "status": "have" if im.get("file") else "needed"}
            for k in ("license", "credit", "clip_in", "clip_dur"):
                if k in im:
                    need[k] = im[k]
            needs.append(need); sc["images"].append(need["id"])
        if beat_needs is None and l.get("place"):
            sc["place"] = {"name": l["place"], "map": l.get("map", "")}
        if beat_needs is None and l.get("links"):
            sc["links"] = list(l["links"])                   # explicit: the lines this one is tied to
        if not sc["images"] and not sc["typed"] and not sc["hero"]:
            r.warn(f"line {l['id']}: nothing to show (no hero, image or typed text)")
        scenes.append(sc)
    link_scenes(p, scenes, beat_needs is not None, r)
    place_scenes(p, scenes, beat_needs is not None, lg, r)
    total = scenes[-1]["end"] + L.TAIL
    r.note(f"{len(scenes)} scenes, {L.mmss(total)} ({'voice timing' if timing else 'estimated'}), "
           f"{len(needs)} images ({sum(1 for x in needs if x['status'] == 'needed')} still to find)")
    if write:
        meta = {"title": src.get("title", ""), "timing": "voice" if timing else "estimate", "duration": round(total, 2)}
        if p["lang"]:
            meta = {"title": meta["title"], "lang": p["lang"], "timing": meta["timing"], "duration": meta["duration"]}
        L.save(p["storyboard"], {**meta, "scenes": scenes})
        if beat_needs is None:                               # an edition never rewrites the shared image list
            L.save(p["image_needs"], {**meta, "images": needs})
        L.write_text(p["storyboard_md"], render_md(meta, scenes, needs))
    return r


def link_scenes(p, scenes, edition, r):
    """Resolve explicit links to this storyboard's line ids: a line's own "links" (lines), or in an
    edition its beat's "links" (beats), shown from the first line that tells each beat. Never inferred."""
    ids = {s["line"] for s in scenes}
    if edition:
        first = {}
        for s in scenes:
            first.setdefault(s.get("beat"), s["line"])
        blinks = {b["id"]: b.get("links", []) for b in L.load(p["beats"], {"beats": []}).get("beats", [])}
        for bid, line in first.items():
            targets = []
            for tb in blinks.get(bid, []):
                if tb in first and first[tb] != line:
                    targets.append(first[tb])
                elif tb not in first:
                    r.warn(f"beat {bid} links to beat {tb}, which this edition does not tell; that string is left out")
            if targets:
                next(s for s in scenes if s["line"] == line)["links"] = targets
        return
    for s in scenes:
        if "links" in s:
            keep = [t for t in s["links"] if t in ids and t != s["line"]]
            for t in s["links"]:
                if t not in ids:
                    r.warn(f"line {s['line']}: links to line {t!r}, which is not in the script; ignored")
            if keep:
                s["links"] = keep
            else:
                del s["links"]


def place_scenes(p, scenes, edition, lg, r):
    """Resolve explicit places against map.json: the map that has the place (the line's "map" when
    several do), and the label in this edition's language (the map's "labels", then, outside
    English, the lexicon's spelling). A place that no map has is dropped with a warning: nothing is
    looked up or guessed from the narration."""
    if edition:
        first = {}
        for s in scenes:
            first.setdefault(s.get("beat"), s)
        for b in L.load(p["beats"], {"beats": []}).get("beats", []):
            if b.get("place") and b["id"] in first:
                first[b["id"]]["place"] = {"name": b["place"], "map": b.get("map", "")}
    todo = [s for s in scenes if "place" in s]
    if not todo:
        return
    maps = L.load(pathlib.Path(p["root"]) / "map.json", {"maps": []}).get("maps", [])
    code = p["lang"] or "en"
    lx = L.load(p["lexicon"], {}) if p["lexicon"].exists() else {}
    allow = set(lx.get("allow", []))
    for s in todo:
        name, want = s["place"]["name"], s["place"].get("map") or ""
        has = [m for m in maps if name in (m.get("places") or {})]
        m = next((x for x in has if x.get("name") == want), None) if want else (has[0] if len(has) == 1 else None)
        if m is None:
            why = (f"map {want!r} in map.json has no place {name!r}" if want else
                   f"no map in map.json has the place {name!r}" if not has else
                   f"{name!r} is on several maps ({', '.join(x['name'] for x in has)}): give the line a \"map\"")
            r.warn(f"line {s['line']}: {why}; no map pin for it")
            del s["place"]
            continue
        labels = (m.get("labels") or {}).get(name) or {}
        label = labels.get(code) or (name if code == "en" else "")
        if not label and code != "en":
            term = (lx.get("terms") or {}).get(name)
            label = (term.get("spoken") if isinstance(term, dict) else term) or ""
        if not label:
            r.warn(f"line {s['line']}: place {name!r} has no {code} label (\"labels\" in map.json); its pin has no label")
        for prob in (lg.check_script(label, allow) if label else []):
            r.warn(f"line {s['line']}: map label {label!r}: {prob}")
        s["place"] = {"name": name, "map": m["name"], "label": label}


def render_md(meta, scenes, needs):
    out = [f"# Storyboard: {meta['title']}", "",
           f"{len(scenes)} scenes, {L.mmss(meta['duration'])}, times {'from the voice' if meta['timing'] == 'voice' else 'estimated until a voice exists'}. "
           "Generated by storyboard.py.", "",
           "| Scene | Time | Narration | Hero and visual | Camera | Images |", "|---|---|---|---|---|---|"]
    for s in scenes:
        vis = "; ".join(x for x in (s["hero"], s["visual"]) if x)
        if s["typed"]:
            vis += f" (typed: {s['typed']})"
        out.append(f"| {s['scene']} | {L.mmss(s['start'])} to {L.mmss(s['end'])} | {s['narration']} | {vis} | "
                   f"{s['camera']}; key word *{s['key_word']}* | {', '.join(s['images'])} |")
    if needs:
        out += ["", "## Images", "", "| ID | Scene | What | Kind | Search | Status |", "|---|---|---|---|---|---|"]
        out += [f"| {n['id']} | {n['scene']} | {n['what']} | {n['kind']} | {n['commons'] or n['query']} | {n['status']} |" for n in needs]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    r = build(a.project)
    print(r.report("storyboard"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
