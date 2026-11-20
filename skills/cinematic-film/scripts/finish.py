#!/usr/bin/env python3
"""Finishing an edition: its acts rendered at their approved timing (render), joined into one film
with the mix (join), captions burned in (captions). docpipe runs them as render@<lang>, join@<lang>
and captions@<lang>, after the look of that edition is approved.

  python3 finish.py render   --project P/editions/hi [--size 1920x1080] [--workers 0] [--force]
  python3 finish.py join     --project P/editions/hi [--force]      # out/film.<lang>.mp4
  python3 finish.py captions --project P/editions/hi [--force]      # out/film.<lang>.captions.mp4

render: every act of 06_film/acts.json (or the project's scene.py, a film of one act) through
render.py, the engine's memory-aware parallel renderer, into out/acts/act_NN.mp4. An act covers its
own part of the timeline (from its title card, or the film's start, to the next act) plus a quarter
second each side for the crossfade the join makes; each file carries the matching slice of the mix
so an act can be watched on its own. Every act is checked before it counts: it decodes, it is H.264
at the asked size, and it has the frames its time range needs. An act that fails is reported and
the rest go on, but the stage fails: nothing incomplete is ever marked done.

join: the acts, in order, into out/film.<lang>.mp4, with the edition's mix laid over the whole film
once (so the sound has no seam). Where two acts meet they crossfade over half a second, centred on
the act change (the title card's silence), so the film is exactly as long as the timeline; acts of
another size or frame rate are normalised to the first act's. A film of one act is copied, not
encoded again. Before it counts, the film must match the timeline (duration and frames), carry an
audio stream and be the asked size. An act rendered from older scenes or timing is not joined.

captions: the joined film with captions burned in, as a second file out/film.<lang>.captions.mp4
(the clean film stays, with its SRT and VTT, for platforms that show subtitles themselves). The
edition's captions.json chooses {"style": "clean" | "highlighter" | "paper" | "redbar",
"highlight": "auto" | "all" | "none", "enabled": true}; clean (sentence case over a soft dark
gradient, legible on any background) is the default. Hindi is shaped by HarfBuzz as everywhere.
Captions follow the edition's word timing; none is on screen in a title card's silence. The burned
film must have the joined film's frames, length, size and sound before it counts.

Time limits: render.py, the join's ffmpeg and burn_captions.py each run in their own process group
with a generous time limit (15 minutes plus a minute of work per second of film at 1080p, scaled by
pixels; the join a fifth of that), or CINEMATIC_RENDER_TIMEOUT seconds. A pass that runs past it is
taken as hung: the whole group (parallel workers and their encoders included) is stopped, its
partial file removed, nothing recorded, and the stage fails with a clear error. Interrupting
finish.py (Ctrl-C) stops the group as well, so no worker is left rendering.

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
import signal
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "finish.py"
HERE = pathlib.Path(__file__).resolve().parent
OVERLAP = 0.25          # each act is rendered this far past its edges, for the crossfade between acts
SIZE, CRF = "1920x1080", 18
TIMEOUT_ENV = "CINEMATIC_RENDER_TIMEOUT"
BASE_LIMIT, PER_FILM_SECOND = 900.0, 60.0      # seconds; at 1080p a worker renders about 3 frames a second


def time_limit(film_seconds, size, share=1.0):
    """How long a pass over film_seconds of film at size may run before it is taken as hung."""
    env = os.environ.get(TIMEOUT_ENV, "").strip()
    if env:
        try:
            if float(env) > 0:
                return float(env)
        except ValueError:
            pass
    w, h = map(int, str(size).lower().split("x"))
    return BASE_LIMIT + share * PER_FILM_SECOND * max(0.0, film_seconds) * max(1.0, w * h / (1920 * 1080))


def stop_group(proc):
    """Stop a process started by run_bounded and everything it started."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:                                                   # pragma: no cover - Windows
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    except (ProcessLookupError, PermissionError):
        pass


def run_bounded(cmd, limit, env=None):
    """subprocess.run(cmd, capture_output=True, text=True) in its own process group, stopped (with its
    children) after limit seconds or when this process is interrupted. Returns (result, timed_out)."""
    kw = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, **kw)
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        stop_group(proc)
        out, err = proc.communicate()
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err), True
    except BaseException:                                       # Ctrl-C and the like: leave nothing running
        stop_group(proc)
        proc.wait()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err), False


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
        limit = time_limit(b - a, size)
        res, hung = run_bounded(cmd, limit, env=env)
        if hung:
            tmp.unlink(missing_ok=True)
            r.error(f"act {n}: the render did not finish in {limit:.0f}s and was stopped; nothing was kept "
                    f"(set {TIMEOUT_ENV} to allow longer)"); continue
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



