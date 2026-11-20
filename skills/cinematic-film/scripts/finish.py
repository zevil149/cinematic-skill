#!/usr/bin/env python3
"""Finishing an edition: its acts rendered at their approved timing (render), joined into one film
with the mix (join), captions burned in (captions). docpipe runs them as render@<lang>, join@<lang>
and captions@<lang>, after the look of that edition is approved.

  python3 finish.py render   --project P/editions/hi [--size 1920x1080] [--workers 0] [--force]

render: every act of 06_film/acts.json (or the project's scene.py, a film of one act) through
render.py, the engine's memory-aware parallel renderer, into out/acts/act_NN.mp4. An act covers its
own part of the timeline (from its title card, or the film's start, to the next act) plus a quarter
second each side for the crossfade the join makes; each file carries the matching slice of the mix
so an act can be watched on its own. Every act is checked before it counts: it decodes, it is H.264
at the asked size, and it has the frames its time range needs. An act that fails is reported and
the rest go on, but the stage fails: nothing incomplete is ever marked done.

Resume: an act is rendered again only when its scene, the engine, the timing, the prepared assets,
the size or its time range changed (out/finish.json). An act file that finish.py did not record,
or that changed since, is yours: never replaced without --force, which keeps it as .bak.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "finish.py"
HERE = pathlib.Path(__file__).resolve().parent
OVERLAP = 0.25          # each act is rendered this far past its edges, for the crossfade between acts
SIZE, CRF = "1920x1080", 18


def fp(proj):
    p = L.paths(proj)
    out = p["proj"] / "out"
    code = p["lang"] or "en"
    return {**p, "code": code, "out": out, "acts_dir": out / "acts", "state": out / "finish.json",
            "acts": p["film_dir"] / "acts.json", "mix": p["proj"] / "audio" / "mix.m4a",
            "film": out / f"film.{code}.mp4", "captioned": out / f"film.{code}.captions.mp4"}


def sha_file(f):
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path):
    """{w, h, fps, frames, duration, vcodec, audio} of a video, by ffprobe (counting frames)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip()[-300:] or "ffprobe could not read it")
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    if v is None:
        raise ValueError("no video stream")
    num, den = map(int, v["r_frame_rate"].split("/"))
    return {"w": int(v["width"]), "h": int(v["height"]), "fps": num / den, "frames": int(v.get("nb_read_frames") or 0),
            "duration": float(j.get("format", {}).get("duration") or 0), "vcodec": v.get("codec_name"),
            "audio": a.get("codec_name") if a else None}


def acts_of(p, total):
    """[(act, scene, start, end, render from, render to)] in order."""
    import effects
    acts = effects.act_list(p, total)
    out = []
    for i, (n, scene, s, e) in enumerate(acts):
        a = 0.0 if i == 0 else max(0.0, s - OVERLAP)
        b = total if i == len(acts) - 1 else min(total, e + OVERLAP)
        out.append((n, scene, s, e, round(a, 3), round(b, 3)))
    return out


def act_key(p, scene, a, b, size, crf):
    import prepare
    h = hashlib.sha256(json.dumps([a, b, size, crf]).encode())
    for f in (scene, p["timing"], p["acts"], p["proj"] / "scene.py", HERE / "scenekit.py", HERE / "engine.py", HERE / "render.py"):
        f = pathlib.Path(f)
        h.update(f.name.encode() + (f.read_bytes() if f.exists() else b"<missing>"))
    h.update(prepare.fingerprint(p["proj"]).encode())
    return h.hexdigest()[:20]


def load_state(p):
    return L.load(p["state"], {"lang": p["code"], "built_by": BUILT_BY, "acts": {}})




