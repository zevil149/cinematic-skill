#!/usr/bin/env python3
"""The production's final report and credits (phase 6.5; docpipe: report, the last stage).

  python3 report.py --project my-doc            # reports/final_report.md, reports/credits.md, reports/report.json

Gathers what the pipeline recorded into one place a person can read before publishing:
  status     each edition: its stages, the look approval, the finished film's QC and delivery
  script     each edition's script check (narration.py), the claims every line cites with their
             status (supported, single-source, weak, disputed, unsupported), and a warning where a
             line seems not to say what the claim it cites says (English: content words shared with
             the claim; a number in the line must be in the claim, as the script check requires)
  images     every image need: placed, your own, or a designed card; which were picked automatically
             and whether a person acknowledged them; every placed file opens; the rights verdicts of
             what each film shows (rights.py)
  audio      each edition's mix: length against the timing, loudness against its target, true peak
             and clipping; the voice, its provider and what it cost
  video      each edition's QC: blocking errors, warnings, what was not checked, the measurements
  trace      claim -> sources -> the lines that state it in each edition -> their scenes -> the images
             on those lines and their rights
  limits     what none of this proves
credits.md lists everything credited in every edition's film, with full attributions and links, and
each edition gets out/credits.<lang>.md next to its film.

Nothing here proves the film's facts are right or its assets free to use: the fact check matches
numbers and words against the research a person entered, and the rights record what archives and
people stated and cleared. The report says so. It is built from the records alone (no clock, no
network), so the same records make the same report.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "report.py"
STOP = set("""a an the and or but of in on at to for from by with as is was were be been are this that these those it its
into over under after before than then there their they them he she his her we our you your not no so if when while
which who whom what where why how also only just more most very one two three first second""".split())
OVERLAP_WARN = 0.25


def rpaths(root):
    root = pathlib.Path(root)
    d = root / "reports"
    return {"root": root, "dir": d, "md": d / "final_report.md", "credits": d / "credits.md", "json": d / "report.json"}


def editions(root):
    import editions as E
    eds = E.editions_of(root)
    return [(c, E.edition_dir(root, c)) for c in eds] if eds else [("en", pathlib.Path(root))]


def content_words(text):
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP}


def claim_match(line, claim):
    """(share of the claim's content words the line uses, numbers in the line the claim lacks)."""
    cw = content_words(claim)
    share = len(cw & content_words(line)) / len(cw) if cw else 1.0
    return share, sorted(set(L.numbers_in(line)) - set(L.numbers_in(claim)))


def script_part(root, code, ed):
    import narration
    p = L.paths(ed)
    r = narration.check(ed, write=False) if p["narration"].exists() else None
    claims = {c["id"]: c for c in L.load(p["claims"], {"claims": []}).get("claims", [])}
    sources = {s["id"]: s for s in L.load(p["sources"], {"sources": []}).get("sources", [])}
    lines, notes = [], []
    n = L.load(p["narration"], {}) if p["narration"].exists() else {}
    english = code == "en"
    for sec in n.get("sections", []):
        for ln in sec.get("lines", []):
            cited = []
            for cid in ln.get("claims", []):
                c = claims.get(cid)
                st = L.claim_status(c, sources) if c else "unknown"
                cited.append({"claim": cid, "status": st})
                if c and english and ln.get("text"):
                    share, extra = claim_match(ln["text"], c.get("text", ""))
                    if share < OVERLAP_WARN and not extra:
                        notes.append(f"line {ln.get('id')}: shares little with {cid} ({share:.0%} of its words); "
                                     f"check that it says what {cid} says")
                if st in ("unsupported", "weak", "disputed", "single-source", "unknown"):
                    notes.append(f"line {ln.get('id')}: cites {cid}, which is {st}")
            if not ln.get("claims") and ln.get("kind") != "framing":
                notes.append(f"line {ln.get('id')}: states something but cites no claim")
            lines.append({"id": ln.get("id"), "section": sec.get("id"), "claims": cited})
    return {"errors": r.errors if r else ["no narration"], "warnings": r.warnings if r else [], "lines": lines, "notes": notes,
            "claim_check": "words and numbers" if english else "numbers only (the claims are written in English)"}


def images_part(root, eds):
    import rights
    from PIL import Image
    p = L.paths(root)
    man = L.load(p["visuals_dir"] / "assets.json", {}).get("assets", {}) if (p["visuals_dir"] / "assets.json").exists() else {}
    sel = L.load(p["visuals_dir"] / "selection.json", {}) if (p["visuals_dir"] / "selection.json").exists() else {}
    ack = set(sel.get("acknowledged", []))
    counts, auto, unread = {}, [], []
    for nid, a in sorted(man.items()):
        counts[a["status"]] = counts.get(a["status"], 0) + 1
        if a.get("auto") and a["status"] == "ok":
            auto.append({"need": nid, "what": a.get("what", ""), "license": (a.get("license") or {}).get("label", ""),
                         "acknowledged": nid in ack or nid in sel})
        if a["status"] in ("ok", "own") and a.get("file"):
            f = root / "assets" / ("footage" if a.get("media") == "video" else "photos") / a["file"]
            if a.get("media") != "video":
                try:
                    with Image.open(f) as im:
                        im.verify()
                except Exception as e:                           # noqa: BLE001 - any unreadable file
                    unread.append(f"{nid}: {a['file']} ({type(e).__name__})")
    per = {}
    for code, ed in eds:
        f = rights.rp(ed)["report"]
        per[code] = L.load(f) if f.exists() else None
    return {"counts": counts, "auto": auto, "unreadable": unread, "rights": per}


def audio_part(ed):
    """The mix as the mix stage judged it: the same loudness and true-peak tolerances (cuesheet.py)."""
    from cuesheet import LOUDNESS_TOL, TP_TOL
    p = L.paths(ed)
    rep = L.load(ed / "audio" / "mix_report.json", {}) if (ed / "audio" / "mix_report.json").exists() else None
    t = L.load(p["timing"], {}) if p["timing"].exists() else {}
    vcfg = L.load(ed / "voice.json", {}) if (ed / "voice.json").exists() else {}
    spend = L.load(ed / "audio" / "voice" / "spend.json", {}) if (ed / "audio" / "voice" / "spend.json").exists() else {}
    out = {"voice": {"provider": vcfg.get("provider"), "voice": vcfg.get("voice"),
                     "spent_usd": round(sum(float(x.get("usd") or 0) for x in spend.get("requests", [])), 2),
                     "requests": len(spend.get("requests", []))}, "mix": None, "problems": []}
    if rep:
        out["mix"] = {k: rep.get(k) for k in ("duration", "lufs", "target_lufs", "true_peak_dbtp", "ceiling_dbtp", "clipped_samples",
                                              "voice_over_music_db")}
        if t and abs(float(rep.get("duration", 0)) - float(t.get("total_duration", 0))) > 0.25:
            out["problems"].append(f"the mix lasts {rep.get('duration')}s, the timing {t.get('total_duration')}s")
        if rep.get("target_lufs") is not None and rep.get("lufs") is not None and abs(rep["lufs"] - rep["target_lufs"]) > LOUDNESS_TOL:
            out["problems"].append(f"the mix is {rep['lufs']} LUFS, made for {rep['target_lufs']}")
        if rep.get("clipped_samples"):
            out["problems"].append(f"{rep['clipped_samples']} clipped sample(s)")
        if rep.get("true_peak_dbtp") is not None and rep.get("ceiling_dbtp") is not None and rep["true_peak_dbtp"] > rep["ceiling_dbtp"] + TP_TOL:
            out["problems"].append(f"true peak {rep['true_peak_dbtp']} dBTP over the {rep['ceiling_dbtp']} ceiling")
    else:
        out["problems"].append("no mix report")
    return out


def video_part(ed, code):
    f = ed / "out" / f"qc.{code}.json"
    if not f.exists():
        return None
    q = L.load(f)
    m = q.get("measurements", {})
    return {"complete": q.get("complete"), "errors": q.get("errors", []), "warnings": q.get("warnings", []),
            "not_checked": q.get("not_checked", []), "loudness": m.get("loudness"),
            "narration_min_share_db": (m.get("narration") or {}).get("min_nrr_db")}


def trace_part(root, eds, imgs):
    p = L.paths(root)
    claims = L.load(p["claims"], {"claims": []}).get("claims", [])
    sources = {s["id"]: s for s in L.load(p["sources"], {"sources": []}).get("sources", [])}
    rows = []
    boards = {code: L.load(L.paths(ed)["storyboard"], {}).get("scenes", []) if L.paths(ed)["storyboard"].exists() else [] for code, ed in eds}
    verdict = {}
    for code, rep in imgs["rights"].items():
        for a in (rep or {}).get("images", []) + (rep or {}).get("footage", []):
            verdict[(code, a["id"])] = "usable" if a["usable"] else "not usable"
    for c in claims:
        row = {"claim": c["id"], "text": c.get("text", ""), "status": L.claim_status(c, sources),
               "sources": [f"{s} (tier {L.source_tier(sources[s])})" if s in sources else f"{s} (missing)" for s in c.get("sources", [])],
               "editions": {}}
        for code, scenes in boards.items():
            hit = [s for s in scenes if c["id"] in s.get("claims", [])]
            row["editions"][code] = {"lines": [s["line"] for s in hit], "scenes": [s["scene"] for s in hit],
                                     "images": [f"{i} ({verdict.get((code, i), 'not shown')})" for s in hit for i in s.get("images", [])]}
        rows.append(row)
    return rows


def build(root, codes=None, log=print):
    """Write the report and credits; errors when an edition in `codes` (default: all) is not complete."""
    root = pathlib.Path(root)
    rp = rpaths(root)
    r = L.Result()
    eds = editions(root)
    want = set(codes or [c for c, _ in eds])
    imgs = images_part(root, eds)
    data = {"built_by": BUILT_BY, "title": (L.load(L.paths(root)["outline"], {}).get("title") if L.paths(root)["outline"].exists() else "")
            or L.load(L.paths(root)["topic"], {}).get("topic", ""), "editions": {}, "images": {k: v for k, v in imgs.items() if k != "rights"},
            "trace": trace_part(root, eds, imgs),
            "limits": ["The fact check matches each line's numbers (and, in English, its words) against the claims a person entered "
                       "from the research; it does not show that the research is right.",
                       "Licences are as archives and people stated them; clearances are a person's word. Neither proves an asset "
                       "is free to use: check anything that matters before publishing.",
                       "Automated QC measures the film (length, sound, picture, subtitles, text geometry); it does not judge "
                       "whether an image fits its line, how the voice sounds or whether a word is pronounced right."]}
    for code, ed in eds:
        d = {"script": script_part(root, code, ed), "audio": audio_part(ed), "video": video_part(ed, code),
             "delivery": None}
        dl = ed / "out" / f"delivery.{code}.json"
        if dl.exists():
            m = L.load(dl)
            d["delivery"] = {"complete": m.get("complete"), "film": m.get("film"), "files": len(m.get("files", []))}
        complete = bool(d["delivery"] and d["delivery"]["complete"] and d["video"] and d["video"]["complete"]
                        and not d["audio"]["problems"] and not d["script"]["errors"])
        d["complete"] = complete
        data["editions"][code] = d
        if code in want and not complete:
            why = ("no finished film yet" if not d["delivery"] else "QC is not complete" if not (d["video"] and d["video"]["complete"])
                   else "; ".join(d["audio"]["problems"] + d["script"]["errors"])[:300] or "not complete")
            r.error(f"{code}: not complete ({why})")
        for x in d["script"]["notes"]:
            r.warn(f"{code} script: {x}")
        # credits next to the film
        rep = imgs["rights"].get(code)
        L.write_text(ed / "out" / f"credits.{code}.md", credits_md([(code, rep)]))
    for a in imgs["auto"]:
        if not a["acknowledged"]:
            r.warn(f"image {a['need']} ({a['what']}) was picked automatically and nobody acknowledged it")
    L.save(rp["json"], data)
    L.write_text(rp["md"], report_md(data))
    L.write_text(rp["credits"], credits_md([(c, imgs["rights"].get(c)) for c, _ in eds]))
    r.note(f"reports/final_report.md: {'complete' if r.ok else 'not complete'}; reports/credits.md")
    return r


def credits_md(per):
    out = ["# Credits", "", "Licences are as each archive or person stated them; see the final report's limits.", ""]
    for code, rep in per:
        if not rep:
            out += [f"## {code}", "", "No rights report yet (finish.py render).", ""]; continue
        out += [f"## {code}", ""]
        for title, key in (("Photographs and documents", "images"), ("Film footage", "footage"), ("Music and sound", "audio")):
            items = [a for a in rep.get(key, []) if a.get("usable")]
            if items:
                out += [f"### {title}", ""] + [f"- {a.get('what') or a['id']}: {a.get('attribution') or a.get('credit') or ''} "
                                               f"({a.get('license') or 'licence not stated'}){' ' + a['source'] if a.get('source') else ''}"
                                               + (f"; {a['basis']}" if a.get('cleared') else "") for a in items] + [""]
        if rep.get("maps"):
            out += ["### Map data", ""] + [f"- {m['id']}: {m.get('source')} ({m.get('license') or 'licence not recorded'})" for m in rep["maps"]] + [""]
        if rep.get("narration"):
            out += ["### Narration", "", f"- {rep['narration']['text']}", ""]
    return "\n".join(out) + "\n"


def report_md(d):
    out = [f"# Final report: {d['title']}", ""]
    for code, e in d["editions"].items():
        out += [f"## {code} edition: {'complete' if e['complete'] else 'NOT complete'}", ""]
        v = e["video"]
        if v:
            out.append(f"- QC: {'complete' if v['complete'] else 'not complete'}; {len(v['errors'])} error(s), {len(v['warnings'])} warning(s), "
                       f"not checked: {', '.join(v['not_checked']) or 'nothing'}")
            for x in v["errors"]:
                out.append(f"  - ERROR {x}")
            for x in v["warnings"]:
                out.append(f"  - {x}")
        else:
            out.append("- QC: not run")
        a = e["audio"]
        mix = a["mix"] or {}
        out.append(f"- Sound: {mix.get('lufs')} LUFS (target {mix.get('target_lufs')}), true peak {mix.get('true_peak_dbtp')} dBTP, "
                   f"voice over music {mix.get('voice_over_music_db')} dB" + (f"; problems: {'; '.join(a['problems'])}" if a["problems"] else ""))
        vo = a["voice"]
        out.append(f"- Voice: {vo['provider']} ({vo['voice']}); spent ${vo['spent_usd']:.2f} over {vo['requests']} paid request(s)")
        s = e["script"]
        out.append(f"- Script: {len(s['errors'])} error(s), {len(s['warnings'])} warning(s); claims checked by {s['claim_check']}")
        for x in s["notes"]:
            out.append(f"  - {x}")
        out.append("")
    im = d["images"]
    out += ["## Images", "", "- Needs: " + (", ".join(f"{n} {k}" for k, n in sorted(im["counts"].items())) or "none")]
    for a in im["auto"]:
        out.append(f"- Picked automatically: {a['need']} ({a['what']}, {a['license']}): " + ("acknowledged" if a["acknowledged"] else "NOT acknowledged"))
    for x in im["unreadable"]:
        out.append(f"- Does not open: {x}")
    out += ["", "## Claims, lines, scenes and images", "", "| Claim | Status | Sources | " +
            " | ".join(f"{c} lines / images" for c in d["editions"]) + " |", "|---|---|---|" + "---|" * len(d["editions"])]
    for t in d["trace"]:
        cells = [f"{', '.join(map(str, x['lines'])) or '-'} / {', '.join(x['images']) or '-'}" for x in t["editions"].values()]
        out.append(f"| {t['claim']}: {t['text'][:60].replace('|', '/')} | {t['status']} | {', '.join(t['sources'])} | " + " | ".join(cells) + " |")
    out += ["", "## What this report does not prove", ""] + [f"- {x}" for x in d["limits"]]
    return "\n".join(out) + "\n"


def fingerprint(root, codes=None):
    root = pathlib.Path(root)
    p = L.paths(root)
    files = [p["claims"], p["sources"], p["outline"], p["visuals_dir"] / "assets.json", p["visuals_dir"] / "selection.json",
             pathlib.Path(__file__)]
    for code, ed in editions(root):
        ep = L.paths(ed)
        files += [ep["narration"], ep["storyboard"], ep["timing"], ed / "audio" / "mix_report.json", ed / "voice.json",
                  ed / "audio" / "voice" / "spend.json", ed / "out" / f"qc.{code}.json", ed / "out" / f"delivery.{code}.json",
                  ed / "out" / f"rights.{code}.json"]
    h = hashlib.sha256(json.dumps(sorted(codes or [])).encode())
    for f in files:
        f = pathlib.Path(f)
        h.update(f.name.encode() + (hashlib.sha256(f.read_bytes()).digest() if f.exists() else b"-"))
    rp = rpaths(root)
    h.update(f"{rp['md'].exists()}{rp['credits'].exists()}".encode())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    r = build(a.project)
    print(r.report("report"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
