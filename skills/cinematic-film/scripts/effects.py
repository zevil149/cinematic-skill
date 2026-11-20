#!/usr/bin/env python3
"""An edition's effects track: every sound cue of every act, synthesised into audio/sfx.wav for the
mix (cuesheet.py). docpipe runs it as effects@<lang>, after the narration and before the sound.

  python3 effects.py --project P/editions/hi [--force]

Where the cues come from (explicit, never guessed):
  the scenes   each act's scene.py: film.cue(...) calls and the cues items make themselves (a
               stamp, a print landing, a camera whip), as render.py --cues has always collected
               them. Each act gives only the cues inside its own part of the film, so acts that
               share a moment (a title card, a closing pull-back) never double a sound.
  the cue sheet "synth_cues" in audio/cues.json, placed on this edition's timing:
               {"kind": "boom", "at": {"line": 12, "word": "storm"}, "gain": 0.5, "dur": 1.2, "pan": 0.0}
               with the same anchors as music (t, film, line, word, section, shift).
  "effects": {"gain": 0.8} in audio/cues.json scales every cue; the mix sets the track's level
  (synth_sfx.gain_db) and ducks nothing under it, as before.

Every sound is synthesised by build_sfx.py from noise and partials: no samples, nothing to
download or license. Library sounds you cleared are placed by the cue sheet's "sfx" in the mix.

Writes audio/sfx.wav and audio/effects.json (every cue with its act, source, time and gain).
Resume: the same scenes, timing and cue sheet make nothing new. An sfx.wav this tool did not make
(build_sfx.py's, yours) or that changed since is never replaced without --force, which keeps it as
sfx.wav.bak. Without skia-python (the scenes cannot be built) or without scenes yet, the stage is
partial and the mix goes on without effects.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "effects.py"
HERE = pathlib.Path(__file__).resolve().parent


def ep(proj):
    p = L.paths(proj)
    a = p["proj"] / "audio"
    return {**p, "code": p["lang"] or "en", "sfx": a / "sfx.wav", "report": a / "effects.json", "cues": a / "cues.json",
            "acts": p["film_dir"] / "acts.json"}


def sha_file(f):
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def act_list(p, total):
    """[(act, scene file, start, end)]: each act's own part of the film, in order. A project without
    acts.json (a hand-made film) is one act: its scene.py, the whole film."""
    if not p["acts"].exists():
        sc = p["proj"] / "scene.py"
        return [(1, sc, 0.0, total)] if sc.exists() else []
    acts = sorted(L.load(p["acts"]).get("acts", []), key=lambda a: a["act"])
    out = []
    for i, a in enumerate(acts):
        start = 0.0 if i == 0 else float(a["t0"])
        end = float(acts[i + 1]["t0"]) if i + 1 < len(acts) else total
        out.append((a["act"], p["proj"] / a["scene"], start, end))
    return out


def fingerprint(proj):
    p = ep(proj)
    total = L.load(p["timing"], {}).get("total_duration", 0) if p["timing"].exists() else 0
    files = [p["timing"], p["acts"], HERE / "scenekit.py", HERE / "engine.py", HERE / "build_sfx.py"]
    files += [sc for _, sc, _, _ in act_list(p, total)]
    h = hashlib.sha256()
    sheet = L.load(p["cues"], {}) if p["cues"].exists() else {}         # only what effects reads from the cue sheet
    h.update(json.dumps({"lang": sheet.get("lang", p["code"]), "synth_cues": sheet.get("synth_cues") or [],
                         "effects": sheet.get("effects") or {}}, sort_keys=True, ensure_ascii=False).encode())
    for f in files:
        f = pathlib.Path(f)
        h.update(f.name.encode() + (f.read_bytes() if f.exists() else b"<missing>"))
    return h.hexdigest()[:20]


def scene_cues(p, total, r):
    """Every act's own cues, from its scene."""
    import review
    from engine import Doc
    cues, rooms = [], []
    for n, scene, start, end in act_list(p, total):
        try:
            film = review.load_act(scene).build_film(Doc(p["proj"]))
        except BaseException as e:                              # noqa: BLE001 - a scene that does not build
            r.error(f"act {n}: {scene.name} does not build: {type(e).__name__}: {str(e)[:300]}"); continue
        for c in film.all_cues():
            if start <= c["t"] < end or (c["t"] >= end and end >= total):
                cues.append({**c, "act": n, "source": "scene"})
        for a, b in film.room_tone or []:
            a, b = max(a, start), min(b, end)
            if b > a:
                rooms.append([round(a, 3), round(b, 3)])
    return cues, rooms


