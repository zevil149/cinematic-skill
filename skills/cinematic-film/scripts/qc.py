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
  sound      no line is silent; and, against audio/narration.m4a, every line's narration is in the
             film: over the voice's own speech frames (pauses left out), aligned by cross-correlation,
             the correlation gives the narration's share of the sound and the projection its gain.
             A share under -10 dB (missing, or buried under music and effects) is an error; under
             +3 dB (masked) and a line 10 dB quieter than the others are warnings; a line spoken
             quietly keeps its share and is not flagged. Silences of a second or more outside the
             lead-in, the pauses, the title cards' silence and the tail; clipping (true peak above
             -0.1 dBTP is an error); integrated loudness against the mix report's target (more than
             1 LU off is a warning, more than 2 LU an error)
  subtitles  the SRT and VTT parse cue by cue (a text line that is only a number is text), match
             audio/subs.json in count and times, sit on their lines in the current timing and inside
             the film; burned captions are visible where lines are spoken
  layout     from the scenes' own geometry (layoutcheck.py): card titles and lines that do not fit
             their card, and measured text that an opaque burned caption would cover (warnings)
A check that cannot be made (no narration track, no mix report, no skia, captions off) is listed as
not checked, with the reason; it never counts as passed. qc.json keeps every measurement.
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


NARR_FRAME = 0.02            # seconds: the narration is compared frame by frame where it speaks
SPEECH_FLOOR_DB = -30.0      # a frame counts as speech within 30 dB of the line's loudest frame
MISSING_DB, MASKED_DB, QUIET_DB = -10.0, 3.0, -10.0
LUFS_WARN, LUFS_ERROR = 1.0, 2.0


def narration_presence(film, narr, rate, segs):
    """How much of the film's sound, while each line speaks, is that line's narration.

    The narration track is the reference: its speech frames (pauses and breaths left out) are
    compared with the same instants of the film, after aligning the two by cross-correlation. The
    film's sound there is the narration at some gain plus everything else (music, effects); their
    correlation c gives the narration's share, nrr = c^2 / (1 - c^2) as a level ratio in dB, and the
    projection gives the narration's gain in the film. A quiet line keeps its share (only the
    ratio to the rest counts); a line whose voice is missing from the film, or drowned, does not.
    Returns (lag in seconds, [{"line", "speech_s", "corr", "nrr_db", "gain_db"}])."""
    import numpy as np
    n = min(len(film), len(narr), int(120 * rate))
    lag = 0
    if n > rate:
        N = 1 << int(np.ceil(np.log2(2 * n)))
        xc = np.fft.irfft(np.fft.rfft(film[:n], N) * np.conj(np.fft.rfft(narr[:n], N)), N)
        m = int(0.5 * rate)
        cand = np.concatenate([xc[N - m:], xc[:m + 1]])                      # lags -m..m
        lag = int(np.argmax(np.abs(cand))) - m
    fr = max(1, int(NARR_FRAME * rate))
    out = []
    for s in segs:
        a, b = int(s["start"] * rate), int(s["end"] * rate)
        src = narr[a:b]
        k = len(src) // fr
        if k == 0:
            out.append({"line": s["id"], "speech_s": 0.0, "corr": None, "nrr_db": None, "gain_db": None}); continue
        e = (src[:k * fr].reshape(k, fr) ** 2).mean(axis=1)
        keep = e > max(e.max() * 10 ** (SPEECH_FLOOR_DB / 10), 1e-7)
        idx = np.nonzero(keep)[0]
        if not len(idx):
            out.append({"line": s["id"], "speech_s": 0.0, "corr": None, "nrr_db": None, "gain_db": None}); continue
        sel = (idx[:, None] * fr + np.arange(fr)[None, :]).ravel() + a
        fsel = sel + lag
        ok = (fsel >= 0) & (fsel < len(film))
        x, y = narr[sel[ok]].astype(np.float64), film[fsel[ok]].astype(np.float64)
        xx, yy, xy = float(x @ x), float(y @ y), float(x @ y)
        c = xy / np.sqrt(xx * yy) if xx > 0 and yy > 0 else 0.0
        c2 = min(max(c, 0.0) ** 2, 0.9999)
        nrr = 10 * np.log10(max(c2, 1e-8) / (1 - c2))
        gain = 20 * np.log10(max(xy / xx, 1e-6)) if xx > 0 else None
        out.append({"line": s["id"], "speech_s": round(len(x) / rate, 2), "corr": round(float(c), 3),
                    "nrr_db": round(float(nrr), 1), "gain_db": None if gain is None else round(float(gain), 1)})
    return lag / rate, out


