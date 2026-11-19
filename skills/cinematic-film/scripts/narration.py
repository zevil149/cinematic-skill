#!/usr/bin/env python3
"""Narration script for a documentary: sections of lines, each line citing the claims it states,
with its visual direction. Checked against the research, then exported to script.json for the
film tools (make_beats.py, tts_say.py, split_takes.py, build_narration.py, render.py).

  python3 narration.py init --project P       # one section per outline section, never overwrites
  python3 narration.py check --project P      # fact and style lint; writes 03_script/script.md
  python3 narration.py spoken --project P     # fill each line's "spoken" (numbers and dates as words)
  python3 narration.py export --project P     # check, then write <project>/script.json

A line in 03_script/narration.json:
  {"id": 12, "text": "The first flight lasted 12 seconds.",   shown in captions, read for facts
   "spoken": "The first flight lasted twelve seconds.",    optional; filled by `spoken`
   "claims": ["C3"],                                         what it states, from claims.json
   "visual": "first-flight photo; counters roll up",        the visual direction
   "hero": "the first-flight photo",                         the one thing the camera is on
   "typed": "12 SECONDS",                                    text drawn on screen, if any
   "images": [{"what": "First flight, 1903", "kind": "photo", "query": "Wright first flight 1903"}],
   "kind": "framing"}                                        only for lines that state no fact

The fact check, per line:
  * a line that is not "framing" must cite at least one claim
  * every number or year in the text must appear in a cited claim
  * a cited claim must have a valid source; a disputed one needs a hedge ("about", "reported")
  * weak and single-source claims are flagged for the review
Style: 4 to 22 words a line, a hero, a visual direction, numbers spoken as words, and each
section within 25% of its word budget.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import lang  # noqa: E402

GENERATOR = "narration.py"


def language(p, n=None):
    """The narration's language plugin: the edition's language, else the narration's tag, else
    English (a single-language project, exactly as before)."""
    return lang.for_paths(p, n)


def init_from_beats(p, force=False):
    """A non-source edition starts from the shared beats: one line per beat, in this edition's
    language, pointing to its beat, with the beat's claims. Its words are written for this
    language, never copied from the source edition."""
    data = L.load(p["beats"])
    secs, order = {}, []
    for b in data["beats"]:
        if b["section"] not in secs:
            order.append(b["section"]); secs[b["section"]] = []
        line = {"id": None, "beat": b["id"], "text": "TODO", "claims": list(b.get("claims", [])),
                "visual": b.get("visual", ""), "hero": b.get("hero", ""), "typed": "TODO" if b["typed"] else ""}
        secs[b["section"]].append(line)
    nid, out = 1, []
    for n, sid in enumerate(order, 1):
        for line in secs[sid]:
            line["id"] = nid; nid += 1
        out.append({"id": sid, "take": f"T{n:02d}_{L.slug(sid)}", "lines": secs[sid]})
    o = L.load(p["outline"], {})
    L.save(p["narration"], {"title": o.get("title", ""), "lang": p["lang"], "from_beats": data.get("source"), "sections": out})
    print(f"narration skeleton for {p['lang']}: {nid - 1} lines, one per beat of the {data.get('source')} edition -> {p['narration']}")
    return True


def init(proj, force=False):
    p = L.paths(proj)
    if p["narration"].exists() and not force:
        print(f"{p['narration']} exists; leaving it alone"); return False
    if p["edition"] and not p["edition"]["beats"] == "own" and p["beats"].exists() \
            and L.load(p["beats"]).get("source") != p["lang"]:
        return init_from_beats(p, force)
    o = L.load(p["outline"])
    secs, nid = [], 1
    for n, s in enumerate(o["sections"], 1):
        secs.append({"id": s["id"], "take": f"T{n:02d}_{L.slug(s.get('title') if s.get('title') != 'TODO' else s['kind'])}",
                     "target_words": s.get("target_words"),
                     "lines": [{"id": nid, "text": "TODO", "claims": list(s.get("claims", []))[:1],
                                "visual": "TODO", "hero": "", "typed": ""}]})
        nid += 1
    data = {"title": o.get("title", ""), "sections": secs}
    if p["lang"]:
        data = {"title": data["title"], "lang": p["lang"], "sections": secs}
    L.save(p["narration"], data)
    print(f"narration skeleton: {len(secs)} sections -> {p['narration']}")
    return True


def _lines(n):
    for s in n.get("sections", []):
        for l in s.get("lines", []):
            yield s, l


def fill_spoken(proj, overwrite=False):
    p = L.paths(proj)
    n = L.load(p["narration"])
    lg = language(p, n)
    changed = 0
    for _, l in _lines(n):
        if overwrite or not l.get("spoken"):
            new = lg.spoken_text(l.get("text", ""))
            if new != l.get("spoken"):
                l["spoken"] = new; changed += 1
    L.save(p["narration"], n)
    print(f"spoken text filled for {changed} line(s)")
    return changed


def check(proj, write=True):
    p = L.paths(proj)
    r = L.Result()
    if not p["narration"].exists():
        r.error("no narration yet: run narration.py init"); return r
    n = L.load(p["narration"])
    lg = language(p, n)
    if p["lang"] and n.get("lang") != p["lang"]:
        r.error(f"narration.json is tagged {n.get('lang')!r}, but this is the {p['lang']} edition")
    allow = set(L.load(p["lexicon"], {}).get("allow", [])) if p["lang"] else set()
    claims = {c["id"]: c for c in L.load(p["claims"], {"claims": []})["claims"]}
    sources = {s["id"]: s for s in L.load(p["sources"], {"sources": []})["sources"]}
    outline = L.load(p["outline"], {"sections": [], "minutes": 0})
    out_ids = {s["id"] for s in outline.get("sections", [])}
    status = {cid: L.claim_status(c, sources) for cid, c in claims.items()}
    ids, takes = set(), set()
    total_words, total_secs, nlines = 0, L.LEAD + L.TAIL, 0
    for s in n.get("sections", []):
        sid = s.get("id", "?")
        if out_ids and sid not in out_ids:
            r.warn(f"{sid}: not a section of the outline")
        if s.get("take") in takes:
            r.error(f"{sid}: take name {s.get('take')!r} is used twice")
        takes.add(s.get("take"))
        if not s.get("lines"):
            r.error(f"{sid}: no lines"); continue
        words = 0
        for k, l in enumerate(s["lines"]):
            nlines += 1
            i = l.get("id")
            where = f"line {i}"
            if not isinstance(i, int) or i in ids:
                r.error(f"{where} ({sid}): ids must be unique integers"); continue
            ids.add(i)
            text = l.get("text", "").strip()
            if not text or "TODO" in text:
                r.error(f"{where}: not written yet"); continue
            w = len(text.split()); words += w
            if w > L.MAX_LINE_WORDS:
                r.warn(f"{where}: {w} words; split it (one idea per line)")
            elif w < 3:
                r.warn(f"{where}: {w} words; very short lines read as fragments")
            if not l.get("hero"):
                r.warn(f"{where}: no hero (what is the camera on?)")
            if not l.get("visual") or "TODO" in l.get("visual", ""):
                r.warn(f"{where}: no visual direction")
            spoken = l.get("spoken") or lg.spoken_text(text)
            for field, value in (("text", text), ("spoken", spoken), ("typed", l.get("typed", ""))):
                for prob in lg.check_script(value, allow):
                    # an edition never mixes languages; a single-language project gets a warning, as before it had none
                    (r.error if p["lang"] else r.warn)(f"{where} {field}: {prob}")
            for msg in lg.spoken_warnings(spoken):
                r.warn(f"{where}: {msg}")
            total_secs += lg.est_seconds(spoken) + l.get("gap_after", L.TAKE_GAP if k == len(s["lines"]) - 1 else L.GAP)
            # the fact check
            cited = l.get("claims", [])
            bad = [c for c in cited if c not in claims]
            if bad:
                r.error(f"{where}: cites unknown claim(s) {bad}")
            cited = [c for c in cited if c in claims]
            if l.get("kind") == "framing":
                if lg.numbers_in(text):
                    r.warn(f"{where}: marked framing but states a number; cite the claim it comes from")
                continue
            if not cited:
                r.warn(f"{where}: UNSUPPORTED, cites no claim. Cite one, or mark it \"kind\": \"framing\" if it states no fact")
                continue
            for c in cited:
                st = status[c]
                if st == "unsupported":
                    r.error(f"{where}: cites {c}, which has no valid source")
                elif st == "disputed" and not L.HEDGES.search(text):
                    r.warn(f"{where}: {c} is disputed; hedge it ('about', 'reported', 'according to')")
                elif st in ("weak", "single-source"):
                    r.warn(f"{where}: rests on {c}, which is {st}")
            have = set()
            for c in cited:
                have |= L.numbers_in(claims[c].get("text", "")) | L.numbers_in(claims[c].get("quote", ""))
                if lg.code != "en":                       # a claim may also carry its words in this language
                    have |= lg.numbers_in(claims[c].get(f"text_{lg.code}", ""))
            missing = sorted(v for v in lg.numbers_in(text) if v not in have)
            if missing:
                nums = ", ".join(f"{v:g}" for v in missing)
                r.warn(f"{where}: states {nums}, which no cited claim contains; check the number or cite its claim")
        total_words += words
        tw = s.get("target_words")
        if tw and abs(words - tw) > 0.25 * tw and tw >= 20:
            r.warn(f"{sid}: {words} words against a budget of {tw}")
    target = float(outline.get("minutes") or 0) * 60
    if target and abs(total_secs - target) > 0.15 * target:
        r.warn(f"estimated length {L.mmss(total_secs)} against {L.mmss(target)}")
    r.note(f"{nlines} lines, {total_words} words, about {L.mmss(total_secs)} at the scratch-voice pace")
    if write and n.get("sections"):
        L.write_text(p["script_md"], render_md(n, lg))
    return r


def render_md(n, lg=None):
    lg = lg or lang.get("en")
    out = [f"# {n.get('title', 'Script')}", "", "Generated by narration.py; edit narration.json, not this file.", "",
           "| Line | Time | Narration | Visual | Claims |", "|---|---|---|---|---|"]
    t = L.LEAD
    for s in n["sections"]:
        out.append(f"| **{s['id']}** | | **{s.get('take', '')}** | | |")
        for k, l in enumerate(s["lines"]):
            spoken = l.get("spoken") or lg.spoken_text(l.get("text", ""))
            cl = "framing" if l.get("kind") == "framing" else ", ".join(l.get("claims", [])) or "**none**"
            out.append(f"| {l.get('id')} | {L.mmss(t)} | {l.get('text', '')} | {l.get('visual', '')} | {cl} |")
            t += lg.est_seconds(spoken) + l.get("gap_after", L.TAKE_GAP if k == len(s["lines"]) - 1 else L.GAP)
    return "\n".join(out) + "\n"


def export(proj, force=False):
    """Write <project>/script.json in the film tools' format. Refuses to replace a script.json that
    this tool did not write, unless force."""
    p = L.paths(proj)
    r = check(proj)
    if not r.ok:
        return r
    if p["script_json"].exists() and not force:
        cur = L.load(p["script_json"])
        if cur.get("generated_by") != GENERATOR:
            r.error(f"{p['script_json']} was not written by {GENERATOR}; move it aside or pass --force")
            return r
    n = L.load(p["narration"])
    lg = language(p, n)
    claims = {c["id"]: c for c in L.load(p["claims"], {"claims": []})["claims"]}
    sources = {s["id"]: s for s in L.load(p["sources"], {"sources": []})["sources"]}
    takes = []
    for s in n["sections"]:
        lines = []
        for l in s["lines"]:
            out = {"id": l["id"], "text": l["text"].strip(), "spoken": (l.get("spoken") or lg.spoken_text(l["text"])).strip(),
                   "hero": l.get("hero", ""), "typed": l.get("typed", ""), "claims": l.get("claims", []),
                   "visual": l.get("visual", "")}
            if "gap_after" in l:
                out["gap_after"] = l["gap_after"]
            if l.get("beat"):
                out["beat"] = l["beat"]
            lines.append(out)
        takes.append({"take": s["take"], "section": s["id"], "lines": lines})
    used = sorted({c for s in n["sections"] for l in s["lines"] for c in l.get("claims", [])},
                  key=lambda c: int(re.sub(r"\D", "", c) or 0))
    notes = []
    for c in used:
        cl = claims[c]
        refs = "; ".join(f"{sid}: {sources[sid].get('url') or sources[sid].get('title', '')}"
                         for sid in cl.get("sources", []) if sid in sources)
        notes.append(f"{c}: {cl['text']} [{refs}]")
    data = {"title": n.get("title", ""), "generated_by": GENERATOR, "takes": takes, "fact_notes": notes}
    if p["lang"]:
        data = {"title": data["title"], "lang": p["lang"], "generated_by": GENERATOR, "takes": takes, "fact_notes": notes}
    L.save(p["script_json"], data)
    r.note(f"exported {sum(len(t['lines']) for t in takes)} lines in {len(takes)} takes -> {p['script_json']}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "check", "spoken", "export"):
        s = sub.add_parser(name); s.add_argument("--project", required=True)
        if name in ("init", "export"):
            s.add_argument("--force", action="store_true")
        if name == "spoken":
            s.add_argument("--overwrite", action="store_true", help="redo lines that already have spoken text")
    a = ap.parse_args()
    if a.cmd == "init":
        init(a.project, a.force)
    elif a.cmd == "spoken":
        fill_spoken(a.project, a.overwrite)
    else:
        r = check(a.project) if a.cmd == "check" else export(a.project, a.force)
        print(r.report("narration"))
        sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