def sheet_cues(p, timing, r, kinds):
    """The cue sheet's "synth_cues", placed on this edition's timing."""
    import cuesheet
    if not p["cues"].exists():
        return [], 1.0
    sheet = L.load(p["cues"])
    if sheet.get("lang", p["code"]) != p["code"]:
        r.error(f"audio/cues.json is the {sheet.get('lang')} edition's; this is {p['code']}"); return [], 1.0
    sections = cuesheet.sections_of(p, timing)
    out = []
    for i, c in enumerate(sheet.get("synth_cues") or []):
        kind = c.get("kind")
        if kind not in kinds:
            r.error(f"synth_cues[{i}]: kind {kind!r} is not one of {', '.join(sorted(kinds))}"); continue
        try:
            t = cuesheet.resolve(c.get("at", {}), timing, sections, f"synth_cues[{i}] at")
        except ValueError as e:
            r.error(str(e)); continue
        cue = {"type": kind, "t": round(t, 3), "gain": float(c.get("gain", 0.5)), "source": "cue sheet"}
        for k in ("dur", "pan"):
            if k in c:
                cue[k] = float(c[k])
        out.append(cue)
    return out, float((sheet.get("effects") or {}).get("gain", 1.0))


def owned(p):
    if not p["sfx"].exists():
        return None
    rep = L.load(p["report"], {}) if p["report"].exists() else {}
    return rep.get("built_by") == BUILT_BY and rep.get("sfx_sha256") == sha_file(p["sfx"])


def build(proj, force=False, log=print):
    p = ep(proj)
    r = L.Result()
    r.partial = False
    if not p["timing"].exists():
        r.error("no audio/timing.json: build the narration first (narrate.py)"); return r
    timing = L.load(p["timing"])
    if (p["lang"] and timing.get("lang") != p["lang"]) or (not p["lang"] and timing.get("lang") not in (None, "en")):
        r.error(f"audio/timing.json is the {timing.get('lang')} voice; this is the {p['code']} edition"); return r
    total = float(timing["total_duration"])
    if not act_list(p, total):
        r.warn("no scenes yet (scenegen, or a scene.py): no effects; the mix goes on without them")
        r.partial = True
        return r
    try:
        import numpy  # noqa: F401
        import skia  # noqa: F401
        import build_sfx as B
    except ImportError as e:
        r.warn(f"effects: {e.name} is not installed, so the scenes' cues cannot be collected; the mix goes on without effects")
        r.partial = True
        return r
    key = fingerprint(proj)
    mine = owned(p)
    old = L.load(p["report"], {}) if p["report"].exists() else {}
    if mine and old.get("input_hash") == key:
        r.note(f"{p['code']} effects are up to date ({len(old.get('cues', []))} cues); nothing synthesised")
        return r
    if mine is False and not force:
        r.error("audio/sfx.wav was not made by effects.py (build_sfx.py's, or yours) or was changed since: it is kept "
                "(--force replaces it, keeping it as sfx.wav.bak)"); return r
    cues, rooms = scene_cues(p, total, r)
    extra, scale = sheet_cues(p, timing, r, set(B.SOUNDS))
    if not r.ok:
        r.error("no effects track was written"); return r
    cues = sorted(cues + extra, key=lambda c: c["t"])
    unknown = sorted({c["type"] for c in cues} - set(B.SOUNDS))
    if unknown:
        r.error(f"scene cues of unknown kinds: {', '.join(unknown)}"); return r
    if mine is False:
        shutil.copyfile(p["sfx"], p["sfx"].with_name("sfx.wav.bak"))
        r.note("your sfx.wav kept as sfx.wav.bak")
    import inspect
    bed = B.Bed(total)
    for i, c in enumerate(cues):
        fn = B.SOUNDS[c["type"]]
        kw = {"dur": c["dur"]} if "dur" in c and "dur" in inspect.signature(fn).parameters else {}
        pan = c.get("pan", ((i * 37) % 11 - 5) / 20)
        bed.add(fn(seed=100 + i, **kw), max(c["t"], 0), gain=c.get("gain", 1.0) * scale, pan=pan)
    if rooms:
        bed.add(B.room_tone(total, rooms), 0, gain=.22 * scale)
    tmp = p["sfx"].with_name("sfx.tmp.wav")
    bed.render(tmp)
    tmp.replace(p["sfx"])
    kinds = {}
    for c in cues:
        kinds[c["type"]] = kinds.get(c["type"], 0) + 1
    by_act = {}
    for c in cues:
        if "act" in c:
            by_act[str(c["act"])] = by_act.get(str(c["act"]), 0) + 1
    L.save(p["report"], {"lang": p["code"], "built_by": BUILT_BY, "input_hash": key, "sfx_sha256": sha_file(p["sfx"]),
                         "duration": total, "scale": scale, "kinds": kinds, "per_act": by_act, "room_tone": rooms,
                         "from_cue_sheet": len(extra), "cues": cues})
    log(f"{p['code']} effects: {len(cues)} cues ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) or 'none'}), {total:.1f}s")
    r.note(f"audio/sfx.wav for {p['code']}: {len(cues)} cues from {len(by_act)} act(s)" +
           (f" and {len(extra)} from the cue sheet" if extra else ""))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    r = build(a.project, a.force)
    print(r.report(f"effects ({ep(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
