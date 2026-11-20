#!/usr/bin/env python3
"""An edition's subtitles, SRT and WebVTT, from its narration timing.

  python3 subtitles.py --project P/editions/hi            # out/subtitles.hi.srt, out/subtitles.hi.vtt, audio/subs.json
  python3 subtitles.py --project P/editions/en --force    # replace subtitle files you edited (kept as .bak)

Reads   audio/timing.json (narrate.py, or build_narration.py) and nothing else; never writes it
Writes  out/subtitles.<lang>.srt, out/subtitles.<lang>.vtt, audio/subs.json (every cue, with its line,
        its timing source, reading speed and the hashes of the files written)

Each cue shows the line's displayed text (the script's text, not the spoken form), cut into
cues at sentence ends (. ! ? । ॥), then at commas, and by length: at most 2 lines of 42 characters
and 7 seconds. Lines break at the most even point, after punctuation where possible. A cue starts
on its first word and ends on its last; a short cue is held longer for reading (1 s at least,
about 17 characters a second) without running into the next. Cues never overlap: there is at
least 80 ms between them. Cues never cross from one narration line to the next.

Timing, honestly labelled: "voice" where the voice gave the word times (ElevenLabs, the mock),
"voice-approx" for words read differently from how they are shown (a year, a number) placed
on the voice's times, and "estimate" where the times come from the language's timing rules
(espeak, Sarvam, manual or edited lines, a timing file without words). subs.json records the
source of every cue and the WebVTT file says how many cues are estimated.

Resume: the same timing and settings write nothing. A subtitle file that subtitles.py did not
write, or that you changed since, is never replaced without --force, which keeps it as .bak.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "subtitles.py"
MAX_LINE, MAX_LINES, MAX_DUR, MIN_DUR = 42, 2, 7.0, 1.0
CPS, CPS_WARN, GAP = 17.0, 21.0, 0.08
SENTENCE_END = re.compile(r"[.!?।॥…]['\"’”)]*$")
CLAUSE_END = re.compile(r"[,;:—–]['\"’”)]*$")


def sp(proj):
    p = L.paths(proj)
    code = p["lang"] or "en"
    out = p["proj"] / "out"
    return {**p, "code": code, "srt": out / f"subtitles.{code}.srt", "vtt": out / f"subtitles.{code}.vtt",
            "subs": p["proj"] / "audio" / "subs.json"}


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def line_words(seg):
    """[(word, start, end, source)] for one narration line."""
    from wordtimes import timed_words, words_with_times
    tw = timed_words(seg)
    if tw is not None:
        return tw
    ws = words_with_times(seg)                         # a timing file without words: letter-share estimate
    out = []
    for k, (w, a) in enumerate(ws):
        b = ws[k + 1][1] if k + 1 < len(ws) else seg["end"]
        out.append((w, a, max(a, b - 0.02), "estimate"))
    return out


def text_of(words):
    return " ".join(w for w, *_ in words)


def split_line(words):
    """Cut one narration line's words into cues: sentence ends first, then clauses, then length."""
    cues, cur = [], []
    limit = MAX_LINE * MAX_LINES
    for i, w in enumerate(words):
        if cur and (len(text_of(cur + [w])) > limit or w[2] - cur[0][1] > MAX_DUR):
            cut = max((k for k in range(1, len(cur)) if CLAUSE_END.search(cur[k - 1][0]) and len(text_of(cur[:k])) >= 16),
                      default=None)
            if cut:
                cues.append(cur[:cut]); cur = cur[cut:]
            else:
                cues.append(cur); cur = []
        cur.append(w)
        if SENTENCE_END.search(w[0]) and len(text_of(cur)) >= 12 and i + 1 < len(words):
            cues.append(cur); cur = []
    if cur:
        if cues and len(text_of(cur)) < 8 and len(text_of(cues[-1] + cur)) <= limit:
            cues[-1] = cues[-1] + cur                  # never leave a word or two on its own
        else:
            cues.append(cur)
    return cues


