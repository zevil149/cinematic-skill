#!/usr/bin/env python3
"""Research store for a documentary: every source, and every claim the film may state, each claim
tied to the sources that support it. The narration may only state what is here (narration.py
checks every line against it), so nothing reaches the film without a source behind it.

  python3 research.py add-source --project P --url https://www.loc.gov/item/... --title "..." \\
        --publisher "Library of Congress" --type archive [--author ...] [--date 1903-12-17]
  python3 research.py add-source --project P --title "The Wright Brothers" --author "David McCullough" \\
        --publisher "Simon & Schuster" --date 2015 --type book          # a book: no url, a citation
  python3 research.py add-claim --project P --text "The first flight lasted 12 seconds." \\
        --source S1 --source S2 [--quote "excerpt from the source"] [--disputed] [--note "..."]
  python3 research.py check --project P [--check-urls]                  # also writes research.md
  python3 research.py list --project P

Files: 01_research/sources.json, 01_research/claims.json (edit them by hand too), research.md.

Source tiers (set "tier" on a source to override):
  1  primary or institutional: archives, museums, government, universities, journals
  2  secondary: books, reputable news, reference works
  3  leads only: Wikipedia, wikis, social media, blogs. Never enough on their own.

Claim status:
  supported      at least one tier 1 source, or two independent tier 2 sources for a number or date
  single-source  a number or date resting on one secondary source: find a second
  weak           only tier 3 sources
  disputed       sources disagree (set --disputed): the narration must hedge ("about", "reported")
  unsupported    no valid source: the narration may not use it
"""
import argparse
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

TYPES = sorted(L.TIER_TYPES)


def load_research(proj):
    p = L.paths(proj)
    sources = L.load(p["sources"], {"sources": []})
    claims = L.load(p["claims"], {"claims": []})
    return p, sources, claims


def _next_id(items, prefix):
    n = [int(i["id"][len(prefix):]) for i in items if str(i.get("id", "")).startswith(prefix) and i["id"][len(prefix):].isdigit()]
    return f"{prefix}{max(n, default=0) + 1}"


def add_source(proj, url="", title="", publisher="", author="", date="", type="other", notes="", tier=None):
    p, sources, _ = load_research(proj)
    if not (url or title):
        raise SystemExit("a source needs a --url or, for a book or print source, a --title")
    if url:
        for s in sources["sources"]:
            if s.get("url") == url:
                print(f"{s['id']} already holds {url}"); return s["id"]
    s = {"id": _next_id(sources["sources"], "S"), "url": url, "title": title, "publisher": publisher,
         "author": author, "date": date, "type": type, "accessed": L.today() if url else "", "notes": notes}
    if tier:
        s["tier"] = tier
    sources["sources"].append(s)
    L.save(p["sources"], sources)
    print(f"{s['id']}: {title or url}  (tier {L.source_tier(s)}, {L.TIER_NAMES[L.source_tier(s)]})")
    return s["id"]


def add_claim(proj, text, source_ids, quote="", disputed=False, note=""):
    p, sources, claims = load_research(proj)
    known = {s["id"] for s in sources["sources"]}
    missing = [s for s in source_ids if s not in known]
    if missing:
        raise SystemExit(f"unknown source id(s) {missing}; add them with add-source first")
    c = {"id": _next_id(claims["claims"], "C"), "text": text.strip(), "sources": list(source_ids),
         "quote": quote, "disputed": bool(disputed), "notes": note}
    claims["claims"].append(c)
    L.save(p["claims"], claims)
    by_id = {s["id"]: s for s in sources["sources"]}
    print(f"{c['id']}: {L.claim_status(c, by_id)}  {text[:80]}")
    return c["id"]


