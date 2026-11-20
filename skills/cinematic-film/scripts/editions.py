#!/usr/bin/env python3
"""Language editions of one documentary: the same production (topic, research, outline, beats,
visuals) told in several languages, each edition with its own script, voice, timing, subtitles,
film and outputs. English is the default edition.

  python3 editions.py add   --project P hi [--own-beats]   # editions/hi/, a complete film project
  python3 editions.py list  --project P
  python3 editions.py check --project P [hi]                # language isolation and tags
  python3 editions.py lexicon --project P hi [--add "Kitty Hawk" "किटी हॉक"] [--allow NASA]

An edition folder is a normal film project: render.py, make_beats.py, burn_captions.py and the
rest run on --project P/editions/hi unchanged. It links (or, where links are not possible,
copies) the production's assets/, photos.json, footage.json and map.json, and never edits them.

Each edition keeps:
  edition.json     {"lang": "hi", "production": "../..", "beats": "shared" | "own"}
  lexicon.json     pronunciations and the words that may stay in another script ("allow")
  voice.json       the voice for this language only (voice.py); a scratch espeak voice to start
  03_script/       narration.json (lines point to beats), script.md
  04_scenes/       storyboard timed by this edition's voice
  06_film/         scene.py starters with this edition's text
  audio/, out/     voice, timing, mix, subtitles and films, every file tagged with the language

A project without editions is a single English edition at its root, exactly as before.
"""
import argparse
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import lang  # noqa: E402

SHARED_LINKS = ("assets", "photos.json", "footage.json", "map.json")


def editions_of(root):
    t = L.load(L.paths(root)["topic"], {})
    return list(t.get("editions") or [])


def default_edition(root):
    t = L.load(L.paths(root)["topic"], {})
    eds = t.get("editions") or []
    return t.get("default_edition") or (eds[0] if eds else "en")


def edition_dir(root, code):
    return pathlib.Path(root) / "editions" / code


def link_shared(root, ed):
    """Link the production's shared assets into an edition, so the film tools find them there.
    A link that already exists is kept; a real file or folder in its place (yours) is never replaced."""
    made = []
    for name in SHARED_LINKS:
        src = pathlib.Path(root) / name
        dst = ed / name
        if dst.is_symlink() or dst.exists():
            continue
        if name == "assets":
            src.mkdir(parents=True, exist_ok=True)
        elif not src.exists():
            continue                         # linked once the production has it (visuals, make_map)
        rel = os.path.relpath(src, ed)
        try:
            dst.symlink_to(rel, target_is_directory=src.is_dir())
            made.append(f"{name} -> {rel}")
        except OSError:                      # no links (some Windows setups): copy, and say so
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
            made.append(f"{name} (copied: links are not available here)")
    return made


def add(root, code, own_beats=False, log=print):
    root = pathlib.Path(root)
    lg = lang.get(code)
    p = L.paths(root)
    t = L.load(p["topic"], {})
    if not t:
        raise SystemExit(f"{root} has no 00_topic/topic.json: start it with docpipe.py new")
    eds = list(t.get("editions") or [])
    ed = edition_dir(root, code)
    if code not in eds:
        eds.append(code)
        t["editions"] = eds
        t.setdefault("default_edition", eds[0])
        L.save(p["topic"], t)
    ed.mkdir(parents=True, exist_ok=True)
    if not (ed / "edition.json").exists():
        L.save(ed / "edition.json", {"lang": code, "production": "../..", "beats": "own" if own_beats else "shared",
                                     "locale": lg.locale, "wpm": lg.wpm})
    if not (ed / "lexicon.json").exists():
        L.save(ed / "lexicon.json", {"lang": code, "terms": {}, "allow": []})
    if not (ed / "voice.json").exists():
        import voice
        L.save(ed / "voice.json", voice.default_config(code))
    for sub in ("03_script", "04_scenes", "06_film", "audio/takes", "out", "fonts"):
        (ed / sub).mkdir(parents=True, exist_ok=True)
    made = link_shared(root, ed)
    log(f"edition {code} ({lg.name}) at {ed}" + (f"; linked {', '.join(made)}" if made else ""))
    return ed


def lexicon(ed):
    return L.load(pathlib.Path(ed) / "lexicon.json", {"terms": {}, "allow": []})


def allowed_words(ed):
    lx = lexicon(ed)
    return set(lx.get("allow", [])) | {k for k, v in lx.get("terms", {}).items() if v.get("keep")}