def wrap(words):
    """One or two display lines, as even as possible, breaking after punctuation where it can."""
    txt = text_of(words)
    if len(txt) <= MAX_LINE or len(words) < 2:
        return [txt]
    best = None
    for k in range(1, len(words)):
        a, b = text_of(words[:k]), text_of(words[k:])
        cost = max(len(a), len(b)) + (0 if re.search(r"[,;:.!?।—–]['\"’”)]*$", words[k - 1][0]) else 6)
        if best is None or cost < best[0]:
            best = (cost, [a, b])
    return best[1]


def build_cues(timing):
    segs = sorted(timing.get("segments", []), key=lambda s: s["start"])
    total = timing["total_duration"]
    cues = []
    for seg in segs:
        for ws in split_line(line_words(seg)):
            srcs = {w[3] for w in ws}
            src = "estimate" if "estimate" in srcs else "voice-approx" if "voice-approx" in srcs else "voice"
            cues.append({"line": seg["id"], "scene": seg.get("scene", ""), "t0": ws[0][1], "t1": max(ws[-1][2], ws[0][1] + 0.3),
                         "lines": wrap(ws), "timing": src})
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["t0"] if i + 1 < len(cues) else total
        chars = len(" ".join(c["lines"]))
        want = min(MAX_DUR, max(MIN_DUR, chars / CPS))
        c["t1"] = max(c["t1"], min(c["t0"] + want, nxt - GAP))     # held for reading, never into the next
        c["t1"] = min(c["t1"], nxt - GAP, total)
        c["t1"] = max(c["t1"], c["t0"] + 0.2)
        c["t0"], c["t1"] = round(c["t0"], 3), round(c["t1"], 3)
        c["cps"] = round(chars / max(0.001, c["t1"] - c["t0"]), 1)
    for i, c in enumerate(cues, 1):
        c["n"] = i
    return cues


def ts(x, sep):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def to_srt(cues):
    out = []
    for c in cues:
        out += [str(c["n"]), f"{ts(c['t0'], ',')} --> {ts(c['t1'], ',')}", *c["lines"], ""]
    return "\n".join(out)


TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
TIMING_LINE = re.compile(rf"^\s*{TIME}\s*-->\s*{TIME}(?:\s+.*)?$")


def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text):
    """(cues, problems) from SRT text. A cue is a block of an index line, a timing line and its text
    lines, blocks parted by blank lines; text that only looks like an index ("1903") stays text.
    cues: [{"n", "t0", "t1", "lines"}]; problems: what is malformed, by block."""
    return _parse_blocks(text, vtt=False)


def parse_vtt(text):
    """(cues, problems) from WebVTT text: the WEBVTT header, NOTE and STYLE blocks skipped, optional
    cue identifiers allowed."""
    return _parse_blocks(text, vtt=True)


def _parse_blocks(text, vtt):
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = [b.split("\n") for b in re.split(r"\n[ \t]*\n", text) if b.strip()]
    cues, problems = [], []
    if vtt:
        if not blocks or not blocks[0][0].startswith("WEBVTT"):
            problems.append("the file does not start with WEBVTT")
        else:
            blocks = blocks[1:] if not any(TIMING_LINE.match(x) for x in blocks[0]) else blocks
    for k, lines in enumerate(blocks, 1):
        if vtt and lines[0].split(" ")[0] in ("NOTE", "STYLE", "REGION"):
            continue
        at = next((i for i, x in enumerate(lines) if TIMING_LINE.match(x)), None)
        if at is None:
            problems.append(f"block {k}: no timing line ({lines[0][:40]!r})"); continue
        head = lines[:at]
        if not vtt and (len(head) != 1 or not head[0].strip().isdigit()):
            problems.append(f"block {k}: the line before the timing is not a cue number ({' / '.join(head)[:40]!r})")
        if vtt and len(head) > 1:
            problems.append(f"block {k}: more than one line before the timing")
        m = TIMING_LINE.match(lines[at])
        t0, t1 = _secs(*m.groups()[:4]), _secs(*m.groups()[4:])
        body = lines[at + 1:]
        while body and not body[-1].strip():
            body.pop()
        if t1 <= t0:
            problems.append(f"block {k}: ends at or before it starts")
        if not any(x.strip() for x in body):
            problems.append(f"block {k}: no text")
        n = int(head[0]) if (not vtt and len(head) == 1 and head[0].strip().isdigit()) else len(cues) + 1
        cues.append({"n": n, "id": head[0] if head else "", "t0": round(t0, 3), "t1": round(t1, 3), "lines": body})
    return cues, problems


