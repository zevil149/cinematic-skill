#!/usr/bin/env python3
"""The production's audio library: music and sound effects you provide, with their rights.

  python3 audiolib.py add   --project P FILE --kind music --source own --by "Your Name" --title "Pulse"
  python3 audiolib.py add   --project P FILE --kind music --source licensed --license "Artlist licence" \
                            --license-ref "order 1234, standard licence" --title "..." --creator "..."
  python3 audiolib.py add   --project P FILE --kind sfx --source cc --license-url https://creativecommons.org/licenses/by/4.0/ \
                            --creator NAME --source-url PAGE --title "..."
  python3 audiolib.py add   --project P FILE --kind sfx --source freesound --freesound-id 12345 \
                            --license-url http://creativecommons.org/publicdomain/zero/1.0/ --creator NAME
  python3 audiolib.py verify --project P A004 [--online]       # Freesound: the licence the sound page states
  python3 audiolib.py clear  --project P A003 --by "Your Name" --note "licence checked: ..."
  python3 audiolib.py list   --project P
  python3 audiolib.py check  --project P

The library lives at the production root, shared by every edition: audio_library/library.json
and audio_library/files/ (a copy of each file you add; your original is never touched or moved).
Each edition says what to play, and when, in its own audio/cues.json (cuesheet.py).

Nothing is downloaded: you bring the files. Each asset records its source, licence, attribution
and clearance, and only usable assets are ever mixed:
  own        your own work (--by): usable
  synth      made here from code (the music bed in cuesheet.py): usable, nothing to license
  cc         a Creative Commons or public-domain file: CC0 and public domain usable; CC BY and BY-SA
             usable with the attribution recorded; NC, ND, unknown or unstated refused
  licensed   a track you hold a licence for (a library subscription, a purchase): pending until you
             clear it (clear --by --note), with the licence reference recorded
  freesound  a sound you downloaded from Freesound yourself: the licence must be verified against
             the sound's page (verify --online reads it from the Freesound API, metadata only, with
             FREESOUND_API_KEY) or cleared by you; Freesound's NC and Sampling+ licences are refused
Downloadable is not the same as usable: a refused or unclear licence stays out of every mix
unless you clear it yourself, with your name and a note (the override is recorded). A file that
changes after it was added is refused until it is added again.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
from archives import normalize_license  # noqa: E402

SOURCES = ("own", "licensed", "cc", "freesound")
KINDS = ("music", "sfx")
EXTS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".aif", ".aiff")
FREESOUND_API = "https://freesound.org/apiv2/sounds/{id}/?fields=id,name,username,license,url"


def lib_paths(proj):
    root = L.paths(proj)["root"]
    d = pathlib.Path(root) / "audio_library"
    return {"root": pathlib.Path(root), "dir": d, "json": d / "library.json", "files": d / "files"}


def load(proj):
    return L.load(lib_paths(proj)["json"], {"version": 1, "assets": []})


def save(proj, lib):
    L.save(lib_paths(proj)["json"], lib)


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def probe_duration(path):
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 3)
    except Exception:
        pass
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True)
        try:
            return round(float(r.stdout.strip()), 3)
        except ValueError:
            return None
    return None


def rights(source, license_text="", license_url="", license_ref="", by=""):
    """(licence record, policy, why) for a new asset. Policy: free | check | refuse."""
    if source == "own":
        if not by.strip():
            return None, "refuse", "your own work needs --by (who made it)"
        return {"code": "OWN", "label": f"Own work of {by.strip()}", "url": "", "raw": ""}, "free", ""
    if source == "licensed":
        lic = {"code": "LICENSED", "label": (license_text or "licensed").strip(), "url": license_url, "raw": license_text,
               "ref": license_ref.strip()}
        if not license_ref.strip():
            return None, "refuse", "a licensed track needs --license-ref (the order, licence or agreement it is used under)"
        return lic, "check", "a person must confirm the licence covers this film (clear --by --note)"
    lic = normalize_license(license_text, license_url)
    if source == "freesound" and re.search(r"sampling\+|sampling plus", f"{license_text} {license_url}".lower()):
        lic = {**lic, "code": "RESTRICTED", "label": "Sampling+", "policy": "refuse"}
    why = {"refuse": f"licence {lic['label']!r}: refused (non-commercial, no derivatives, unclear or not stated)",
           "check": f"licence {lic['label']!r}: a person must clear it", "free": ""}[lic["policy"]]
    return {k: lic[k] for k in ("code", "label", "url", "raw")}, lic["policy"], why


def attribution(a):
    lic = a["license"]
    if lic["code"] in ("OWN", "SYNTH"):
        return ""
    who = f" by {a['creator']}" if a.get("creator") else ""
    where = f", {a['source_url']}" if a.get("source_url") else ""
    via = " (Freesound)" if a["source"] == "freesound" else ""
    return f"\"{a.get('title') or a['id']}\"{who}{via}, {lic['label']}" + (f" ({lic['url']})" if lic.get("url") else "") + where


def needs_attribution(a):
    return a["license"]["code"] in ("CC-BY", "CC-BY-SA") or bool(a.get("attribution_required"))


def add(proj, file, kind, source, title="", creator="", source_url="", license_text="", license_url="",
        license_ref="", by="", freesound_id=None, note="", log=print):
    r = L.Result()
    src = pathlib.Path(file)
    if kind not in KINDS:
        r.error(f"--kind is music or sfx, not {kind!r}"); return r, None
    if source not in SOURCES:
        r.error(f"--source is one of {', '.join(SOURCES)}, not {source!r} (nothing is downloaded: bring the file)"); return r, None
    if not src.is_file():
        r.error(f"{src} is not a file"); return r, None
    if src.suffix.lower() not in EXTS:
        r.error(f"{src.name}: not an audio file this library takes ({', '.join(EXTS)})"); return r, None
    if source == "freesound" and not str(freesound_id or "").isdigit():
        r.error("a Freesound sound needs --freesound-id (the number in its page address)"); return r, None
    lic, policy, why = rights(source, license_text, license_url, license_ref, by)
    if lic is None:
        r.error(why); return r, None
    p = lib_paths(proj)
    lib = load(proj)
    digest = sha_file(src)
    for a in lib["assets"]:
        if a["sha256"] == digest:
            r.note(f"{src.name} is already in the library as {a['id']}"); return r, a
    aid = f"A{len(lib['assets']) + 1:03d}"
    p["files"].mkdir(parents=True, exist_ok=True)
    dst = p["files"] / f"{aid}{src.suffix.lower()}"
    shutil.copyfile(src, dst)                          # a copy: the original stays exactly where and as it was
    a = {"id": aid, "kind": kind, "source": source, "title": title or src.stem, "creator": creator,
         "source_url": source_url, "original": src.name, "file": str(dst.relative_to(p["dir"])), "sha256": digest,
         "duration": probe_duration(dst), "license": lic, "policy": policy,
         "clearance": {"status": "cleared" if policy == "free" and source != "freesound" else "refused" if policy == "refuse" else "pending",
                       "by": by.strip() if source == "own" else ("licence" if policy == "free" else ""), "at": now(), "note": note}}
    if source == "freesound":
        a["freesound"] = {"id": int(freesound_id), "verified": False}
        if policy == "free":
            why = "a Freesound licence is verified against the sound's page first (verify --online, or clear --by --note)"
    a["attribution"] = attribution(a)
    a["attribution_required"] = needs_attribution(a)
    lib["assets"].append(a)
    save(proj, lib)
    state = a["clearance"]["status"]
    log(f"{aid}: {kind} {a['title']!r} ({source}, {lic['label']}): {state}" + (f"; {why}" if why and state != "cleared" else ""))
    if state == "refused":
        r.warn(f"{aid} is in the library but refused: {why}. It is never mixed unless you clear it yourself")
    elif state == "pending":
        r.warn(f"{aid} is pending: {why}")
    return r, a


def usable(proj, a):
    """'' if the asset may be mixed, else why not. The file must be the one that was added."""
    if a.get("source") == "synth":
        return ""
    st = a.get("clearance", {}).get("status")
    if st != "cleared":
        return f"{a['id']} is {st or 'not cleared'} ({a['license']['label']}): clear it first (audiolib.py clear/verify)"
    f = lib_paths(proj)["dir"] / a["file"]
    if not f.exists():
        return f"{a['id']}: its file {a['file']} is missing from the library"
    if sha_file(f) != a["sha256"]:
        return f"{a['id']}: {a['file']} changed after it was added; add the file again"
    return ""


def get(proj, aid):
    return next((a for a in load(proj)["assets"] if a["id"] == aid), None)


def clear(proj, aid, by, note):
    """A person's decision that this asset may be used, recorded with their name and reason. Needed for
    licensed tracks, 'check' licences, unverified Freesound sounds, and (as a recorded override) a
    refused or unclear licence."""
    r = L.Result()
    if not by.strip() or not note.strip():
        r.error("clear needs --by (your name) and --note (why it may be used: the licence, the agreement)"); return r
    lib = load(proj)
    a = next((x for x in lib["assets"] if x["id"] == aid), None)
    if a is None:
        r.error(f"no asset {aid} in the library"); return r
    override = a["policy"] == "refuse"
    a["clearance"] = {"status": "cleared", "by": by.strip(), "at": now(), "note": note.strip(), "override": override}
    save(proj, lib)
    if override:
        r.warn(f"{aid} cleared by {by} against its licence ({a['license']['label']}): recorded as your override")
    r.note(f"{aid} cleared by {by}")
    return r


def verify(proj, aid, online=False, http=None):
    """A Freesound sound: compare the licence you recorded with the one its page states (API
    metadata only: the sound is never downloaded). Offline, says what would be checked."""
    import voices as V
    r = L.Result()
    lib = load(proj)
    a = next((x for x in lib["assets"] if x["id"] == aid), None)
    if a is None or a["source"] != "freesound":
        r.error(f"{aid} is not a Freesound sound in the library"); return r
    if not online:
        r.note(f"--online reads the licence of Freesound sound {a['freesound']['id']} (free, metadata only); nothing was sent")
        return r
    try:
        key = V.api_key("FREESOUND_API_KEY")
        j, _ = (http or V.Http()).request("GET", FREESOUND_API.format(id=a["freesound"]["id"]),
                                          {"Authorization": f"Token {key}", "Accept": "application/json"},
                                          None, secret=key, service="Freesound")
    except V.ProviderError as e:
        r.error(str(e)); return r
    stated = normalize_license("", j.get("license", ""))
    if re.search(r"sampling\+", str(j.get("license", "")).lower()):
        stated = {**stated, "code": "RESTRICTED", "label": "Sampling+", "policy": "refuse"}
    a["freesound"].update({"verified": True, "stated_license": j.get("license", ""), "page": j.get("url", ""),
                           "username": j.get("username", ""), "at": now()})
    if stated["code"] != a["license"]["code"]:
        a["clearance"] = {"status": "refused", "by": "freesound", "at": now(),
                          "note": f"recorded {a['license']['label']}, the page states {stated['label']}"}
        r.error(f"{aid}: you recorded {a['license']['label']}, Freesound states {stated['label']}: refused")
    elif stated["policy"] != "free":
        a["clearance"] = {"status": "refused", "by": "freesound", "at": now(), "note": f"licence {stated['label']}"}
        r.error(f"{aid}: Freesound states {stated['label']}, which is not usable here")
    else:
        if j.get("username") and not a.get("creator"):
            a["creator"] = j["username"]
        a["source_url"] = a.get("source_url") or j.get("url", "")
        a["clearance"] = {"status": "cleared", "by": "freesound licence", "at": now(), "note": f"page states {stated['label']}"}
        a["attribution"] = attribution(a)
        r.note(f"{aid}: Freesound states {stated['label']}; cleared")
    save(proj, lib)
    return r


def check(proj):
    r = L.Result()
    lib = load(proj)
    for a in lib["assets"]:
        why = usable(proj, a)
        if why and a["clearance"]["status"] == "cleared":
            r.error(why)                                    # cleared but its file is gone or changed
        elif why:
            r.note(why)
        if a.get("attribution_required") and not a.get("attribution"):
            r.error(f"{a['id']}: needs attribution and has none")
    r.note(f"{len(lib['assets'])} asset(s): " + ", ".join(f"{n} {s}" for s, n in sorted(
        {s: sum(1 for a in lib['assets'] if a['clearance']['status'] == s) for s in ('cleared', 'pending', 'refused')}.items()) if n))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("--project", required=True); a.add_argument("file")
    a.add_argument("--kind", required=True, choices=KINDS); a.add_argument("--source", required=True, choices=SOURCES)
    for f in ("title", "creator", "source-url", "license", "license-url", "license-ref", "by", "note"):
        a.add_argument("--" + f, default="")
    a.add_argument("--freesound-id", default=None)
    v = sub.add_parser("verify"); v.add_argument("--project", required=True); v.add_argument("id"); v.add_argument("--online", action="store_true")
    c = sub.add_parser("clear"); c.add_argument("--project", required=True); c.add_argument("id")
    c.add_argument("--by", required=True); c.add_argument("--note", required=True)
    for name in ("list", "check"):
        s = sub.add_parser(name); s.add_argument("--project", required=True)
    x = ap.parse_args()
    if x.cmd == "add":
        r, _ = add(x.project, x.file, x.kind, x.source, x.title, x.creator, x.source_url, x.license, x.license_url,
                   x.license_ref, x.by, x.freesound_id, x.note)
    elif x.cmd == "verify":
        r = verify(x.project, x.id, x.online)
    elif x.cmd == "clear":
        r = clear(x.project, x.id, x.by, x.note)
    elif x.cmd == "list":
        for a in load(x.project)["assets"]:
            print(f"{a['id']}  {a['kind']:<5} {a['clearance']['status']:<8} {a['license']['label']:<24} {a['title']}")
        return
    else:
        r = check(x.project)
    print(r.report("audio library"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