# ------------------------------------------------------------------------------------------- join

def join_key(p, recs, size):
    h = hashlib.sha256(json.dumps([size, OVERLAP, [r["sha256"] for r in recs]]).encode())
    h.update((sha_file(p["mix"]) if p["mix"].exists() else "no mix").encode())
    return h.hexdigest()[:20]


def join(proj, force=False, crf=CRF, log=print):
    """The acts, in order, crossfaded where they meet, with the edition's mix laid over the whole film."""
    p = fp(proj)
    r = L.Result()
    if not p["timing"].exists() or not p["state"].exists():
        r.error("the acts are not rendered yet (finish.py render)"); return r
    if not p["mix"].exists():
        r.error("no audio/mix.m4a: mix the soundtrack first (cuesheet.py mix)"); return r
    timing = L.load(p["timing"])
    total = float(timing["total_duration"])
    state = load_state(p)
    acts = acts_of(p, total)
    recs = []
    for n, scene, s, e, a, b in acts:
        rec = state["acts"].get(str(n))
        f = p["acts_dir"] / f"act_{n:02d}.mp4"
        if not rec or not f.exists():
            r.error(f"act {n} is not rendered (finish.py render)"); continue
        if rec.get("sha256") != sha_file(f):
            r.error(f"act {n}: {f.name} changed after it was rendered; render it again"); continue
        if rec.get("key") != act_key(p, scene, a, b, rec.get("size", state.get("size", SIZE)), crf):
            r.error(f"act {n} was rendered from older scenes, timing or assets; render it again"); continue
        recs.append(rec)
    if not r.ok:
        r.error("the film was not joined"); return r
    starts = [x["from"] for x in recs]
    if starts != sorted(starts) or [x["act"] for x in recs] != sorted(x["act"] for x in recs):
        r.error("the acts are not in timeline order (acts.json)"); return r
    infos = []
    for rec in recs:
        try:
            infos.append(probe(p["proj"] / rec["file"]))
        except ValueError as ex:
            r.error(f"act {rec['act']}: cannot be read: {ex}"); return r
    W, H, FPS = infos[0]["w"], infos[0]["h"], infos[0]["fps"]
    odd = [rec["act"] for rec, i in zip(recs, infos) if (i["w"], i["h"], round(i["fps"], 3)) != (W, H, round(FPS, 3))]
    if odd:
        r.warn(f"act(s) {', '.join(map(str, odd))} differ in size or frame rate from act {recs[0]['act']}: normalised to {W}x{H} at {FPS:g} fps")
    key = join_key(p, recs, f"{W}x{H}")
    old = state.get("join", {})
    f = p["film"]
    if f.exists():
        ours = old.get("sha256") == sha_file(f)
        if ours and old.get("key") == key:
            r.note(f"{p['code']} film is up to date ({old['duration']:.2f}s)"); return r
        if not ours:
            if not force:
                r.error(f"{f.relative_to(p['proj'])} was not joined by finish.py or was changed since; it is kept "
                        "(--force joins again, keeping a .bak)"); return r
            shutil.copyfile(f, f.with_name(f.name + ".bak"))
            r.note(f"your {f.name} kept as {f.name}.bak")
    tmp = f.with_name(f.stem + ".joining.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for rec in recs:
        cmd += ["-i", str(p["proj"] / rec["file"])]
    cmd += ["-i", str(p["mix"])]
    xfades = []
    if len(recs) == 1 and not odd:
        cmd += ["-map", "0:v", "-map", f"{len(recs)}:a", "-c:v", "copy"]          # one act: no re-encode
    else:
        D = 2 * OVERLAP
        g = [f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
             f"fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{i}]" for i in range(len(recs))]
        cur = "v0"
        for i in range(1, len(recs)):
            off = recs[i]["from"]                      # where the later act's render starts on the film's clock
            g.append(f"[{cur}][v{i}]xfade=transition=fade:duration={D:.3f}:offset={off:.3f}[x{i}]")
            xfades.append({"between": [recs[i - 1]["act"], recs[i]["act"]], "at": round(off, 3), "duration": D})
            cur = f"x{i}"
        cmd += ["-filter_complex", ";".join(g), "-map", f"[{cur}]", "-map", f"{len(recs)}:a",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    cmd += ["-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)]
    log(f"{p['code']} film: joining {len(recs)} act(s), {total:.2f}s")
    limit = time_limit(total, f"{W}x{H}", share=0.2)
    res, hung = run_bounded(cmd, limit)
    if hung:
        tmp.unlink(missing_ok=True)
        r.error(f"the join did not finish in {limit:.0f}s and was stopped; nothing was kept (set {TIMEOUT_ENV} to allow longer)")
        return r
    if res.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        r.error(f"the join failed: {res.stderr.strip()[-600:]}"); return r
    try:
        info = probe(tmp)
    except ValueError as ex:
        tmp.unlink(missing_ok=True)
        r.error(f"the joined film cannot be read: {ex}"); return r
    want = round(total * FPS)
    problems = []
    if abs(info["duration"] - total) > max(0.1, 2.0 / FPS):
        problems.append(f"{info['duration']:.2f}s long, the timeline is {total:.2f}s")
    if abs(info["frames"] - want) > 2:
        problems.append(f"{info['frames']} frames, {want} expected")
    if not info["audio"]:
        problems.append("no audio stream")
    if (info["w"], info["h"]) != (W, H):
        problems.append(f"{info['w']}x{info['h']}, not {W}x{H}")
    if problems:
        tmp.unlink(missing_ok=True)
        r.error(f"the joined film is wrong ({'; '.join(problems)}); nothing was kept"); return r
    tmp.replace(f)
    state["join"] = {"file": str(f.relative_to(p["proj"])), "order": [x["act"] for x in recs], "crossfades": xfades,
                     "duration": round(info["duration"], 3), "frames": info["frames"], "fps": FPS, "size": f"{W}x{H}",
                     "mix_sha256": sha_file(p["mix"]), "key": key, "sha256": sha_file(f)}
    L.save(p["state"], state)
    r.note(f"{f.relative_to(p['proj'])}: {len(recs)} act(s), {info['duration']:.2f}s, {info['frames']} frames at {W}x{H}"
           + (f", {len(xfades)} crossfade(s)" if xfades else ""))
    return r


def join_fingerprint(proj):
    p = fp(proj)
    st = load_state(p)
    h = hashlib.sha256(json.dumps(sorted((k, v.get("sha256")) for k, v in st.get("acts", {}).items())).encode())
    h.update((sha_file(p["mix"]) if p["mix"].exists() else "no mix").encode())
    h.update(f"{p['film'].exists() and p['film'].stat().st_size}".encode())
    return h.hexdigest()[:16]



# ---------------------------------------------------------------------------------------- captions

CAPTION_STYLES = ("clean", "highlighter", "paper", "redbar")
CAPTION_DEFAULT = {"enabled": True, "style": "clean", "highlight": "auto"}


def caption_config(p, r):
    """The edition's captions.json (optional): style, highlight, enabled."""
    f = p["proj"] / "captions.json"
    cfg = dict(CAPTION_DEFAULT, **(L.load(f, {}) if f.exists() else {}))
    if cfg["style"] not in CAPTION_STYLES:
        r.error(f"captions.json: style {cfg['style']!r} is not one of {', '.join(CAPTION_STYLES)}")
    if cfg["highlight"] not in ("auto", "all", "none"):
        r.error("captions.json: highlight is auto, all or none")
    return cfg


def caption_key(p, cfg):
    h = hashlib.sha256(json.dumps({k: cfg[k] for k in ("style", "highlight")}).encode())
    for f in (p["film"], p["timing"], p["proj"] / "fonts", HERE / "captions.py", HERE / "burn_captions.py",
              HERE / "wordtimes.py", HERE / "textshape.py", HERE / "engine.py"):
        f = pathlib.Path(f)
        h.update(f.name.encode())
        if f.is_file():
            h.update(sha_file(f).encode())
    return h.hexdigest()[:20]


def captions(proj, force=False, workers=0, log=print):
    """The joined film with captions burned in, as a second file (the clean film stays for platforms
    that show the SRT or VTT themselves)."""
    p = fp(proj)
    r = L.Result()
    cfg = caption_config(p, r)
    if not r.ok:
        return r
    state = load_state(p)
    if not cfg["enabled"]:
        r.note("captions.json: burned-in captions are off; the film is delivered with its SRT and VTT")
        state["captions"] = {"enabled": False}
        L.save(p["state"], state)
        return r
    j = state.get("join")
    if not j or not p["film"].exists() or j.get("sha256") != sha_file(p["film"]):
        r.error("no joined film (finish.py join), or it changed since it was joined"); return r
    key = caption_key(p, cfg)
    old = state.get("captions", {})
    f = p["captioned"]
    if f.exists():
        ours = old.get("sha256") == sha_file(f)
        if ours and old.get("key") == key:
            r.note(f"{p['code']} captioned film is up to date ({cfg['style']})"); return r
        if not ours:
            if not force:
                r.error(f"{f.relative_to(p['proj'])} was not made by finish.py or was changed since; it is kept "
                        "(--force burns the captions again, keeping a .bak)"); return r
            shutil.copyfile(f, f.with_name(f.name + ".bak"))
            r.note(f"your {f.name} kept as {f.name}.bak")
    tmp = f.with_name(f.stem + ".burning.mp4")
    rel = lambda x: os.path.relpath(x, p["proj"])          # noqa: E731 - burn_captions takes project-relative paths
    cmd = [sys.executable, str(HERE / "burn_captions.py"), "--project", str(p["proj"]), "--video", rel(p["film"]),
           "--audio", rel(p["film"]), "--style", cfg["style"], "--highlight", cfg["highlight"], "--out", rel(tmp)]
    if workers:
        cmd += ["--workers", str(workers)]
    log(f"{p['code']} captions: burning the {cfg['style']} style into the film")
    jf = probe(p["film"])
    limit = time_limit(jf["duration"], f"{jf['w']}x{jf['h']}")
    res, hung = run_bounded(cmd, limit)
    if hung:
        tmp.unlink(missing_ok=True)
        r.error(f"burning the captions did not finish in {limit:.0f}s and was stopped; nothing was kept "
                f"(set {TIMEOUT_ENV} to allow longer)"); return r
    if res.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        r.error(f"burning the captions failed: {(res.stderr or res.stdout).strip()[-600:]}"); return r
    try:
        info, film = probe(tmp), probe(p["film"])
    except ValueError as ex:
        tmp.unlink(missing_ok=True)
        r.error(f"the captioned film cannot be read: {ex}"); return r
    problems = []
    if abs(info["frames"] - film["frames"]) > 1:
        problems.append(f"{info['frames']} frames, the film has {film['frames']}")
    if abs(info["duration"] - film["duration"]) > 0.15:
        problems.append(f"{info['duration']:.2f}s, the film is {film['duration']:.2f}s")
    if not info["audio"]:
        problems.append("no audio stream")
    if (info["w"], info["h"]) != (film["w"], film["h"]):
        problems.append("another size than the film")
    if problems:
        tmp.unlink(missing_ok=True)
        r.error(f"the captioned film is wrong ({'; '.join(problems)}); nothing was kept"); return r
    tmp.replace(f)
    state["captions"] = {"enabled": True, "file": str(f.relative_to(p["proj"])), "style": cfg["style"], "highlight": cfg["highlight"],
                         "frames": info["frames"], "duration": round(info["duration"], 3), "key": key, "sha256": sha_file(f)}
    L.save(p["state"], state)
    r.note(f"{f.relative_to(p['proj'])}: {cfg['style']} captions, {info['duration']:.2f}s")
    return r


def captions_fingerprint(proj):
    p = fp(proj)
    r = L.Result()
    cfg = caption_config(p, r)
    h = hashlib.sha256(caption_key(p, cfg).encode() + json.dumps(cfg, sort_keys=True).encode())
    h.update(f"{p['captioned'].exists() and p['captioned'].stat().st_size}".encode())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rd = sub.add_parser("render"); rd.add_argument("--project", required=True); rd.add_argument("--size", default=SIZE)
    rd.add_argument("--workers", type=int, default=0); rd.add_argument("--force", action="store_true")
    jn = sub.add_parser("join"); jn.add_argument("--project", required=True); jn.add_argument("--force", action="store_true")
    cp_ = sub.add_parser("captions"); cp_.add_argument("--project", required=True); cp_.add_argument("--force", action="store_true")
    cp_.add_argument("--workers", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "render":
        r = render_acts(a.project, a.size, a.workers, a.force)
    elif a.cmd == "join":
        r = join(a.project, a.force)
    elif a.cmd == "captions":
        r = captions(a.project, a.force, a.workers)
    print(r.report(f"{a.cmd} ({fp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
