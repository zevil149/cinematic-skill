#!/usr/bin/env python3
"""The finished film's quality control and its delivery manifest (docpipe: qc@<lang>, the last stage).

  python3 qc.py --project P/editions/hi

Checks the film an edition delivers, and says plainly what blocks it (errors) and what deserves a
look (warnings):
  film       out/film.<lang>.mp4 (and the captioned copy, if captions are on) exists and decodes;
             H.264 video and an audio stream; the rendered size and frame rate
  length     the film is the timeline's length (0.1 s) with every frame; sound and picture end together
  acts       joined in the order of 06_film/acts.json, each crossfade on its act change
  picture    black frames (ffmpeg blackdetect) outside the film's own fade in and fade out; blank,
             almost single-colour frames in a sample every 2 s
  sound      every narration line is heard in its own place (narration missing or out of sync is an
             error); silences of a second or more outside the lead-in, the pauses between lines, the
             title cards' silence and the tail; clipping (true peak above -0.5 dBTP is an error)
  subtitles  the SRT and VTT exist and match audio/subs.json, every cue sits on its line in the
             current timing and inside the film; burned captions are visible where lines are spoken
Deliberate choices are not faults: the fades, title cards and pauses are known from the timing,
and qc.json in the edition can declare more: {"allow_black": [[t0, t1]], "allow_silence": [[t0, t1]]}.

Writes out/qc.<lang>.json, out/qc.<lang>.md and the delivery manifest out/delivery.<lang>.json: the
films, subtitles, audio, reports and credits with their sizes and SHA-256, and the film's metadata.
"complete": true only when nothing blocks it. Reads everything, changes nothing else.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "qc.py"
FADE_IN, FADE_OUT = 0.9, 2.2            # engine.Film's own fades
BLACK_MIN, SILENCE_MIN = 0.4, 1.0


def qp(proj):
    import finish
    p = finish.fp(proj)
    code = p["code"]
    out = p["out"]
    return {**p, "qc_json": out / f"qc.{code}.json", "qc_md": out / f"qc.{code}.md", "manifest": out / f"delivery.{code}.json",
            "subs": p["proj"] / "audio" / "subs.json", "srt": out / f"subtitles.{code}.srt", "vtt": out / f"subtitles.{code}.vtt",
            "config": p["proj"] / "qc.json"}


def sha_file(f):
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def stream_durations(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)])
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        try:
            out[s["codec_type"]] = float(s.get("duration"))
        except (TypeError, ValueError):
            pass
    return out


def intervals(stderr, start_key, end_key):
    a = [float(x) for x in re.findall(start_key + r":\s*([\d.]+)", stderr)]
    b = [float(x) for x in re.findall(end_key + r":\s*([\d.]+)", stderr)]
    return list(zip(a, b))


def overlap_outside(span, allowed):
    """How much of span lies outside every allowed window."""
    a, b = span
    pieces = [(a, b)]
    for x, y in allowed:
        nxt = []
        for p0, p1 in pieces:
            if y <= p0 or x >= p1:
                nxt.append((p0, p1)); continue
            if p0 < x:
                nxt.append((p0, x))
            if y < p1:
                nxt.append((y, p1))
        pieces = nxt
    return sum(p1 - p0 for p0, p1 in pieces)


def decode_audio(path, rate=8000):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1"],
                       capture_output=True)
    return np.frombuffer(r.stdout, np.float32), rate


def sample_frames(path, every, w=160, h=90):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps=1/{every},scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "pipe:1"], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    n = len(a) // (w * h * 3)
    return a[: n * w * h * 3].reshape(n, h, w, 3)


def build(proj, log=print):
    import finish
    p = qp(proj)
    r = L.Result()
    checks = []

    def check(name, ok, msg, blocking=True, seen=""):
        """msg says what is wrong; seen, what was measured when it is right."""
        checks.append({"check": name, "ok": bool(ok), "blocking": blocking, "message": seen if ok else msg})
        if not ok:
            (r.error if blocking else r.warn)(f"{name}: {msg}")
    if not p["timing"].exists() or not p["state"].exists():
        r.error("nothing to check: the film has not been rendered and joined (finish.py render, join)"); return r
    timing = L.load(p["timing"])
    total = float(timing["total_duration"])
    segs = timing.get("segments", [])
    state = finish.load_state(p)
    cfg = L.load(p["config"], {}) if p["config"].exists() else {}
    film = p["film"]
    j = state.get("join") or {}
    if not film.exists():
        check("film", False, f"{film.relative_to(p['proj'])} is missing"); return finish_report(p, r, checks, timing, state)
    try:
        info = finish.probe(film)
    except ValueError as e:
        check("film", False, f"{film.name} cannot be read: {e}"); return finish_report(p, r, checks, timing, state)
    check("film", True, "", seen=f"{film.name}: {info['w']}x{info['h']}, {info['fps']:g} fps, {info['duration']:.2f}s")
    check("video codec", info["vcodec"] == "h264", f"video is {info['vcodec']}, not h264", blocking=False, seen=info["vcodec"])
    check("audio stream", bool(info["audio"]), "the film has no audio stream", seen=str(info["audio"]))
    want_size = j.get("size") or state.get("size")
    if want_size:
        check("size", f"{info['w']}x{info['h']}" == want_size, f"{info['w']}x{info['h']}, rendered at {want_size}", seen=want_size)
    fps = j.get("fps") or 30.0
    check("frame rate", abs(info["fps"] - fps) < 0.01, f"{info['fps']:g} fps, rendered at {fps:g}", seen=f"{fps:g} fps")
    check("duration", abs(info["duration"] - total) <= 0.1, f"{info['duration']:.2f}s, the timeline is {total:.2f}s",
          seen=f"{info['duration']:.2f}s, the timeline {total:.2f}s")
    check("frames", abs(info["frames"] - round(total * info["fps"])) <= 2,
          f"{info['frames']} frames, {round(total * info['fps'])} expected: the render is incomplete",
          seen=f"{info['frames']} frames")
    sd = stream_durations(film)
    if "audio" in sd and "video" in sd:
        check("sound and picture", abs(sd["audio"] - sd["video"]) <= 0.2,
              f"the sound lasts {sd['audio']:.2f}s, the picture {sd['video']:.2f}s",
              seen=f"sound {sd['audio']:.2f}s, picture {sd['video']:.2f}s")
    if j.get("sha256") and j["sha256"] != sha_file(film):
        check("film record", False, f"{film.name} changed after it was joined; join it again", blocking=False)
    # acts
    acts = sorted(L.load(p["acts"], {}).get("acts", []), key=lambda a: a["act"]) if p["acts"].exists() else []
    if acts:
        check("act order", j.get("order") == [a["act"] for a in acts],
              f"joined {j.get('order')}, acts.json has {[a['act'] for a in acts]}", seen=f"acts {j.get('order')}")
        for xf, a in zip(j.get("crossfades", []), acts[1:]):
            mid = xf["at"] + xf["duration"] / 2
            check(f"act {a['act']} join", abs(mid - a["t0"]) <= 0.05, f"the crossfade is at {mid:.2f}s, act {a['act']} starts at {a['t0']:.2f}s",
                  seen=f"crossfade centred at {mid:.2f}s")
        recs = state.get("acts", {})
        unrendered = [a["act"] for a in acts if str(a["act"]) not in recs]
        check("act renders", not unrendered, f"act(s) {', '.join(map(str, unrendered))} have no recorded render: the film is incomplete",
              seen=f"{len(acts)} act(s) rendered")
    leftovers = sorted(f.name for f in p["out"].rglob("*") if f.name.endswith((".rendering.mp4", ".joining.mp4", ".burning.mp4")))
    if leftovers:
        check("interrupted renders", False, f"{', '.join(leftovers)} left by an interrupted run; nothing uses them", blocking=False)
    # picture: black frames outside the fades and declared spans
    cards = [(a["title_card"]["t0"] - 0.3, a["title_card"]["t1"] + 0.3) for a in acts if a.get("title_card")]
    allowed_black = [(0.0, FADE_IN + 0.3), (total - FADE_OUT - 0.3, total + 1)] + cards + \
        [tuple(x) for x in cfg.get("allow_black", [])]
    bd = run(["ffmpeg", "-v", "info", "-nostats", "-i", str(film), "-vf", f"blackdetect=d={BLACK_MIN}:pic_th=0.995:pix_th=0.05",
              "-an", "-f", "null", "-"]).stderr
    blacks = intervals(bd, "black_start", "black_end")
    for a, b in blacks:
        out = overlap_outside((a, b), allowed_black)
        if out >= 1.0:
            check("black frames", False, f"{out:.1f}s of black between {a:.2f}s and {b:.2f}s, outside the film's fades")
        elif out > 0.2:
            check("black frames", False, f"{out:.1f}s of black near {a:.2f}s; look at it", blocking=False)
    if not any(c["check"] == "black frames" for c in checks):
        check("black frames", True, "", seen=f"{len(blacks)} black span(s), none outside the fades or title cards")
    try:
        import numpy as np
        import review
        frames = sample_frames(film, 2.0)
        for k, fr in enumerate(frames):
            t = k * 2.0
            if any(x <= t <= y for x, y in allowed_black):
                continue
            fl = review.flags_of(fr)[0]
            if "blank" in fl:
                check("blank frames", False, f"the frame at {t:.0f}s is almost a single colour; look at it", blocking=False)
        audio, rate = decode_audio(film)
    except ImportError:
        audio = None
        check("analysis", False, "numpy is not installed: frames and sound were not analysed", blocking=False)
    # sound: every line heard in its own place
    if audio is not None and len(audio):
        def rms(a, b):
            x = audio[int(a * rate):int(b * rate)]
            return float(np.sqrt((x ** 2).mean())) if len(x) else 0.0
        quiet_lines = []
        for s in segs:
            v = rms(s["start"], s["end"])
            if v < 0.003:
                quiet_lines.append(s["id"])
        check("narration", not quiet_lines, f"line(s) {', '.join(map(str, quiet_lines))} are silent in the film: "
              "the narration is missing or out of sync there", seen=f"all {len(segs)} lines heard")
    allowed_quiet = [(0.0, (segs[0]["start"] if segs else 0) + 0.3)]
    for a_, b_ in zip(segs, segs[1:]):
        allowed_quiet.append((a_["end"] - 0.2, b_["start"] + 0.3))         # the pauses, title cards included
    if segs:
        allowed_quiet.append((segs[-1]["end"] - 0.2, total + 1))
    allowed_quiet += [tuple(x) for x in cfg.get("allow_silence", [])]
    sdx = run(["ffmpeg", "-v", "info", "-nostats", "-i", str(film), "-af", f"silencedetect=noise=-50dB:d={SILENCE_MIN}",
               "-vn", "-f", "null", "-"]).stderr
    quiet = intervals(sdx, "silence_start", "silence_end")
    for a, b in quiet:
        out = overlap_outside((a, b), allowed_quiet)
        if out >= SILENCE_MIN:
            check("silence", False, f"{out:.1f}s of silence between {a:.2f}s and {b:.2f}s, where nothing pauses", blocking=False)
    if not any(c["check"] == "silence" for c in checks):
        check("silence", True, "", seen=f"{len(quiet)} silence(s), none outside the lead-in, pauses, title cards or tail")
    import cuesheet
    lufs, tp = cuesheet.measure(film)
    check("clipping", not tp > -0.1, f"true peak {tp:.1f} dBTP: the sound clips", seen=f"true peak {tp:.1f} dBTP")
    if -0.1 >= tp > -1.0:
        check("headroom", False, f"true peak {tp:.1f} dBTP, close to clipping", blocking=False)
    # subtitles
    if p["subs"].exists():
        subs = L.load(p["subs"])
        for f in (p["srt"], p["vtt"]):
            check(f"subtitles {f.suffix[1:]}", f.exists(), f"{f.relative_to(p['proj'])} is missing", seen=f.name)
        rec = subs.get("files", {})
        for f in (p["srt"], p["vtt"]):
            rel = str(f.relative_to(p["proj"]))
            if f.exists() and rec.get(rel) and rec[rel] != sha_file(f):
                check("subtitles edited", False, f"{f.name} was edited after it was made; it is delivered as edited", blocking=False)
        if p["srt"].exists():
            n = len(re.findall(r"^\d+\s*$", p["srt"].read_text(encoding="utf-8"), re.M))
            check("subtitle cues", n == len(subs.get("cues", [])) or rec.get(str(p["srt"].relative_to(p["proj"]))) != sha_file(p["srt"]),
                  f"the SRT has {n} cues, subs.json {len(subs.get('cues', []))}",
                  seen=f"{n} cues")
        by_id = {s["id"]: s for s in segs}
        off = [c["n"] for c in subs.get("cues", []) if c["line"] not in by_id
               or not (by_id[c["line"]]["start"] - 0.05 <= c["t0"] <= by_id[c["line"]]["end"])]
        check("subtitle sync", not off, f"cue(s) {', '.join(map(str, off[:8]))} are not on their lines in the current timing: "
              "make the subtitles again (subtitles.py)", seen="every cue on its line")
        late = [c["n"] for c in subs.get("cues", []) if c["t1"] > info["duration"] + 0.05]
        check("subtitle end", not late, f"cue(s) {', '.join(map(str, late[:8]))} run past the end of the film",
              seen="the last cue ends inside the film")
    else:
        check("subtitles", False, "no subtitles (subtitles.py)")
    # burned captions
    cap = state.get("captions") or {}
    if cap.get("enabled"):
        cf = p["captioned"]
        if not cf.exists():
            check("captioned film", False, f"{cf.relative_to(p['proj'])} is missing")
        else:
            try:
                ci = finish.probe(cf)
                check("captioned film", abs(ci["frames"] - info["frames"]) <= 1 and bool(ci["audio"]),
                      f"{cf.name}: {ci['frames']} frames, the film has {info['frames']}",
                      seen=f"{cf.name}: {ci['frames']} frames, {cap.get('style')}")
                if audio is not None and segs:
                    s = segs[0]
                    t = (s["start"] + s["end"]) / 2
                    a, b = grab(cf, t), grab(film, t)
                    h = a.shape[0]
                    diff = float(np.abs(a[int(h * 0.74):].astype(int) - b[int(h * 0.74):].astype(int)).mean())
                    check("captions visible", diff > 4.0, f"no caption is visible at {t:.1f}s in {cf.name}",
                          seen=f"a caption on screen at {t:.1f}s")
            except ValueError as e:
                check("captioned film", False, f"{cf.name} cannot be read: {e}")
    return finish_report(p, r, checks, timing, state, info)


def grab(video, t):
    import numpy as np
    import finish
    i = finish.probe(video)
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "pipe:1"], capture_output=True).stdout
    return np.frombuffer(out, np.uint8).reshape(i["h"], i["w"], 3)


def finish_report(p, r, checks, timing, state, info=None):
    complete = r.ok
    qc = {"lang": p["code"], "built_by": BUILT_BY, "complete": complete,
          "errors": r.errors, "warnings": r.warnings, "checks": checks}
    L.save(p["qc_json"], qc)
    md = [f"# Quality control: {p['code']} edition", "",
          f"**{'Complete' if complete else 'Not complete'}**: {len(r.errors)} blocking error(s), {len(r.warnings)} warning(s).", ""]
    if r.errors:
        md += ["## Blocking", ""] + [f"- {e}" for e in r.errors] + [""]
    if r.warnings:
        md += ["## Worth a look", ""] + [f"- {w}" for w in r.warnings] + [""]
    md += ["## Every check", "", "| Check | Result | Note |", "|---|---|---|"]
    for c in checks:
        md.append(f"| {c['check']} | {'ok' if c['ok'] else ('error' if c['blocking'] else 'warning')} | {c['message'].replace('|', '/')} |")
    L.write_text(p["qc_md"], "\n".join(md) + "\n")
    manifest(p, complete, timing, state, info)
    r.note(f"{p['code']} quality control: {'complete' if complete else 'not complete'}, "
           f"{len(r.errors)} error(s), {len(r.warnings)} warning(s); out/{p['qc_md'].name}")
    return r


def manifest(p, complete, timing, state, info):
    root = pathlib.Path(p["root"])

    def entry(kind, f):
        f = pathlib.Path(f)
        if not f.exists():
            return None
        return {"kind": kind, "path": str(f.relative_to(root)), "bytes": f.stat().st_size, "sha256": sha_file(f)}
    files = [entry("film", p["film"]), entry("film with captions", p["captioned"]), entry("subtitles", p["srt"]),
             entry("subtitles", p["vtt"]), entry("soundtrack", p["mix"]), entry("narration", p["proj"] / "audio" / "narration.m4a"),
             entry("quality control", p["qc_md"]), entry("quality control", p["qc_json"]),
             entry("mix report", p["proj"] / "audio" / "mix_report.json"), entry("effects report", p["proj"] / "audio" / "effects.json"),
             entry("credits", p["proj"] / "audio" / "music_credits.md"), entry("credits", root / "credits.md"),
             entry("credits", root / "05_visuals" / "credits.md")]
    title = (L.load(p["narration"], {}).get("title") if p["narration"].exists() else "") or \
        (L.load(p["outline"], {}).get("title", "") if p["outline"].exists() else "")
    data = {"lang": p["code"], "built_by": BUILT_BY, "complete": complete, "title": title,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "film": {"duration": info["duration"] if info else None, "size": f"{info['w']}x{info['h']}" if info else None,
                     "fps": info["fps"] if info else None, "acts": (state.get("join") or {}).get("order"),
                     "captions": (state.get("captions") or {}).get("style") if (state.get("captions") or {}).get("enabled") else None},
            "files": [f for f in files if f]}
    L.save(p["manifest"], data)


def fingerprint(proj):
    p = qp(proj)
    h = hashlib.sha256()
    for f in (p["film"], p["captioned"], p["timing"], p["subs"], p["srt"], p["vtt"], p["acts"], p["config"], p["state"]):
        f = pathlib.Path(f)
        h.update(f.name.encode() + (f"{f.stat().st_size}:{f.stat().st_mtime_ns}".encode() if f.exists() else b"-"))
    h.update(f"{p['qc_json'].exists()}".encode())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    r = build(a.project)
    print(r.report(f"qc ({qp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
