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
    timing = {}
    if p["timing"].exists():
        timing = {s["id"]: s for s in L.load(p["timing"]).get("segments", [])}
    flat = [(sid, take, k, l) for sid, take, lines in sections for k, l in enumerate(lines)]
    if not flat:
        r.error("the script has no lines"); return r
    per_section = {sid: len(lines) for sid, _, lines in sections}
    scenes, needs, cursor = [], [], L.LEAD
    for n, (sid, take, k, l) in enumerate(flat):
        spoken = l.get("spoken") or L.spoken_text(l.get("text", ""))
        if l["id"] in timing:
            start, dur = timing[l["id"]]["start"], timing[l["id"]]["duration"]
        else:
            start, dur = cursor, L.est_seconds(spoken)
        gap = l.get("gap_after", L.TAKE_GAP if k == per_section[sid] - 1 else L.GAP)
        cursor = start + dur + gap
        first_sec = k == 0
        sc = {"scene": f"{sid}-{k + 1:02d}", "section": sid, "take": take, "line": l["id"],
              "start": round(start, 2), "end": round(start + dur, 2), "duration": round(dur, 2),
              "narration": l.get("text", ""), "visual": l.get("visual", ""), "hero": l.get("hero", ""),
              "typed": l.get("typed", ""), "key_word": key_word(spoken),
              "camera": camera_for(first_sec, n == 0, n == len(flat) - 1, l),
              "transition": "section change" if first_sec and n else "",
              "claims": l.get("claims", []), "images": []}
        for im in l.get("images", []):
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
        if not sc["images"] and not sc["typed"] and not sc["hero"]:
            r.warn(f"line {l['id']}: nothing to show (no hero, image or typed text)")
        scenes.append(sc)
    total = scenes[-1]["end"] + L.TAIL
    r.note(f"{len(scenes)} scenes, {L.mmss(total)} ({'voice timing' if timing else 'estimated'}), "
           f"{len(needs)} images ({sum(1 for x in needs if x['status'] == 'needed')} still to find)")
    if write:
        meta = {"title": src.get("title", ""), "timing": "voice" if timing else "estimate", "duration": round(total, 2)}
        L.save(p["storyboard"], {**meta, "scenes": scenes})
        L.save(p["image_needs"], {**meta, "images": needs})
        L.write_text(p["storyboard_md"], render_md(meta, scenes, needs))
    return r


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