def check(root, code, r=None):
    """Isolation and tag checks for one edition. Errors mean languages would be mixed."""
    r = r or L.Result()
    ed = edition_dir(root, code)
    if not (ed / "edition.json").exists():
        r.error(f"edition {code}: {ed}/edition.json is missing (editions.py add)"); return r
    info = L.edition_info(ed)
    try:
        lg = lang.get(info["lang"])
    except KeyError as e:
        r.error(str(e)); return r
    if info["lang"] != code:
        r.error(f"edition folder {code} says it is {info['lang']!r} in edition.json")
    lx = lexicon(ed)
    if lx.get("lang", code) != code:
        r.error(f"edition {code}: lexicon.json is for {lx.get('lang')!r}")
    for name, path in (("narration.json", ed / "03_script" / "narration.json"), ("script.json", ed / "script.json"),
                       ("timing.json", ed / "audio" / "timing.json"), ("voice.json", ed / "voice.json"),
                       ("audio/voice/manifest.json", ed / "audio" / "voice" / "manifest.json")):
        if path.exists():
            tag = L.load(path).get("lang")
            if tag and tag != code:
                r.error(f"edition {code}: {name} is tagged {tag!r}; it belongs to another edition")
    for name in SHARED_LINKS:
        f = ed / name
        if f.exists() and not f.is_symlink() and (pathlib.Path(root) / name).exists() and name != "assets":
            r.note(f"edition {code}: {name} is a copy, not a link; it will not follow changes to the production")
    for term, entry in (lx.get("terms") or {}).items():
        spoken = entry.get("spoken", "") if isinstance(entry, dict) else str(entry)
        if not spoken:
            r.error(f"edition {code} lexicon: {term!r} has no spoken form")
        for prob in lg.check_script(spoken):
            r.error(f"edition {code} lexicon: {term!r} is spoken as {spoken!r}, which {prob.split(' ', 1)[1]}")
    allow = allowed_words(ed)
    n = L.load(ed / "03_script" / "narration.json", {})
    for s in n.get("sections", []):
        for line in s.get("lines", []):
            for field in ("text", "spoken", "typed"):
                for prob in lg.check_script(line.get(field, ""), allow):
                    r.error(f"edition {code} line {line.get('id')} {field}: {prob}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("--project", required=True); a.add_argument("lang")
    a.add_argument("--own-beats", action="store_true", help="this edition keeps its own beats (its own cut)")
    li = sub.add_parser("list"); li.add_argument("--project", required=True)
    c = sub.add_parser("check"); c.add_argument("--project", required=True); c.add_argument("lang", nargs="?")
    x = sub.add_parser("lexicon", help="list the lexicon, or add a pronunciation or an allowed word")
    x.add_argument("--project", required=True); x.add_argument("lang")
    x.add_argument("--add", nargs=2, metavar=("TERM", "SPOKEN")); x.add_argument("--allow", action="append", default=[])
    args = ap.parse_args()
    if args.cmd == "lexicon":
        path = edition_dir(args.project, args.lang) / "lexicon.json"
        lx = L.load(path, {"lang": args.lang, "terms": {}, "allow": []})
        if args.add:
            lx.setdefault("terms", {})[args.add[0]] = {**lx.get("terms", {}).get(args.add[0], {}), "spoken": args.add[1]}
        for w in args.allow:
            if w not in lx.setdefault("allow", []):
                lx["allow"].append(w)
        if args.add or args.allow:
            L.save(path, lx)
        for term, entry in lx.get("terms", {}).items():
            print(f"{term} -> {entry.get('spoken') if isinstance(entry, dict) else entry}")
        print("allowed in the text: " + (", ".join(lx.get("allow", [])) or "none"))
        r = check(args.project, args.lang)
        print(r.report("lexicon"))
        sys.exit(0 if r.ok else 1)
    if args.cmd == "add":
        add(args.project, args.lang, args.own_beats)
    elif args.cmd == "list":
        d = default_edition(args.project)
        for code in editions_of(args.project) or ["en (single-language project)"]:
            print(f"{code}{'  (default)' if code == d else ''}")
    else:
        codes = [args.lang] if args.lang else editions_of(args.project)
        r = L.Result()
        for code in codes:
            check(args.project, code, r)
        print(r.report("editions"))
        sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