def build(proj, log=print):
    import finish
    p = qp(proj)
    r = L.Result()
    checks = []

    measures = {}

    def check(name, ok, msg, blocking=True, seen=""):
        """msg says what is wrong; seen, what was measured when it is right."""
        checks.append({"check": name, "ok": bool(ok), "blocking": blocking, "message": seen if ok else msg})
        if not ok:
            (r.error if blocking else r.warn)(f"{name}: {msg}")

    def unchecked(name, why):
        """A check that could not be made here: said so, never counted as passed or failed."""
        checks.append({"check": name, "ok": None, "blocking": False, "message": why})
        r.note(f"{name}: not checked ({why})")
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
        check("film", False, f"{film.relative_to(p['proj'])} is missing"); return finish_report(p, r, checks, timing, state, measures=measures)
    try:
        info = finish.probe(film)
    except ValueError as e:
        check("film", False, f"{film.name} cannot be read: {e}"); return finish_report(p, r, checks, timing, state, measures=measures)
    check("film", True, "", seen=f"{film.name}: {info['w']}x{info['h']}, {info['fps']:g} fps, {info['duration']:.2f}s")
    check("video codec", info["vcodec"] == "h264", f"video is {info['vcodec']}, not h264", blocking=False, seen=info["vcodec"])
    check("audio stream", bool(info["audio"]), "the film has no audio stream", seen=str(info["audio"]))
    want_size = j.get("size") or state.get("size")
    if want_size:
        check("size", f"{info['w']}x{info['h']}" == want_size, f"{info['w']}x{info['h']}, rendered at {want_size}", seen=want_size)
    fps = j.get("fps") or 30.0
    check("frame rate", abs(info["fps"] - fps) < 0.01, f"{info['fps']:g} fps, rendered at {fps:g}", seen=f"{fps:g} fps")
    cd = float(j.get("credits") or 0.0)                   # the closing credits after the timeline (rights.py, credits.py)
    end = total + cd
    tail = f" and {cd:.2f}s of credits" if cd else ""
    check("duration", abs(info["duration"] - end) <= 0.1, f"{info['duration']:.2f}s, the timeline is {total:.2f}s{tail}",
          seen=f"{info['duration']:.2f}s, the timeline {total:.2f}s{tail}")
    check("frames", abs(info["frames"] - round(end * info["fps"])) <= 2,
          f"{info['frames']} frames, {round(end * info['fps'])} expected: the render is incomplete",
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
    leftovers = sorted(f.name for f in p["out"].rglob("*") if f.name.endswith((".rendering.mp4", ".joining.mp4", ".burning.mp4", ".parts")))
    if leftovers:
        check("interrupted renders", False, f"{', '.join(leftovers)} left by an interrupted run; nothing uses them", blocking=False)
    # picture: black frames outside the fades and declared spans
    cards = [(a["title_card"]["t0"] - 0.3, a["title_card"]["t1"] + 0.3) for a in acts if a.get("title_card")]
    allowed_black = [(0.0, FADE_IN + 0.3), (total - FADE_OUT - 0.3, total + FADE_IN + 0.3 if cd else total + 1)] + \
        ([(end - FADE_OUT - 0.3, end + 1)] if cd else []) + cards + \
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
    narr_file = p["proj"] / "audio" / "narration.m4a"
    if audio is not None and len(audio):
        def rms(a, b):
            x = audio[int(a * rate):int(b * rate)]
            return float(np.sqrt((x ** 2).mean())) if len(x) else 0.0
        silent = [s["id"] for s in segs if rms(s["start"], s["end"]) < 0.003]
        check("sound during lines", not silent, f"line(s) {', '.join(map(str, silent))} are silent in the film",
              seen=f"sound under all {len(segs)} lines")
        if narr_file.exists():
            narr, _ = decode_audio(narr_file, rate)
            lag, lines = narration_presence(audio, narr, rate, segs)
            gains = [x["gain_db"] for x in lines if x["gain_db"] is not None and x["nrr_db"] is not None and x["nrr_db"] > MASKED_DB]
            ref = float(np.median(gains)) if gains else None
            no_src = [x["line"] for x in lines if x["corr"] is None]
            missing = [x["line"] for x in lines if x["nrr_db"] is not None and x["nrr_db"] < MISSING_DB]
            masked = [x for x in lines if x["nrr_db"] is not None and MISSING_DB <= x["nrr_db"] < MASKED_DB]
            quiet = [x for x in lines if ref is not None and x["gain_db"] is not None and x["line"] not in missing
                     and x["gain_db"] - ref < QUIET_DB]
            measures["narration"] = {"lag_ms": round(lag * 1000, 1), "reference_gain_db": None if ref is None else round(ref, 1),
                                     "min_nrr_db": min((x["nrr_db"] for x in lines if x["nrr_db"] is not None), default=None),
                                     "lines": lines}
            if no_src:
                check("narration source", False, f"line(s) {', '.join(map(str, no_src))} are silent in audio/narration.m4a")
            check("narration", not missing, f"line(s) {', '.join(map(str, missing))}: the narration is missing from the film there, "
                  "or buried under the music and effects (its share of the sound is under "
                  f"{MISSING_DB:g} dB)", seen=f"every line's narration found in the film (lowest share "
                  f"{measures['narration']['min_nrr_db']} dB over the rest, aligned at {lag * 1000:+.0f} ms)")
            if masked:
                check("narration masking", False, "line(s) " + ", ".join(f"{x['line']} ({x['nrr_db']:+.1f} dB)" for x in masked[:8]) +
                      ": the narration is barely above the music and effects there", blocking=False)
            if quiet:
                check("narration level", False, "line(s) " + ", ".join(f"{x['line']} ({x['gain_db'] - ref:+.1f} dB)" for x in quiet[:8]) +
                      " are much quieter in the film than the other lines", blocking=False)
        else:
            unchecked("narration", "no audio/narration.m4a to compare the film with; only silence under the lines was checked")
    allowed_quiet = [(0.0, (segs[0]["start"] if segs else 0) + 0.3)]
    for a_, b_ in zip(segs, segs[1:]):
        allowed_quiet.append((a_["end"] - 0.2, b_["start"] + 0.3))         # the pauses, title cards included
    if segs:
        allowed_quiet.append((segs[-1]["end"] - 0.2, end + 1))                 # the tail, and the credits (silent)
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
    mrep = p["proj"] / "audio" / "mix_report.json"
    target = L.load(mrep, {}).get("target_lufs") if mrep.exists() else None
    measures["loudness"] = {"integrated_lufs": None if lufs != lufs else round(lufs, 1), "target_lufs": target,
                            "true_peak_dbtp": None if tp != tp else round(tp, 1)}
    if tp != tp:
        unchecked("clipping", "ffmpeg's loudness meter gave no true peak for the film")
    else:
        check("clipping", not tp > -0.1, f"true peak {tp:.1f} dBTP: the sound clips", seen=f"true peak {tp:.1f} dBTP")
        if -0.1 >= tp > -1.0:
            check("headroom", False, f"true peak {tp:.1f} dBTP, close to clipping", blocking=False)
    if lufs != lufs:
        unchecked("loudness", "ffmpeg's loudness meter gave no integrated loudness for the film")
    elif target is None:
        unchecked("loudness", f"the film measures {lufs:.1f} LUFS; no mix report says what it was meant to be")
    else:
        d = lufs - float(target)
        check("loudness", abs(d) <= LUFS_ERROR,
              f"the film measures {lufs:.1f} LUFS, the mix was made for {target:g} LUFS ({d:+.1f} LU)",
              seen=f"{lufs:.1f} LUFS integrated, made for {target:g} ({d:+.1f} LU)")
        if LUFS_WARN < abs(d) <= LUFS_ERROR:
            check("loudness drift", False, f"the film measures {lufs:.1f} LUFS, {d:+.1f} LU from the mix's {target:g}", blocking=False)
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
        import subtitles
        want = subs.get("cues", [])
        for f, parse in ((p["srt"], subtitles.parse_srt), (p["vtt"], subtitles.parse_vtt)):
            if not f.exists():
                continue
            kind = f.suffix[1:].upper()
            try:
                got, probs = parse(f.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                check(f"{kind} file", False, f"{f.name} is not UTF-8 text"); continue
            check(f"{kind} file", not probs, f"{f.name} is malformed: " + "; ".join(probs[:5]), seen=f"{len(got)} cues parsed")
            edited = rec.get(str(f.relative_to(p["proj"]))) != sha_file(f)
            if probs or edited:
                continue
            same = len(got) == len(want) and all(abs(a["t0"] - b["t0"]) < 0.002 and abs(a["t1"] - b["t1"]) < 0.002
                                                 for a, b in zip(got, want))
            check(f"{kind} cues", same, f"{f.name} has {len(got)} cue(s), audio/subs.json {len(want)}, or their times differ: "
                  "make the subtitles again (subtitles.py)", seen=f"{len(got)} cues, times as in audio/subs.json")
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
    layout(p, timing, total, cap, check, unchecked, measures)
    rights_and_credits(proj, p, state, check, unchecked, measures, r)
    return finish_report(p, r, checks, timing, state, info, measures=measures)


def rights_and_credits(proj, p, state, check, unchecked, measures, r):
    """Every asset the film uses may be used (rights.py), and the credits that need giving are in it."""
    try:
        import rights
        rr, report = rights.check(proj)
    except ImportError as e:
        unchecked("rights", f"cannot read the scenes here ({e})"); return
    if not report:
        check("rights", False, "; ".join(rr.errors)); return
    used = report["images"] + report["footage"] + report["audio"]
    bad = [a for a in used if not a["usable"]]
    cleared = [a for a in used if a["usable"] and a.get("cleared")]
    measures["rights"] = {"used": len(used), "not_usable": [a["id"] for a in bad], "cleared_by_a_person": [a["id"] for a in cleared],
                          "maps": len(report["maps"]), "report": f"out/{rights.rp(proj)['report'].name}"}
    check("rights", not bad, "; ".join(f"{a['media']} {a['id']}: {a['basis']}" for a in bad[:6]) +
          (f" and {len(bad) - 6} more" if len(bad) > 6 else ""),
          seen=f"{len(used)} asset(s) used, each free as stated, your own as stated, or cleared" + (" (none needs rights)" if not used else ""))
    if cleared:
        check("clearances", False, "; ".join(f"{a['id']}: {a['basis']}" for a in cleared[:6]) +
              " (a person's clearance, recorded; check it before publishing)", blocking=False)
    for w in rr.warnings:
        check("map licence", False, w, blocking=False)
    import finish
    lines = finish.credits_lines(p, report)
    import credits
    owed = credits.lines_for(report, p["code"])
    cd = float((state.get("join") or {}).get("credits") or 0)
    if not owed:
        check("credits", True, "", seen="nothing used needs crediting on screen")
    elif not lines:
        check("credits", False, "credits.json turns the closing credits off while the film uses credited assets: "
              "give the attributions where it is published (credits.md)", blocking=False)
    else:
        check("credits", cd > 0, "the film has no closing credits although it uses credited assets: render and join again",
              seen=f"{sum(1 for k, _ in lines if k == 'line')} credit line(s), {cd:.1f}s at the end")


def layout(p, timing, total, cap, check, unchecked, measures, size=(960, 540)):
    """Text that overflows its card, and measured text under the burned captions (layoutcheck.py)."""
    try:
        import numpy  # noqa: F401
        import skia  # noqa: F401
    except ImportError:
        unchecked("text fit", "skia-python or numpy is not installed"); unchecked("caption clearance", "skia-python or numpy is not installed")
        return
    import finish
    import layoutcheck
    import review
    from engine import Doc, Res
    films = []
    try:
        doc = Doc(p["proj"])
        for n, scene, s, e, _, _ in finish.acts_of(p, total):
            films.append((s, e if e < total else total + 1, review.load_act(scene).build_film(doc)))
    except BaseException as ex:                                   # noqa: BLE001 - a scene that does not build here
        why = f"the scenes do not build here ({type(ex).__name__}: {str(ex)[:120]})"
        unchecked("text fit", why); unchecked("caption clearance", why)
        return
    W, H = size
    res = Res(W / 3840.0, doc.prep, doc.dir / "fonts")
    census = layoutcheck.census(films)
    measured = {k: v for k, v in census.items() if k in layoutcheck.MEASURED}
    other = {k: v for k, v in census.items() if k not in layoutcheck.MEASURED}
    over = [o for _, _, f in films for o in layoutcheck.overflows(f, res)]
    measures["layout"] = {"measured_items": measured, "unmeasured_items": other, "overflows": over}
    note = "; text of " + ", ".join(f"{v} {k}" for k, v in sorted(other.items())) + " is not measured" if other else ""
    check("text fit", not over, "; ".join(f"{o['kind']} at {o['t']:.1f}s: {o['what']} by {o['over'] * 100:.0f}% ({o['text'][:40]!r})"
                                          for o in over[:6]) + (f" and {len(over) - 6} more" if len(over) > 6 else ""),
          blocking=False, seen=f"all text fits its card ({', '.join(f'{v} {k}' for k, v in sorted(measured.items())) or 'no measured text'}){note}")
    import engine
    used = layoutcheck.fonts_used(films)
    resolved = {role: engine.resolve_typeface(role, p["proj"] / "fonts")[1] for role in used}
    fallback = {k: v for k, v in resolved.items() if v.startswith("system default")}
    measures["layout"]["fonts"] = resolved
    check("fonts", not fallback, "; ".join(f"{k}: {v}" for k, v in fallback.items()) +
          " (get_fonts.py or fonts/<role>.ttf pins a font; Devanagari always uses the bundled Noto Sans Devanagari)",
          blocking=False, seen=", ".join(f"{k}: {v}" for k, v in resolved.items()) or "no measured text")
    acts = sorted(L.load(p["acts"], {}).get("acts", []), key=lambda a: a["act"]) if p["acts"].exists() else []
    allowed = [(0.0, FADE_IN + 0.3), (total - FADE_OUT - 0.3, total + 1)] + \
        [(a["title_card"]["t0"] - 0.3, a["title_card"]["t1"] + 0.3) for a in acts if a.get("title_card")]
    holds = layoutcheck.empty_holds(films, doc, total, allowed)
    measures["layout"]["empty_holds"] = holds
    check("empty frames", not holds, "; ".join(f"{a:.1f}-{b:.1f}s" for a, b in holds[:6]) +
          ": the camera holds still on bare board (nothing measured in frame)", blocking=False,
          seen="no still frame of bare board outside the fades and title cards")
    if not cap.get("enabled"):
        unchecked("caption clearance", "burned-in captions are off")
        return
    from captions import Captions
    capt = Captions(cap.get("style", "clean"), W, H, timing, fonts_dir=p["proj"] / "fonts", highlight=cap.get("highlight", "auto"))
    hits = layoutcheck.collisions(films, capt, W, H, lambda f: res)
    measures["layout"]["caption_collisions"] = hits
    check("caption clearance", not hits, "; ".join(f"{h['kind']} {h['text'][:30]!r} at {h['t']:.1f}s, {h['cover'] * 100:.0f}% under the caption"
                                                   for h in hits[:6]) + (f" and {len(hits) - 6} more" if len(hits) > 6 else ""),
          blocking=False, seen=f"no measured text under the captions at {len(capt.chunks)} caption(s)")


def grab(video, t):
    import numpy as np
    import finish
    i = finish.probe(video)
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "pipe:1"], capture_output=True).stdout
    return np.frombuffer(out, np.uint8).reshape(i["h"], i["w"], 3)