def url_ok(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "cinematic-film/1.0 research check"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status < 400, str(r.status)
    except urllib.error.HTTPError as e:
        return e.code in (403, 405, 429), str(e.code)     # many archives refuse HEAD or bots; not proof it is gone
    except Exception as e:
        return False, type(e).__name__


def check(proj, check_urls=False, write=True):
    """Validate the research store. Returns a doclib.Result; writes research.md."""
    p, sources, claims = load_research(proj)
    r = L.Result()
    srcs, cls = sources.get("sources", []), claims.get("claims", [])
    by_id = {}
    for s in srcs:
        sid = s.get("id")
        if not sid:
            r.error(f"a source has no id: {s}"); continue
        if sid in by_id:
            r.error(f"source id {sid} is used twice")
        by_id[sid] = s
        if not (s.get("url") or s.get("title")):
            r.error(f"{sid}: needs a url or, for print, a title")
        if s.get("url"):
            if not s["url"].startswith(("http://", "https://")):
                r.error(f"{sid}: url {s['url']!r} is not http(s)")
            if not s.get("accessed"):
                r.warn(f"{sid}: no accessed date")
            if check_urls:
                ok, why = url_ok(s["url"])
                (r.note if ok else r.warn)(f"{sid}: {s['url']} -> {why}")
        elif not (s.get("author") or s.get("publisher")):
            r.warn(f"{sid}: a print source needs an author or publisher to be findable")
    if not cls:
        r.error("no claims yet: research the topic and add-claim each fact the film will state")
    seen, used, status = set(), set(), {}
    for c in cls:
        cid = c.get("id")
        if not cid or cid in seen:
            r.error(f"claim id {cid!r} is missing or used twice"); continue
        seen.add(cid)
        if not c.get("text", "").strip():
            r.error(f"{cid}: empty text")
        bad = [s for s in c.get("sources", []) if s not in by_id]
        if bad:
            r.error(f"{cid}: unknown source id(s) {bad}")
        used.update(c.get("sources", []))
        st = status[cid] = L.claim_status(c, by_id)
        if st == "unsupported":
            r.warn(f"{cid}: UNSUPPORTED, no valid source; the narration may not state it")
        elif st == "weak":
            r.warn(f"{cid}: weak, only tier 3 sources (Wikipedia and the like are leads, not proof)")
        elif st == "single-source":
            r.warn(f"{cid}: single-source number or date; confirm it in a second independent source")
        elif st == "disputed":
            r.warn(f"{cid}: disputed; any line stating it must hedge ('about', 'reported', 'according to')")
    for sid in by_id:
        if sid not in used:
            r.note(f"{sid}: not cited by any claim")
    counts = {k: sum(1 for v in status.values() if v == k) for k in
              ("supported", "single-source", "weak", "disputed", "unsupported")}
    r.note("claims: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    if write:
        L.write_text(p["research_md"], render_md(srcs, cls, status, r))
    return r


def render_md(srcs, cls, status, r):
    by_id = {s["id"]: s for s in srcs}
    out = ["# Research", "", f"{len(cls)} claims from {len(srcs)} sources. Generated by research.py; edit the JSON, not this file.", ""]
    out += ["## Claims", "", "| ID | Status | Claim | Sources |", "|---|---|---|---|"]
    for c in cls:
        cite = ", ".join(c.get("sources", [])) or "none"
        flag = status.get(c["id"], "?")
        flag = f"**{flag.upper()}**" if flag in ("unsupported", "weak") else flag
        out.append(f"| {c['id']} | {flag} | {c.get('text', '').replace('|', '/')} | {cite} |")
    out += ["", "## Sources", "", "| ID | Tier | Source | Accessed |", "|---|---|---|---|"]
    for s in srcs:
        t = L.source_tier(s)
        name = " / ".join(x for x in (s.get("author"), s.get("title"), s.get("publisher"), s.get("date")) if x)
        link = f"[{name or s.get('url')}]({s['url']})" if s.get("url") else name
        out.append(f"| {s['id']} | {t} ({L.TIER_NAMES[t]}) | {link.replace('|', '/')} | {s.get('accessed', '')} |")
    if r.errors or r.warnings:
        out += ["", "## To fix", ""] + [f"- ERROR {e}" for e in r.errors] + [f"- {w}" for w in r.warnings]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add-source")
    s.add_argument("--project", required=True); s.add_argument("--url", default=""); s.add_argument("--title", default="")
    s.add_argument("--publisher", default=""); s.add_argument("--author", default=""); s.add_argument("--date", default="")
    s.add_argument("--type", default="other", choices=TYPES); s.add_argument("--notes", default="")
    s.add_argument("--tier", type=int, choices=(1, 2, 3))
    c = sub.add_parser("add-claim")
    c.add_argument("--project", required=True); c.add_argument("--text", required=True)
    c.add_argument("--source", action="append", default=[], required=True); c.add_argument("--quote", default="")
    c.add_argument("--disputed", action="store_true"); c.add_argument("--note", default="")
    k = sub.add_parser("check"); k.add_argument("--project", required=True); k.add_argument("--check-urls", action="store_true")
    li = sub.add_parser("list"); li.add_argument("--project", required=True)
    a = ap.parse_args()
    if a.cmd == "add-source":
        add_source(a.project, a.url, a.title, a.publisher, a.author, a.date, a.type, a.notes, a.tier)
    elif a.cmd == "add-claim":
        add_claim(a.project, a.text, a.source, a.quote, a.disputed, a.note)
    elif a.cmd == "check":
        r = check(a.project, a.check_urls)
        print(r.report("research"))
        print(f"wrote {L.paths(a.project)['research_md']}")
        sys.exit(0 if r.ok else 1)
    else:
        _, sources, claims = load_research(a.project)
        by_id = {s["id"]: s for s in sources["sources"]}
        for s in sources["sources"]:
            print(f"{s['id']:<4} tier {L.source_tier(s)}  {s.get('title') or s.get('url')}")
        for c in claims["claims"]:
            print(f"{c['id']:<4} {L.claim_status(c, by_id):<13} {c['text'][:90]}  [{', '.join(c['sources'])}]")


if __name__ == "__main__":
    main()