def to_vtt(cues, code, counts):
    head = ["WEBVTT", "", "NOTE", f"Language: {code}. Word timing: " +
            ", ".join(f"{n} cue(s) {k}" for k, n in sorted(counts.items())) +
            ". 'estimate' cues are placed by the language's timing rules, not by the voice.", ""]
    out = []
    for c in cues:
        out += [f"L{c['line']}-{c['n']}", f"{ts(c['t0'], '.')} --> {ts(c['t1'], '.')}", *c["lines"], ""]
    return "\n".join(head + out)


def build(proj, force=False, log=print):
    p = sp(proj)
    r = L.Result()
    if not p["timing"].exists():
        r.error("no audio/timing.json: build the narration first (narrate.py)"); return r
    timing = L.load(p["timing"])
    tag = timing.get("lang")
    if (p["lang"] and tag != p["lang"]) or (not p["lang"] and tag not in (None, "en")):
        r.error(f"audio/timing.json is the {tag or 'untagged'} voice; this is the {p['code']} edition"); return r
    if not timing.get("segments"):
        r.error("audio/timing.json has no lines"); return r
    settings = {"max_line": MAX_LINE, "max_lines": MAX_LINES, "max_dur": MAX_DUR, "min_dur": MIN_DUR, "cps": CPS, "gap": GAP}
    key = hashlib.sha256(json.dumps({"by": BUILT_BY, "lang": p["code"], "settings": settings,
                                     "timing": L.load(p["timing"])}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    old = L.load(p["subs"], {}) if p["subs"].exists() else {}
    if old.get("lang") and old["lang"] != p["code"] and not force:
        r.error(f"audio/subs.json is the {old['lang']} edition's; this is {p['code']} (--force replaces it, keeping a .bak)"); return r
    recorded = old.get("files", {}) if old.get("built_by") == BUILT_BY else {}
    theirs = []
    for f in (p["srt"], p["vtt"]):
        rel = str(f.relative_to(p["proj"]))
        if f.exists() and recorded.get(rel) != sha_bytes(f.read_bytes()):
            theirs.append(f)
    if not theirs and old.get("input_hash") == key and all(f.exists() for f in (p["srt"], p["vtt"])):
        r.note(f"{p['code']} subtitles are up to date ({len(old.get('cues', []))} cues); nothing written"); return r
    if theirs:
        if not force:
            r.error(", ".join(str(f.relative_to(p["proj"])) for f in theirs) + " was not written by subtitles.py or was "
                    "changed since: it is yours and left as it is (--force replaces it, keeping a .bak)"); return r
        for f in theirs:
            shutil.copyfile(f, f.with_name(f.name + ".bak"))
            r.note(f"your {f.name} kept as {f.name}.bak")
    cues = build_cues(timing)
    counts = {}
    for c in cues:
        counts[c["timing"]] = counts.get(c["timing"], 0) + 1
    srt, vtt = to_srt(cues), to_vtt(cues, p["code"], counts)
    files = {}
    for f, text in ((p["srt"], srt), (p["vtt"], vtt)):
        f.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_bytes(data); tmp.replace(f)
        files[str(f.relative_to(p["proj"]))] = sha_bytes(data)
    L.save(p["subs"], {"lang": p["code"], "built_by": BUILT_BY, "input_hash": key, "settings": settings,
                       "timing_counts": counts, "files": files, "cues": cues})
    for c in cues:
        if c["cps"] > CPS_WARN:
            r.warn(f"cue {c['n']} (line {c['line']}): {c['cps']} characters a second is fast to read; "
                   f"a shorter line or a longer pause would help")
    est = counts.get("estimate", 0)
    r.note(f"{p['code']} subtitles: {len(cues)} cues -> {p['srt'].relative_to(p['proj'])}, {p['vtt'].relative_to(p['proj'])}"
           + (f"; {est} cue(s) on estimated word times" if est else "; word times from the voice"))
    log(f"{p['code']} subtitles: {len(cues)} cues; " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    r = build(a.project, a.force)
    print(r.report(f"subtitles ({sp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