def finish_report(p, r, checks, timing, state, info=None, measures=None):
    complete = r.ok
    qc = {"lang": p["code"], "built_by": BUILT_BY, "complete": complete,
          "errors": r.errors, "warnings": r.warnings, "checks": checks,
          "not_checked": [c["check"] for c in checks if c["ok"] is None], "measurements": measures or {}}
    L.save(p["qc_json"], qc)
    md = [f"# Quality control: {p['code']} edition", "",
          f"**{'Complete' if complete else 'Not complete'}**: {len(r.errors)} blocking error(s), {len(r.warnings)} warning(s), "
          f"{len(qc['not_checked'])} check(s) not made.", ""]
    if r.errors:
        md += ["## Blocking", ""] + [f"- {e}" for e in r.errors] + [""]
    if r.warnings:
        md += ["## Worth a look", ""] + [f"- {w}" for w in r.warnings] + [""]
    if qc["not_checked"]:
        md += ["## Not checked", ""] + [f"- {c['check']}: {c['message']}" for c in checks if c["ok"] is None] + [""]
    ms = qc["measurements"]
    if ms.get("loudness") or ms.get("narration"):
        md += ["## Measurements", ""]
        lo = ms.get("loudness") or {}
        if lo:
            md.append(f"- Loudness: {lo.get('integrated_lufs')} LUFS integrated (made for {lo.get('target_lufs')}), "
                      f"true peak {lo.get('true_peak_dbtp')} dBTP")
        na = ms.get("narration")
        if na:
            md.append(f"- Narration: lowest share {na['min_nrr_db']} dB over the music and effects, aligned at {na['lag_ms']:+.0f} ms; "
                      "per line in qc.json")
        md.append("")
    md += ["## Every check", "", "| Check | Result | Note |", "|---|---|---|"]
    for c in checks:
        res = "not checked" if c["ok"] is None else "ok" if c["ok"] else ("error" if c["blocking"] else "warning")
        md.append(f"| {c['check']} | {res} | {c['message'].replace('|', '/')} |")
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
             entry("rights", p["out"] / f"rights.{p['code']}.json"), entry("credits sequence", p["out"] / f"credits.{p['code']}.mp4"),
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
                     "captions": (state.get("captions") or {}).get("style") if (state.get("captions") or {}).get("enabled") else None,
                     "timeline": (state.get("join") or {}).get("timeline"), "credits": (state.get("join") or {}).get("credits")},
            "rights": _rights_summary(p),
            "files": [f for f in files if f]}
    L.save(p["manifest"], data)


def _rights_summary(p):
    f = p["out"] / f"rights.{p['code']}.json"
    if not f.exists():
        return None
    rep = L.load(f)
    used = rep.get("images", []) + rep.get("footage", []) + rep.get("audio", [])
    return {"usable": rep.get("usable"), "note": rep.get("note"),
            "assets": [{k: a.get(k) for k in ("id", "media", "what", "license", "credit", "source", "basis", "usable")} for a in used],
            "maps": [{k: m.get(k) for k in ("id", "source", "license", "credit")} for m in rep.get("maps", [])]}


def fingerprint(proj):
    p = qp(proj)
    h = hashlib.sha256()
    import rights
    rp_ = rights.rp(proj)
    for f in (p["film"], p["captioned"], p["timing"], p["subs"], p["srt"], p["vtt"], p["acts"], p["config"], p["state"],
              rp_["manifest"], rp_["selection"], rp_["photos_json"], rp_["footage_json"], rp_["map_json"], rp_["mix_report"],
              p["proj"] / "credits.json"):
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