def render_acts(proj, size=SIZE, workers=0, force=False, crf=CRF, log=print):
    p = fp(proj)
    r = L.Result()
    if not p["timing"].exists():
        r.error("no audio/timing.json: build the narration first"); return r
    timing = L.load(p["timing"])
    if (p["lang"] and timing.get("lang") != p["lang"]) or (not p["lang"] and timing.get("lang") not in (None, "en")):
        r.error(f"audio/timing.json is the {timing.get('lang')} voice; this is the {p['code']} edition"); return r
    if not shutil.which("ffmpeg"):
        r.error("ffmpeg is not installed"); return r
    total = float(timing["total_duration"])
    acts = acts_of(p, total)
    if not acts:
        r.error("no scenes to render (scenegen, or a scene.py)"); return r
    state = load_state(p)
    p["acts_dir"].mkdir(parents=True, exist_ok=True)
    w, h = map(int, size.lower().split("x"))
    done = {}
    for n, scene, s, e, a, b in acts:
        f = p["acts_dir"] / f"act_{n:02d}.mp4"
        key = act_key(p, scene, a, b, size, crf)
        rec = state["acts"].get(str(n), {})
        if f.exists():
            ours = rec.get("sha256") == sha_file(f)
            if ours and rec.get("key") == key:
                done[n] = rec; r.note(f"act {n}: up to date ({rec['frames']} frames)"); continue
            if not ours:
                if not force:
                    r.error(f"act {n}: {f.relative_to(p['proj'])} was not rendered by finish.py or was changed since; "
                            "it is kept (--force renders it again, keeping a .bak)"); continue
                shutil.copyfile(f, f.with_name(f.name + ".bak"))
                r.note(f"act {n}: your {f.name} kept as {f.name}.bak")
        tmp = f.with_name(f.stem + ".rendering.mp4")
        cmd = [sys.executable, str(HERE / "render.py"), "--project", str(p["proj"]), "--t0", f"{a:.3f}", "--t1", f"{b:.3f}",
               "--size", size, "--crf", str(crf), "--out", str(tmp)] + (["--workers", str(workers)] if workers else [])
        if p["mix"].exists():
            cmd += ["--audio", str(p["mix"])]
        env = dict(os.environ, CINEMATIC_ACT=str(n))
        log(f"{p['code']} act {n}: rendering {a:.2f}-{b:.2f}s at {size}")
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            r.error(f"act {n}: the render failed: {(res.stderr or res.stdout).strip()[-600:]}"); continue
        try:
            info = probe(tmp)
        except ValueError as ex:
            tmp.unlink(missing_ok=True)
            r.error(f"act {n}: the rendered file cannot be read: {ex}"); continue
        want = round(b * info["fps"]) - round(a * info["fps"])
        problems = []
        if (info["w"], info["h"]) != (w, h):
            problems.append(f"{info['w']}x{info['h']}, not {size}")
        if info["vcodec"] != "h264":
            problems.append(f"codec {info['vcodec']}, not h264")
        if abs(info["frames"] - want) > 1:
            problems.append(f"{info['frames']} frames, {want} expected")
        if problems:
            tmp.unlink(missing_ok=True)
            r.error(f"act {n}: the render is incomplete or wrong ({'; '.join(problems)}); nothing was kept"); continue
        tmp.replace(f)
        rec = {"act": n, "file": str(f.relative_to(p["proj"])), "scene": str(pathlib.Path(scene).relative_to(p["proj"])),
               "t0": s, "t1": e, "from": a, "to": b, "frames": info["frames"], "fps": info["fps"], "size": size,
               "audio": bool(info["audio"]), "key": key, "sha256": sha_file(f)}
        state["acts"][str(n)] = rec
        done[n] = rec
        L.save(p["state"], state)
        r.note(f"act {n}: {info['frames']} frames, {info['frames'] / info['fps']:.2f}s at {size}")
    stale = [k for k in state["acts"] if int(k) not in [x[0] for x in acts]]
    for k in stale:
        state["acts"].pop(k)
    state.update(lang=p["code"], built_by=BUILT_BY, size=size, total=total, order=[x[0] for x in acts])
    L.save(p["state"], state)
    missing = [x[0] for x in acts if x[0] not in done]
    if missing:
        r.error(f"act(s) {', '.join(map(str, missing))} not rendered: the film is not complete")
    return r


def render_fingerprint(proj, size=SIZE, crf=CRF):
    p = fp(proj)
    if not p["timing"].exists():
        return "no-timing"
    total = float(L.load(p["timing"])["total_duration"])
    h = hashlib.sha256()
    for n, scene, s, e, a, b in acts_of(p, total):
        h.update(act_key(p, scene, a, b, size, crf).encode())
        f = p["acts_dir"] / f"act_{n:02d}.mp4"
        h.update(f"{f.exists() and f.stat().st_size}".encode())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rd = sub.add_parser("render"); rd.add_argument("--project", required=True); rd.add_argument("--size", default=SIZE)
    rd.add_argument("--workers", type=int, default=0); rd.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "render":
        r = render_acts(a.project, a.size, a.workers, a.force)
    print(r.report(f"{a.cmd} ({fp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
