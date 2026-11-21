#!/usr/bin/env python3
"""Find, license and fetch the image or footage for every storyboard scene, with a designed
fallback for anything that cannot be used.

  python3 visuals.py search --project P [--providers commons,loc] [--refresh]   # candidates per need
  python3 visuals.py select --project P                                         # best free candidate per need
  python3 visuals.py fetch  --project P                                         # download, with retry and resume
  python3 visuals.py run    --project P [--offline]                             # all three
  python3 visuals.py hosts  --project P                                         # which archives are cooling down
  python3 visuals.py acknowledge --project P I003 I007                          # you looked at these automatic picks

Reads   04_scenes/image_needs.json (from storyboard.py), 05_visuals/selection.json (your choices)
Writes  05_visuals/candidates.json, assets.json (one entry per need), visuals.md, credits.md,
        assets/photos/<need>.<ext>, assets/footage/<need>.<ext>,
        photos.json and footage.json (entries marked generated_by visuals.py; other entries are kept)

Choosing: the best-scoring candidate with a free licence is picked unless selection.json says
otherwise. A pick made that way is automatic: the visuals gate is not approved until a person has
looked at each one and chosen it in selection.json or acknowledged it (selection.json
"acknowledged", by `acknowledge`), which the final report records. A selection entry is a candidate id, "fallback", or {"candidate": id, "cleared_by":
"name", "note": "why it is clear"} for a "check" licence (no known restrictions, free use) a
person has cleared. Refused licences (NC, ND, in copyright, none stated) are never used.

Your own files: give the need {"kind": "own", "file": "name.jpg", "license": "...", "credit": "..."}
in the narration; the file goes in assets/photos/. Without a licence and credit it is not used.

Fallback: a need with nothing usable (no free candidate, a failed download, an archive cooling
down) gets a designed card with the need's description, never a stand-in photo. assets.json and
visuals.md list every fallback so it can be replaced. An archive that rate-limits us is left alone
until its cooldown ends (05_visuals/http_state.json); the next run retries what was deferred.
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import archives as A  # noqa: E402
import doclib as L  # noqa: E402

GEN = "visuals.py"
KIND_TO_PHOTO = {"photo": "photo", "doc": "doc", "paper": "paper", "color": "color", "map": "photo", "ai": "photo", "own": "photo"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif")
VIDEO_EXT = (".webm", ".ogv", ".ogg", ".mp4", ".mov", ".mkv", ".mpg", ".mpeg")


Offline = A.Offline


def vpaths(proj):
    p = L.paths(proj)
    d = p["visuals_dir"]
    return {**p, "candidates": d / "candidates.json", "selection": d / "selection.json", "assets": d / "assets.json",
            "visuals_md": d / "visuals.md", "credits_md": d / "credits.md", "http_state": d / "http_state.json",
            "cache": d / "cache", "photos_json": p["proj"] / "photos.json", "footage_json": p["proj"] / "footage.json"}


def make_http(proj, offline=False, **kw):
    p = vpaths(proj)
    h = A.Http(state_path=p["http_state"], cache_dir=p["cache"], **kw)
    if offline:
        h.opener = h._offline
    return h


def media_of(need):
    return "video" if need.get("kind") == "footage" else "image"


# ------------------------------------------------------------------------------------- scoring

def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


def score(c, need):
    pol = c["license"]["policy"]
    if pol == "refuse":
        return 0.0
    q = _words(need.get("query") or need.get("what"))
    text = _words(f"{c.get('title')} {c.get('description')}")
    rel = len(q & text) / max(1, len(q))
    side = max(c.get("width") or 0, c.get("height") or 0)
    res = 0.5 if not side else min(1.0, side / 1920)
    if side and side < 800:
        res *= 0.3
    kind = 1.0 if c["media"] == media_of(need) else 0.0
    lic = 1.0 if pol == "free" else 0.35
    svg = 0.5 if "svg" in (c.get("mime") or "") else 1.0
    return round((0.45 * rel + 0.25 * res + 0.15 * lic + 0.15 * kind) * svg, 4)


# -------------------------------------------------------------------------------------- stages

def load_needs(proj):
    p = vpaths(proj)
    if not p["image_needs"].exists():
        raise SystemExit("no 04_scenes/image_needs.json: run storyboard.py (or docpipe.py run) first")
    return L.load(p["image_needs"]).get("images", [])


def search(proj, http=None, providers=None, limit=8, refresh=False, log=print):
    """Ask the archives for candidates, need by need, stopping at the first archive that offers
    enough free ones. Archives that rate-limit us are skipped for the rest of the run."""
    p = vpaths(proj)
    http = http or make_http(proj)
    order = providers or L.load(p["topic"], {}).get("archives") or A.DEFAULT_ORDER
    provs = []
    for name in order:
        cls = A.PROVIDERS.get(name)
        if not cls:
            log(f"unknown archive {name!r}; known: {', '.join(A.PROVIDERS)}"); continue
        pv = cls(http)
        if not pv.available():
            log(f"{name}: skipped, set {cls.key_env} to use it"); continue
        provs.append(pv)
    cands = L.load(p["candidates"], {"needs": {}})
    blocked = set()
    for need in load_needs(proj):
        nid = need["id"]
        if need.get("kind") == "own" or need.get("file"):
            continue
        if nid in cands["needs"] and cands["needs"][nid].get("candidates") and not refresh:
            continue
        found, notes = [], []
        media = media_of(need)
        if need.get("commons"):
            title = need["commons"] if need["commons"].startswith("File:") else "File:" + need["commons"]
            try:
                found = A.Commons(http).lookup(title)
                notes.append("named Commons file" if found else f"{title} is not on Commons")
            except (A.RateLimited, Offline) as e:
                notes.append(str(e))
            except Exception as e:
                notes.append(f"commons: {type(e).__name__}: {str(e)[:120]}")
            for c in found:
                c["score"] = 1.0 if c["license"]["policy"] != "refuse" else 0.0
            cands["needs"][nid] = {"query": title, "media": c["media"] if found else media, "candidates": found,
                                   "notes": notes, "named": True}
            log(f"{nid}: {title} " + (f"[{found[0]['license']['label']}]" if found else "not found"))
            continue
        query = need.get("commons", "").removeprefix("File:") or need.get("query") or need.get("what") or ""
        for pv in provs:
            if pv.name in blocked or media not in pv.media:
                continue
            try:
                got = pv.search(query, media=media, limit=limit)
            except A.RateLimited as e:
                blocked.add(pv.name); notes.append(str(e)); log(f"{nid}: {e}"); continue
            except Offline:
                blocked.add(pv.name); notes.append(f"{pv.name}: offline"); continue
            except Exception as e:                       # one archive failing must not stop the others
                notes.append(f"{pv.name}: {type(e).__name__}: {str(e)[:120]}"); continue
            for c in got:
                c["score"] = score(c, need)
            found += got
            if sum(1 for c in got if c["license"]["policy"] == "free" and c["score"] > 0.3) >= 3:
                break
        found.sort(key=lambda c: -c["score"])
        cands["needs"][nid] = {"query": query, "media": media, "candidates": found, "notes": notes}
        free = sum(1 for c in found if c["license"]["policy"] == "free")
        log(f"{nid}: {len(found)} candidates ({free} free) for {query!r}")
    L.save(p["candidates"], cands)
    return cands


def select(proj):
    p = vpaths(proj)
    cands = L.load(p["candidates"], {"needs": {}})["needs"]
    sel = L.load(p["selection"], {})
    picks = {}
    for need in load_needs(proj):
        nid = need["id"]
        if need.get("kind") == "own" or need.get("file"):
            picks[nid] = {"own": True}; continue
        choice = sel.get(nid)
        pool = {c["id"]: c for c in cands.get(nid, {}).get("candidates", [])}
        if choice == "fallback":
            picks[nid] = {"fallback": "chosen in selection.json"}; continue
        if choice:
            cid = choice if isinstance(choice, str) else choice.get("candidate")
            c = pool.get(cid)
            if not c:
                picks[nid] = {"fallback": f"selection.json names {cid!r}, which is not a candidate"}; continue
            pol = c["license"]["policy"]
            if pol == "refuse":
                picks[nid] = {"fallback": f"{cid} has a refused licence ({c['license']['label']})"}; continue
            if pol == "check" and not (isinstance(choice, dict) and choice.get("cleared_by")):
                picks[nid] = {"fallback": f"{cid} needs clearing: add cleared_by and a note in selection.json"}; continue
            picks[nid] = {"candidate": c, "cleared": choice if isinstance(choice, dict) else None}
            continue
        free = [c for c in pool.values() if c["license"]["policy"] == "free" and c["score"] > 0]
        if free:
            picks[nid] = {"candidate": max(free, key=lambda c: c["score"]), "auto": True}
        else:
            why = "no free candidate" if pool else ("no candidates yet" + (": " + "; ".join(cands.get(nid, {}).get("notes", [])) if cands.get(nid, {}).get("notes") else ""))
            picks[nid] = {"fallback": why}
    return picks


def _ext(c):
    path = urllib.parse.urlsplit(c["media_url"]).path.lower()
    ext = pathlib.Path(path).suffix
    if c["media"] == "video":
        return ext if ext in VIDEO_EXT else ".webm"
    return ext if ext in IMAGE_EXT else ".jpg"


def fallback_for(need, reason):
    title = need.get("what") or need.get("query") or "image"
    return {"type": "card", "title": title, "reason": reason}


def source_record(dst):
    return dst.with_name(f".{dst.name}.source.json")


def place(http, c, dst):
    """Put candidate c's media at dst. A file there is reused only if its source record names this
    very candidate; otherwise it and its record are removed first, so a failed download leaves no
    file at all rather than the previous pick under the new pick's credit and licence. Earlier
    picks for the same need under another extension (files with a source record) go too; files
    without a record (yours) are never touched."""
    rec = source_record(dst)
    current = rec.exists() and L.load(rec, {}).get("candidate") == c["id"] and dst.exists()
    nid = dst.stem
    for old in dst.parent.glob(f"{nid}.*"):
        orec = source_record(old)
        if old.name != dst.name and orec.exists() and not old.name.endswith((".part", ".json")):
            old.unlink(); orec.unlink()
    if current:
        return dst
    for f in (dst, rec, dst.with_name(dst.name + ".part")):
        if f.exists():
            f.unlink()
    http.download(c["media_url"], dst)
    L.save(rec, {"candidate": c["id"], "media_url": A.strip_secrets(c["media_url"]), "license": c["license"]["label"],
                 "attribution": c["attribution"]})
    return dst


def fetch(proj, http=None, picks=None, log=print):
    p = vpaths(proj)
    http = http or make_http(proj)
    picks = picks if picks is not None else select(proj)
    manifest = {}
    for need in load_needs(proj):
        nid = need["id"]
        pk = picks.get(nid, {"fallback": "not selected"})
        base = {"need": nid, "scene": need.get("scene"), "line": need.get("line"), "what": need.get("what", ""),
                "kind": need.get("kind", "photo"), "media": media_of(need)}
        if pk.get("own"):
            f = p["proj"] / "assets" / "photos" / need.get("file", "")
            if not need.get("file") or not f.exists():
                manifest[nid] = {**base, "status": "fallback", "fallback": fallback_for(need, f"own file {need.get('file')!r} not in assets/photos")}
            elif not (need.get("license") and need.get("credit")):
                manifest[nid] = {**base, "status": "fallback", "fallback": fallback_for(need, "own file has no licence and credit in the narration")}
            else:
                # the user's own statement of rights, recorded as given: they answer for it
                lic = {"code": "OWN", "label": need["license"], "version": "", "url": "", "policy": "own", "raw": need["license"]}
                manifest[nid] = {**base, "status": "own", "file": need["file"], "provider": "own",
                                 "license": lic, "credit": need["credit"], "attribution": f"{need['credit']} ({need['license']})"}
            continue
        if "fallback" in pk:
            manifest[nid] = {**base, "status": "fallback", "fallback": fallback_for(need, pk["fallback"])}
            continue
        c = pk["candidate"]
        sub = "footage" if c["media"] == "video" else "photos"
        fname = f"{nid}{_ext(c)}"
        dst = p["proj"] / "assets" / sub / fname
        entry = {**base, "candidate": c["id"], "provider": c["provider"], "license": c["license"],
                 "credit": c.get("creator") or A.PROVIDER_NAMES.get(c["provider"], c["provider"]),
                 "source": c.get("page_url", ""), "attribution": c["attribution"], "title": c.get("title", ""),
                 "file": fname, "media": c["media"], "auto": bool(pk.get("auto")), "cleared": pk.get("cleared")}
        try:
            place(http, c, dst)
            manifest[nid] = {**entry, "status": "ok"}
            log(f"{nid}: {fname}  [{c['license']['label']}]")
        except A.RateLimited as e:
            manifest[nid] = {**entry, "status": "deferred", "fallback": fallback_for(need, str(e))}
            log(f"{nid}: deferred, {e}")
        except Offline:
            manifest[nid] = {**entry, "status": "deferred", "fallback": fallback_for(need, "offline")}
        except Exception as e:
            manifest[nid] = {**entry, "status": "fallback", "fallback": fallback_for(need, f"download failed: {type(e).__name__}: {str(e)[:120]}")}
            log(f"{nid}: download failed ({e}); using a fallback card")
    for nid in write_project_files(proj, manifest):
        manifest[nid]["shadowed"] = True
    L.save(p["assets"], {"generated_by": GEN, "assets": manifest})
    return manifest


def write_project_files(proj, manifest):
    """Merge into photos.json and footage.json without touching entries this tool did not write.
    Returns the need ids whose download is shadowed by an entry the user wrote with the same id."""
    p = vpaths(proj)
    shadowed = []
    look = L.load(p["topic"], {}).get("look", "wall")
    grade = "bw" if look in ("wall", "slate") else "natural"
    for key, media, sub in (("photos_json", "image", "photos"), ("footage_json", "video", "footage")):
        cur = L.load(p[key], {"grade": grade, sub: []}) if key == "photos_json" else L.load(p[key], {"footage": []})
        items = cur.setdefault(sub, [])
        mine = {e["id"] for e in items if e.get("generated_by") == GEN}
        theirs = {e["id"] for e in items if e.get("generated_by") != GEN}
        items[:] = [e for e in items if e.get("generated_by") != GEN]
        for nid, a in manifest.items():
            if a.get("status") not in ("ok", "own") or a.get("media", "image") != media:
                continue
            if nid in theirs:
                shadowed.append(nid)                      # an entry the user wrote wins; check() says so
                continue
            items.append({"id": nid, "file": a["file"], "kind": KIND_TO_PHOTO.get(a["kind"], "photo"), "what": a["what"],
                          "credit": a.get("credit", ""), "license": a["license"]["label"], "license_url": a["license"].get("url", ""),
                          "source": a.get("source", ""), "attribution": a.get("attribution", ""),
                          "license_ok": a["license"]["policy"] in ("free", "own") or bool(a.get("cleared")), "generated_by": GEN})
        if items or mine or p[key].exists():
            L.save(p[key], cur)
    return shadowed


def check(proj):
    """Summarise assets.json into a Result and write visuals.md and credits.md."""
    p = vpaths(proj)
    r = L.Result()
    man = L.load(p["assets"], {"assets": {}})["assets"]
    counts = {}
    for nid, a in man.items():
        counts[a["status"]] = counts.get(a["status"], 0) + 1
        if a["status"] == "fallback":
            r.warn(f"{nid} ({a['what']}): fallback card, {a['fallback']['reason']}")
        elif a["status"] == "deferred":
            r.warn(f"{nid} ({a['what']}): deferred, {a['fallback']['reason']}; the next run retries it")
        elif a["status"] == "own":
            r.note(f"{nid}: your own file, rights as you stated them: {a['license']['label']}")
        elif a.get("cleared"):
            r.note(f"{nid}: {a['license']['label']} cleared by {a['cleared'].get('cleared_by')}")
        if a.get("auto") and a["status"] == "ok":
            r.note(f"{nid} ({a['what']}): picked automatically ({a['license']['label']}); look at it, then choose it in "
                   "selection.json or acknowledge it (visuals.py acknowledge) before approving")
        if a.get("shadowed"):
            r.warn(f"{nid}: photos.json or footage.json already has an entry {nid} you wrote; yours is used and the "
                   f"download ({a.get('file')}) is not. Rename one of them if both should appear")
    r.note("visuals: " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no needs"))
    r.partial = bool(counts.get("deferred"))
    L.write_text(p["visuals_md"], render_md(man))
    L.write_text(p["credits_md"], render_credits(man, user_entries(p)))
    return r


def user_entries(p):
    """The photos.json / footage.json entries written by hand (not by this tool), by id: where one
    shadows a download, it is what the film uses and credits (rights.py), so credits.md says the same."""
    out = {}
    for key, sub in (("photos_json", "photos"), ("footage_json", "footage")):
        if p[key].exists():
            out.update({e["id"]: e for e in L.load(p[key], {}).get(sub, []) if e.get("id") and e.get("generated_by") != GEN})
    return out


def render_md(man):
    out = ["# Visuals", "", "Generated by visuals.py. Change a choice in selection.json, then run it again.", "",
           "| Need | Scene | What | Status | Source | Licence |", "|---|---|---|---|---|---|"]
    for nid, a in man.items():
        src = a.get("candidate") or a.get("file") or ""
        lic = a.get("license", {}).get("label", "") if a.get("license") else ""
        st = a["status"] + (f": {a['fallback']['reason']}" if a.get("fallback") else "")
        out.append(f"| {nid} | {a.get('scene', '')} | {a['what']} | {st} | {src} | {lic} |")
    return "\n".join(out) + "\n"


def render_credits(man, theirs=None):
    theirs = theirs or {}
    used = [a for a in man.values() if a["status"] in ("ok", "own")]
    out = ["# Image and footage credits", ""]

    def line(a):
        e = theirs.get(a["need"]) if a.get("shadowed") else None
        if e:                                          # the entry written in photos.json is what the film credits
            text = e.get("attribution") or " · ".join(x for x in (e.get("what"), e.get("credit"), e.get("license")) if x)
            return f"- {a['need']}: {text} (as written in photos.json)"
        return f"- {a['need']}: {a['attribution']}"
    out += [line(a) for a in used] or ["- none yet"]
    fb = [a for a in man.values() if a["status"] in ("fallback", "deferred")]
    if fb:
        out += ["", "## Shown as designed cards (no image used)", ""] + [f"- {a['need']}: {a['what']}" for a in fb]
    return "\n".join(out) + "\n"


def auto_picks(proj):
    """[(need id, what, licence)] of images the stage chose by itself (best score, no selection.json
    entry) that nobody has acknowledged yet. The visuals gate is not approved while any remain."""
    p = vpaths(proj)
    man = L.load(p["assets"], {}).get("assets", {}) if p["assets"].exists() else {}
    sel = L.load(p["selection"], {}) if p["selection"].exists() else {}
    ack = set(sel.get("acknowledged", []))
    return [(nid, a.get("what", ""), (a.get("license") or {}).get("label", "")) for nid, a in sorted(man.items())
            if a.get("auto") and a.get("status") == "ok" and nid not in ack and nid not in sel]


def acknowledge(proj, ids, log=print):
    """Record that a person looked at these automatic picks and keeps them (selection.json "acknowledged")."""
    p = vpaths(proj)
    man = L.load(p["assets"], {}).get("assets", {}) if p["assets"].exists() else {}
    unknown = [i for i in ids if i not in man]
    if unknown:
        raise SystemExit(f"no image need {', '.join(unknown)} in 05_visuals/assets.json")
    sel = L.load(p["selection"], {}) if p["selection"].exists() else {}
    sel["acknowledged"] = sorted(set(sel.get("acknowledged", [])) | set(ids))
    L.save(p["selection"], sel)
    log(f"acknowledged {', '.join(ids)}; run docpipe.py again, then approve visuals")


def run(proj, http=None, offline=False, providers=None, log=print):
    if not vpaths(proj)["image_needs"].exists():
        r = L.Result(); r.error("no 04_scenes/image_needs.json: run the scenes stage first"); return r
    http = http or make_http(proj, offline=offline)
    search(proj, http, providers, log=log)
    fetch(proj, http, log=log)
    return check(proj)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("search", "select", "fetch", "run", "hosts", "acknowledge"):
        s = sub.add_parser(name); s.add_argument("--project", required=True)
        if name == "acknowledge":
            s.add_argument("needs", nargs="+", help="image need ids whose automatic pick you looked at and keep")
        if name in ("search", "run"):
            s.add_argument("--providers", default="", help="comma-separated, in order (default: topic.json archives or all)")
        if name == "search":
            s.add_argument("--refresh", action="store_true")
        if name in ("run", "fetch", "search"):
            s.add_argument("--offline", action="store_true", help="use cached searches only; no network")
    a = ap.parse_args()
    if a.cmd == "acknowledge":
        acknowledge(a.project, a.needs); return
    provs = [x for x in getattr(a, "providers", "").split(",") if x] or None
    if a.cmd == "hosts":
        st = L.load(vpaths(a.project)["http_state"], {"cooling": {}})
        import time
        for h, until in st["cooling"].items():
            left = until - time.time()
            print(f"{h:<32} " + (f"cooling for {left / 60:.0f} more min" if left > 0 else "ok"))
        return
    if a.cmd == "search":
        search(a.project, make_http(a.project, a.offline), provs, refresh=a.refresh)
    elif a.cmd == "select":
        for nid, pk in select(a.project).items():
            print(f"{nid}: " + (pk["candidate"]["id"] if "candidate" in pk else "own file" if pk.get("own") else f"fallback ({pk['fallback']})"))
    elif a.cmd == "fetch":
        fetch(a.project, make_http(a.project, a.offline))
        print(check(a.project).report("visuals"))
    else:
        r = run(a.project, offline=a.offline, providers=provs)
        print(r.report("visuals"))
        sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
