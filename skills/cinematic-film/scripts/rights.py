#!/usr/bin/env python3
"""The rights of everything an edition's finished film shows or plays, and the credits that go with
them (phase 6.4).

  python3 rights.py check   --project P/editions/hi     # out/rights.<lang>.json, the verdict for every asset used

What counts is what the film uses: the photos and clips its act scenes put on screen (Print and
Footage items, read from the scenes themselves), the maps they draw, and the music and sounds the mix
report says were mixed. An asset that was searched, downloaded or listed but never used is not
credited and cannot block anything.

The policy is the one the pipeline already documents; this module applies it at the end instead of
only advising:
  archive images and clips (05_visuals/assets.json)
             free (public domain, CC0, CC BY, CC BY-SA) as the archive states it: usable, with its
             attribution. A licence that needs clearing ("no known restrictions") is usable only
             with "cleared_by" and a note in selection.json, recorded as your clearance. A refused
             licence (NC, ND, in copyright, none stated) is never usable.
  your own files (a need of kind "own", or a photos.json / footage.json entry with a local file)
             usable with the licence and credit you state; without them, not used.
  entries you wrote in photos.json / footage.json with a source (Commons, a URL)
             judged by the licence they state, the same way; "cleared_by" and "note" on the entry
             clear a licence that needs clearing, and are recorded as your clearance.
  music and sounds (audio/mix_report.json)
             cleared in the production's audio library (audiolib.py), which records who cleared what
             and any override; the mix uses nothing else.
  maps       the boundary data's source from map.json, credited; its licence is recorded when map.json
             gives one ("license", "credit"), and a warning says so when it does not.
  narration  the voice provider and voice (voice.json), or your recordings: credited, nothing to clear.
Everything drawn in code (cards, type, the synthesised bed and effects) needs no rights.

None of this proves an asset is free to use: it records what an archive or a person stated, and who
cleared what. A stated licence can be wrong; check anything that matters before publishing.

An asset that is not usable blocks the act render that would show it (finish.py render) and the
delivery (qc.py). The verdicts, with every licence, attribution and clearance, go into the delivery
manifest, and the credits into the film's closing credits (credits.py).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import archives as A  # noqa: E402
import doclib as L  # noqa: E402

BUILT_BY = "rights.py"


def rp(proj):
    p = L.paths(proj)
    code = p["lang"] or "en"
    v = p["visuals_dir"]
    return {**p, "code": code, "manifest": v / "assets.json", "selection": v / "selection.json",
            "photos_json": p["proj"] / "photos.json", "footage_json": p["proj"] / "footage.json",
            "map_json": p["proj"] / "map.json", "mix_report": p["proj"] / "audio" / "mix_report.json",
            "voice_json": p["proj"] / "voice.json", "voice_manifest": p["proj"] / "audio" / "voice" / "manifest.json",
            "report": p["proj"] / "out" / f"rights.{code}.json"}


def used_in_scenes(proj, total=None):
    """{"image": {key: [acts]}, "video": {key: [acts]}, "maps": n, "unread": {act: why}}: what the act
    scenes put on screen. An act whose scene does not build is listed under "unread", not guessed."""
    import finish
    import review
    from engine import Doc
    p = finish.fp(proj)
    if total is None:
        total = float(L.load(p["timing"])["total_duration"])
    doc = Doc(p["proj"])
    out = {"image": {}, "video": {}, "maps": 0, "unread": {}}
    for n, scene, s, e, _, _ in finish.acts_of(p, total):
        try:
            film = review.load_act(scene).build_film(doc)
        except BaseException as ex:                               # noqa: BLE001 - one broken act does not hide the others
            if not isinstance(ex, Exception) and not isinstance(ex, SystemExit):
                raise
            out["unread"][n] = f"{type(ex).__name__}: {str(ex)[:200]}"
            continue
        for it in film.items:
            inner = it.item if type(it).__name__ == "Parallax" else it
            kind = type(inner).__name__
            if kind in ("Print", "Footage") and inner.t_in < e:
                out["video" if kind == "Footage" else "image"].setdefault(inner.key, []).append(n)
            elif kind == "GeoMap":
                out["maps"] += 1
    return out


def _entry_of(p, key, media):
    f = p["footage_json"] if media == "video" else p["photos_json"]
    data = L.load(f, {}) if f.exists() else {}
    return next((e for e in data.get("footage" if media == "video" else "photos", []) if e.get("id") == key), None)


def verdict(p, key, media):
    """One asset's record: {"id", "media", "what", "license", "policy", "usable", "basis", "credit",
    "attribution", "source", "cleared"}."""
    man = L.load(p["manifest"], {}).get("assets", {}) if p["manifest"].exists() else {}
    a = man.get(key)
    rec = {"id": key, "media": media, "what": "", "license": "", "policy": "", "usable": False, "basis": "",
           "credit": "", "attribution": "", "source": "", "cleared": None}
    entry = _entry_of(p, key, media)
    if entry and entry.get("generated_by") != "visuals.py":
        a = None                                              # an entry you wrote wins over the download (visuals.py says so)
    if a:
        lic = a.get("license") or {}
        rec.update(what=a.get("what", ""), license=lic.get("label", ""), policy=lic.get("policy", ""), credit=a.get("credit", ""),
                   attribution=a.get("attribution", ""), source=a.get("source", ""), cleared=a.get("cleared"),
                   provider=A.PROVIDER_NAMES.get(a.get("provider"), a.get("provider") or "") if a.get("status") != "own" else "")
        if a.get("status") == "own":
            rec.update(usable=bool(a.get("license") and a.get("credit")), basis="your own file, with the licence and credit you stated")
        elif a.get("status") != "ok":
            rec.update(basis=f"no usable download ({a.get('status')}): the scene shows a file the visuals stage did not place")
        elif rec["policy"] == "free":
            rec.update(usable=True, basis=f"free licence as the archive states it ({rec['license']})")
        elif rec["policy"] == "check" and isinstance(a.get("cleared"), dict) and a["cleared"].get("cleared_by"):
            rec.update(usable=True, basis=f"cleared by {a['cleared']['cleared_by']}: {a['cleared'].get('note', '') or 'no note'}")
        elif rec["policy"] == "check":
            rec.update(basis=f"{rec['license']} needs clearing: cleared_by and a note in selection.json")
        else:
            rec.update(basis=f"refused licence ({rec['license']})")
        return rec
    if not entry:
        rec["basis"] = "no rights record: not in assets.json, photos.json or footage.json"
        return rec
    rec.update(what=entry.get("what", ""), credit=entry.get("credit", ""), attribution=entry.get("attribution", ""),
               source=entry.get("source") or entry.get("url") or (f"Wikimedia Commons: {entry['commons']}" if entry.get("commons") else ""),
               license=entry.get("license", ""), provider="Wikimedia Commons" if entry.get("commons") else "")
    from_source = bool(entry.get("commons") or entry.get("url") or entry.get("source"))
    if not from_source:
        ok = bool(entry.get("license") and entry.get("credit"))
        rec.update(policy="own", usable=ok, basis="your own file, with the licence and credit you stated" if ok else
                   "your own file needs a \"license\" and a \"credit\" in its entry (the rights as you state them)")
        return rec
    lic = A.normalize_license(entry.get("license", ""), entry.get("license_url", ""))
    rec.update(policy=lic["policy"], license=entry.get("license") or lic["label"])
    if lic["policy"] == "free":
        needs_credit = lic["code"].startswith("CC-BY")
        if needs_credit and not (entry.get("credit") or entry.get("attribution")):
            rec["basis"] = f"{lic['label']} needs an attribution: add a \"credit\" to the entry"
        else:
            rec.update(usable=True, basis=f"free licence as the entry states it ({lic['label']})")
    elif lic["policy"] == "check" and entry.get("cleared_by") and entry.get("note"):
        rec.update(usable=True, cleared={"cleared_by": entry["cleared_by"], "note": entry["note"]},
                   basis=f"cleared by {entry['cleared_by']}: {entry['note']}")
    elif lic["policy"] == "check":
        rec["basis"] = f"{lic['label']} needs clearing: add \"cleared_by\" and a \"note\" to the entry"
    else:
        rec["basis"] = f"refused licence ({lic['label'] if entry.get('license') else 'no licence stated'})"
    return rec


def audio_assets(p):
    rep = L.load(p["mix_report"], {}) if p["mix_report"].exists() else {}
    out = []
    for a in rep.get("assets", []):
        out.append({"id": a["id"], "media": a.get("kind", "audio"), "what": a.get("title", ""), "license": a.get("license", ""),
                    "policy": "cleared", "usable": bool(a.get("cleared_by")), "credit": a.get("creator", ""),
                    "attribution": a.get("attribution", ""), "source": a.get("source", ""),
                    "cleared": {"cleared_by": a.get("cleared_by"), "override": bool(a.get("override"))},
                    "basis": (f"cleared in the audio library by {a.get('cleared_by')}" + (" (an override of its licence)" if a.get("override") else ""))
                    if a.get("cleared_by") else "not cleared in the audio library"})
    return out


def map_credits(p):
    data = L.load(p["map_json"], {}) if p["map_json"].exists() else {}
    out = []
    for m in data.get("maps", []):
        srcs = [m.get("source")] + ([m["neighbors"].get("source")] if isinstance(m.get("neighbors"), dict) else [])
        out.append({"id": m.get("name", ""), "media": "map", "what": f"map: {m.get('name', '')}", "license": m.get("license", ""),
                    "credit": m.get("credit", ""), "source": ", ".join(s for s in srcs if s), "usable": True,
                    "basis": "boundary data" + (f" under {m['license']}" if m.get("license") else ": no licence recorded in map.json")})
    return out


def narration_credit(p):
    cfg = L.load(p["voice_json"], {}) if p["voice_json"].exists() else {}
    man = L.load(p["voice_manifest"], {}) if p["voice_manifest"].exists() else {}
    segs = man.get("segments", {}).values()
    manual = sum(1 for s in segs if s.get("provider") == "manual" or s.get("audio") == "manual")
    if not cfg and not segs:
        return None
    who = f"{cfg.get('provider', '?')} ({cfg.get('voice', '')})" if cfg else "?"
    return {"provider": cfg.get("provider"), "voice": cfg.get("voice"), "manual_lines": manual,
            "text": who + (f"; {manual} line(s) recorded by hand" if manual else "")}


def check(proj, write=True, log=print):
    """(Result, report): every asset the film uses, with its verdict. Errors for anything not usable."""
    p = rp(proj)
    r = L.Result()
    try:
        used = used_in_scenes(proj)
    except BaseException as e:                                   # noqa: BLE001 - scenes that do not build
        r.error(f"the scenes do not build, so what the film uses cannot be read: {type(e).__name__}: {str(e)[:200]}")
        return r, {}
    images = [dict(verdict(p, k, "image"), acts=sorted(set(v))) for k, v in sorted(used["image"].items())]
    clips = [dict(verdict(p, k, "video"), acts=sorted(set(v))) for k, v in sorted(used["video"].items())]
    audio = audio_assets(p)
    maps = map_credits(p) if used["maps"] else []
    for n, why in sorted(used["unread"].items()):
        r.error(f"act {n}: its scene does not build ({why}), so what it shows cannot be checked")
    for a in images + clips + audio:
        if not a["usable"]:
            r.error(f"{a['media']} {a['id']} ({a['what'] or 'untitled'}) cannot be used: {a['basis']}")
        elif a.get("cleared"):
            r.note(f"{a['media']} {a['id']}: {a['basis']}")
    for m in maps:
        if not m["license"]:
            r.warn(f"map {m['id']}: map.json records no licence for its boundary data ({m['source'] or 'no source'}); "
                   "add \"license\" and \"credit\" to it")
    report = {"lang": p["code"], "built_by": BUILT_BY, "usable": r.ok,
              "note": "Licences are as each archive or person stated them; this records them and who cleared what, "
                      "it does not prove an asset is free to use.",
              "images": images, "footage": clips, "audio": audio, "maps": maps, "narration": narration_credit(p),
              "unread_acts": used["unread"]}
    if write:
        L.save(p["report"], report)
    r.note(f"{p['code']} rights: {len(images)} image(s), {len(clips)} clip(s), {len(audio)} sound(s), {len(maps)} map(s) used; "
           f"{len(r.errors)} not usable")
    return r, report


def blocked_by_act(report):
    """{act: [asset ids that are not usable]} for the act renders."""
    out = {}
    for a in report.get("images", []) + report.get("footage", []):
        if not a["usable"]:
            for n in a.get("acts", []):
                out.setdefault(n, []).append(a["id"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--project", required=True)
    a = ap.parse_args()
    r, _ = check(a.project)
    print(r.report(f"rights ({rp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
