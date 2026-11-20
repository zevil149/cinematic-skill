#!/usr/bin/env python3
"""An edition's music and sound-effects cue sheet, and its mix.

  python3 cuesheet.py init  --project P/editions/hi     # audio/cues.json: a synthesised bed under the film
  python3 cuesheet.py plan  --project P/editions/hi     # every cue resolved to times, and what blocks the mix
  python3 cuesheet.py mix   --project P/editions/hi [--force]   # audio/mix.m4a, mix_report.json, music_credits.md

The library (audiolib.py) is shared by the production; the cue sheet is this edition's own, placed
on this edition's narration timing (audio/timing.json from narrate.py), so the English and Hindi
films each get their own cues, levels and mix.

audio/cues.json:
  {"lang": "hi",
   "music": [{"id": "M1", "asset": "synth:bed", "from": {"film": "start"}, "to": {"section": "s03", "edge": "start"},
              "gain_db": -8, "fade_in": 2.0, "fade_out": 3.0, "duck": true},
             {"id": "M2", "asset": "A001", "from": {"line": 14, "word": "storm", "shift": -0.5}, "to": {"film": "end"},
              "offset": 12.0, "loop": false, "gain_db": -10, "fade_in": 1.0, "fade_out": 4.0}],
   "sfx":   [{"id": "S1", "asset": "A004", "at": {"line": 9, "edge": "start"}, "gain_db": -6}],
   "gaps":  [{"from": {"section": "s04", "edge": "start", "shift": -1.5}, "to": {"line": 22, "edge": "start"}, "fade": 0.4}],
   "synth_sfx": {"use": true, "file": "audio/sfx.wav", "gain_db": -7},
   "duck": {"db": -12, "threshold": 0.015, "attack": 0.08, "release": 0.6},
   "loudness": {"lufs": -15, "true_peak": -1.5}}
Anchors: {"t": 12.5}, {"film": "start" | "end"}, {"line": 7, "edge": "start" | "end", "word": "storm"},
{"section": "s02" (or its take), "edge": "start" | "end"}, each with an optional "shift" in seconds.
"synth:bed" is a quiet bed made here from code (a low drone and pulse that fall silent into each
section change): nothing to license. Effects are synthesised by default (render.py --cues, then
build_sfx.py writes audio/sfx.wav); library sounds are optional.

The mix: music (faded, levelled, silent in the gaps) ducks under the narration; effects ride on top;
a limiter and two-pass loudness bring it to -15 LUFS integrated with a -1.5 dBTP ceiling. It is then
checked: loudness within 1 LU, true peak, no clipped samples, and the narration at least 10 dB over
the music while it speaks (under 6 dB is an error). Any uncleared or changed asset, a cue sheet or
timing of another language, or missing narration stops the mix before anything is written.

Resume: the same inputs make nothing new. narration.m4a, the library files and audio/sfx.wav are
only read. A mix.m4a cuesheet.py did not make (mix_soundtrack.py's, yours) or that changed since is
never replaced without --force, which keeps it as .bak.
"""
import argparse
import datetime
import hashlib
import json
import math
import pathlib
import shutil
import subprocess
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audiolib  # noqa: E402
import doclib as L  # noqa: E402

SR = 48000
WIN = 0.02                       # analysis window for ducking and the intelligibility check (s)
BUILT_BY = "cuesheet.py"
DEFAULTS = {"synth_sfx": {"use": True, "file": "audio/sfx.wav", "gain_db": -7.0},
            "duck": {"db": -12.0, "threshold": 0.015, "attack": 0.08, "release": 0.6},
            "loudness": {"lufs": -15.0, "true_peak": -1.5}}
LOUDNESS_TOL, MIN_MARGIN, GOOD_MARGIN = 1.0, 6.0, 10.0


def cp(proj):
    p = L.paths(proj)
    a = p["proj"] / "audio"
    return {**p, "cues": a / "cues.json", "mix": a / "mix.m4a", "report": a / "mix_report.json",
            "credits": a / "music_credits.md", "build": a / "mix_build", "narration_track": a / "narration.m4a",
            "code": p["lang"] or "en"}


def sha_file(path):
    return audiolib.sha_file(path)


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


# ------------------------------------------------------------------------------- the cue sheet

def default_sheet(code):
    return {"lang": code, "version": 1,
            "music": [{"id": "M1", "asset": "synth:bed", "from": {"film": "start"}, "to": {"film": "end"},
                       "gain_db": -8.0, "fade_in": 2.0, "fade_out": 3.0, "duck": True}],
            "sfx": [], "gaps": [], **json.loads(json.dumps(DEFAULTS))}


def init(proj, log=print):
    p = cp(proj)
    r = L.Result()
    if p["cues"].exists():
        r.note(f"{p['cues'].relative_to(p['proj'])} exists; left as it is"); return r
    L.save(p["cues"], default_sheet(p["code"]))
    log(f"audio/cues.json for {p['code']}: a synthesised bed under the whole film; edit it to place library music and sounds")
    return r


def load_timing(p, r):
    if not p["timing"].exists():
        r.error("no audio/timing.json: build the narration first (narrate.py)"); return None
    t = L.load(p["timing"])
    tag = t.get("lang")
    if (p["lang"] and tag != p["lang"]) or (not p["lang"] and tag not in (None, "en")):
        r.error(f"audio/timing.json is the {tag or 'untagged'} voice; this is the {p['code']} edition"); return None
    return t


def sections_of(p, timing):
    """{section or take: (start, end)} from the edition's script and timing."""
    s = L.load(p["script_json"], {})
    seg = {x["id"]: x for x in timing.get("segments", [])}
    out = {}
    for t in s.get("takes", []):
        ids = [l["id"] for l in t["lines"] if l["id"] in seg]
        if ids:
            span = (seg[ids[0]]["start"], seg[ids[-1]]["end"])
            out[t.get("section", t["take"])] = span
            out.setdefault(t["take"], span)
    return out


def resolve(anchor, timing, sections, what):
    """Seconds into the film for one anchor."""
    if not isinstance(anchor, dict):
        raise ValueError(f"{what}: an anchor is an object like {{\"line\": 3}}, not {anchor!r}")
    total = timing["total_duration"]
    shift = float(anchor.get("shift", 0) or 0)
    edge = anchor.get("edge", "start")
    if "t" in anchor:
        t = float(anchor["t"])
    elif "film" in anchor:
        t = 0.0 if anchor["film"] == "start" else total
    elif "line" in anchor:
        seg = next((x for x in timing["segments"] if x["id"] == anchor["line"]), None)
        if seg is None:
            raise ValueError(f"{what}: line {anchor['line']} is not in this edition's timing")
        if anchor.get("word"):
            toks = [w for w in seg.get("words") or []]
            hit = next((w for w in toks if anchor["word"].lower() in w["w"].lower()), None)
            if hit is None:
                raise ValueError(f"{what}: {anchor['word']!r} is not a timed word of line {anchor['line']}")
            t = hit["start"] if edge == "start" else hit["end"]
        else:
            t = seg["start"] if edge == "start" else seg["end"]
    elif "section" in anchor:
        if anchor["section"] not in sections:
            raise ValueError(f"{what}: section {anchor['section']!r} is not in this edition ({', '.join(sorted(sections))})")
        a, b = sections[anchor["section"]]
        t = a if edge == "start" else b
    else:
        raise ValueError(f"{what}: unknown anchor {anchor!r}")
    t += shift
    if not -1e-6 <= t <= total + 1e-6:
        raise ValueError(f"{what}: {t:.2f}s is outside the film (0 to {total:.2f}s)")
    return min(max(t, 0.0), total)


def plan(proj, r=None):
    """The cue sheet resolved against this edition's timing and the shared library."""
    p = cp(proj)
    r = r or L.Result()
    if not p["cues"].exists():
        r.error("no audio/cues.json: cuesheet.py init"); return r, None
    sheet = L.load(p["cues"])
    if sheet.get("lang", p["code"]) != p["code"]:
        r.error(f"audio/cues.json is the {sheet.get('lang')} edition's cue sheet; this is {p['code']}"); return r, None
    timing = load_timing(p, r)
    if timing is None:
        return r, None
    if not p["narration_track"].exists():
        r.error("no audio/narration.m4a: build the narration first (narrate.py)"); return r, None
    cfg = {k: {**DEFAULTS[k], **(sheet.get(k) or {})} for k in DEFAULTS}
    sections = sections_of(p, timing)
    lib = {a["id"]: a for a in audiolib.load(proj)["assets"]}
    used, music, sfx, gaps = {}, [], [], []

    def asset(cue, kind):
        aid = cue.get("asset", "")
        if aid == "synth:bed":
            if kind != "music":
                r.error(f"{cue.get('id')}: synth:bed is music, not an effect"); return None
            return {"id": "synth:bed", "source": "synth", "kind": "music", "title": "Synthesised bed",
                    "license": {"code": "SYNTH", "label": "made here from code", "url": ""}, "attribution": ""}
        a = lib.get(aid)
        if a is None:
            r.error(f"{cue.get('id')}: asset {aid!r} is not in the library (audiolib.py add)"); return None
        if a["kind"] != kind:
            r.error(f"{cue.get('id')}: {aid} is {a['kind']}, used as {kind}"); return None
        why = audiolib.usable(proj, a)
        if why:
            r.error(f"{cue.get('id')}: {why}"); return None
        used[aid] = a
        return a

    for c in sheet.get("music", []):
        a = asset(c, "music")
        try:
            t0 = resolve(c.get("from", {"film": "start"}), timing, sections, f"{c.get('id')} from")
            t1 = resolve(c.get("to", {"film": "end"}), timing, sections, f"{c.get('id')} to")
        except ValueError as e:
            r.error(str(e)); continue
        if t1 - t0 < 0.5:
            r.error(f"{c.get('id')}: plays {t1 - t0:.2f}s ({t0:.2f}-{t1:.2f}); a music cue needs at least 0.5s"); continue
        fi, fo = float(c.get("fade_in", 2.0)), float(c.get("fade_out", 3.0))
        if fi + fo > t1 - t0:
            r.warn(f"{c.get('id')}: fades ({fi + fo:.1f}s) are longer than the cue ({t1 - t0:.1f}s); shortened")
            k = (t1 - t0) / (fi + fo); fi, fo = fi * k, fo * k
        if a is None:
            continue
        span = t1 - t0
        if a.get("duration") and not c.get("loop") and a["duration"] - float(c.get("offset", 0)) < span - 0.05:
            r.warn(f"{c.get('id')}: {a['id']} lasts {a['duration']:.1f}s from offset {float(c.get('offset', 0)):.1f}s, "
                   f"shorter than the cue ({span:.1f}s); it ends early (\"loop\": true repeats it)")
        music.append({"id": c.get("id"), "asset": a["id"], "t0": round(t0, 3), "t1": round(t1, 3),
                      "offset": float(c.get("offset", 0)), "loop": bool(c.get("loop")), "gain_db": float(c.get("gain_db", -8)),
                      "fade_in": round(fi, 3), "fade_out": round(fo, 3), "duck": c.get("duck", True) is not False,
                      "sha": a.get("sha256", "synth"), "seed": int(c.get("seed", 7))})
    for c in sheet.get("sfx", []):
        a = asset(c, "sfx")
        try:
            t = resolve(c.get("at", {}), timing, sections, f"{c.get('id')} at")
        except ValueError as e:
            r.error(str(e)); continue
        if a is not None:
            sfx.append({"id": c.get("id"), "asset": a["id"], "t": round(t, 3), "gain_db": float(c.get("gain_db", -6)),
                        "sha": a["sha256"]})
    for n, g in enumerate(sheet.get("gaps", [])):
        try:
            a_, b_ = resolve(g.get("from", {}), timing, sections, f"gap {n + 1} from"), resolve(g.get("to", {}), timing, sections, f"gap {n + 1} to")
        except ValueError as e:
            r.error(str(e)); continue
        if b_ <= a_:
            r.error(f"gap {n + 1}: ends ({b_:.2f}s) before it starts ({a_:.2f}s)"); continue
        gaps.append({"t0": round(a_, 3), "t1": round(b_, 3), "fade": float(g.get("fade", 0.4))})
    synth = cfg["synth_sfx"]
    sfx_file = p["proj"] / synth["file"] if synth.get("use") else None
    if sfx_file is not None and not sfx_file.exists():
        r.note(f"no {synth['file']} (render.py --cues, then build_sfx.py): mixing without synthesised effects")
        sfx_file = None
    info = {"p": p, "timing": timing, "sections": sections, "music": music, "sfx": sfx, "gaps": gaps, "cfg": cfg,
            "used": used, "sfx_file": sfx_file, "total": timing["total_duration"]}
    r.note(f"{p['code']} cue sheet: {len(music)} music cue(s), {len(sfx)} library sound(s), {len(gaps)} gap(s)"
           + (", synthesised effects" if sfx_file else "") + f", {L.mmss(info['total'])}")
    return r, info


# ------------------------------------------------------------------------------------- audio

def np_():
    import numpy
    return numpy


def decode(path, offset=0.0, dur=None, loop=False):
    """Any audio file -> float32 stereo at 48 kHz, through ffmpeg; the file is only read."""
    np = np_()
    cmd = ["ffmpeg", "-v", "error"] + (["-stream_loop", "-1"] if loop else []) + \
          (["-ss", f"{offset:.3f}"] if offset else []) + (["-t", f"{dur:.3f}"] if dur else []) + \
          ["-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "pipe:1"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"could not read {pathlib.Path(path).name}: {out.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(out.stdout, dtype=np.float32).reshape(-1, 2).astype(np.float64)


def synth_bed(total, section_starts, seed=7):
    """A quiet documentary bed made from code: a low drone (root, fifth, octave) breathing slowly,
    a soft pulse once a second, falling silent for a breath into every section change. Stereo,
    about -20 dBFS RMS, nothing to license."""
    np = np_()
    n = int(round(total * SR))
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    root = 55.0 * 2 ** (rng.integers(0, 5) / 12.0)
    drone = sum(a * np.sin(2 * np.pi * root * m * t + rng.uniform(0, 6.28)) for m, a in ((1, 0.55), (1.5, 0.3), (2, 0.18), (3, 0.06)))
    drone *= 0.75 + 0.25 * np.sin(2 * np.pi * t / 17.0)
    pulse = np.zeros(n)
    k = np.arange(int(0.35 * SR)) / SR
    thump = np.sin(2 * np.pi * (root * 1.0) * k) * np.exp(-k / 0.09)
    for beat in np.arange(0.5, total, 1.0):
        i = int(beat * SR)
        j = min(n, i + len(thump))
        pulse[i:j] += thump[: j - i] * (0.5 if int(beat) % 4 == 0 else 0.3)
    mono = drone + pulse
    env = np.ones(n)
    for s in section_starts:
        a, b = int((s - 1.6) * SR), int((s + 0.6) * SR)
        for i0, i1, v0, v1 in ((a, a + int(0.5 * SR), 1, 0), (b - int(0.1 * SR), b + int(1.2 * SR), 0, 1)):
            i0c, i1c = max(0, i0), min(n, i1)
            if i1c > i0c:
                env[i0c:i1c] = np.minimum(env[i0c:i1c], np.linspace(v0, v1, i1 - i0)[i0c - i0:i1c - i0])
        lo, hi = max(0, a + int(0.5 * SR)), min(n, b - int(0.1 * SR))
        if hi > lo:
            env[lo:hi] = 0
    mono *= env
    rms = math.sqrt(float(np.mean(mono ** 2))) or 1.0
    mono *= 0.1 / rms
    stereo = np.stack([mono * 0.96 + 0.04 * np.roll(mono, 240), mono * 0.96 + 0.04 * np.roll(mono, -240)], axis=1)
    return np.clip(stereo, -0.9, 0.9)


def ramp_gain(n, t0, t1, fi, fo):
    np = np_()
    g = np.ones(n)
    a, b = int(fi * SR), int(fo * SR)
    if a > 0:
        g[:min(a, n)] = np.linspace(0, 1, a)[:min(a, n)]
    if b > 0:
        g[max(0, n - b):] = np.minimum(g[max(0, n - b):], np.linspace(1, 0, b)[-min(b, n):])
    return g


def windows_rms(x):
    """RMS of a mono signal in WIN windows."""
    np = np_()
    w = int(WIN * SR)
    m = len(x) // w
    if m == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(x[: m * w].reshape(m, w) ** 2, axis=1))


def duck_curve(voice_mono, n, duck):
    """Music gain per sample: down by duck['db'] while the narrator speaks, with attack and release
    (the dip starts a little before each line, so the first word is never covered)."""
    np = np_()
    rms = windows_rms(voice_mono)
    speech = rms > duck["threshold"]
    look = int(round(duck["attack"] / WIN))
    if look:
        ahead = np.zeros_like(speech)
        for k in range(1, look + 1):
            ahead[:-k] |= speech[k:]
        speech = speech | ahead
    target = np.where(speech, 10 ** (duck["db"] / 20.0), 1.0)
    g = np.ones_like(target)
    a_c = math.exp(-WIN / max(1e-3, duck["attack"]))
    r_c = math.exp(-WIN / max(1e-3, duck["release"]))
    cur = 1.0
    for i, v in enumerate(target):
        c = a_c if v < cur else r_c
        cur = v + (cur - v) * c
        g[i] = cur
    per = np.repeat(g, int(WIN * SR))
    if len(per) < n:
        per = np.concatenate([per, np.full(n - len(per), per[-1] if len(per) else 1.0)])
    return per[:n], speech


def gap_curve(n, gaps):
    np = np_()
    g = np.ones(n)
    for x in gaps:
        a, b, f = int(x["t0"] * SR), int(x["t1"] * SR), max(1, int(x["fade"] * SR))
        g[max(0, a):min(n, b)] = 0
        lo = max(0, a - f)
        if a > lo:
            g[lo:a] = np.minimum(g[lo:a], np.linspace(1, 0, a - lo))
        hi = min(n, b + f)
        if hi > b:
            g[b:hi] = np.minimum(g[b:hi], np.linspace(0, 1, hi - b))
    return g


def place(bus, sig, at):
    i = int(round(at * SR))
    if i >= len(bus):
        return
    j = min(len(bus), i + len(sig))
    bus[i:j] += sig[: j - i]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-600:]}")
    return r


def measure(path):
    """Integrated loudness (LUFS) and true peak (dBTP) by ffmpeg's EBU R128 meter."""
    import re
    r = run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = r.stderr[r.stderr.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    return (float(i.group(1)) if i else float("nan")), (float(tp.group(1)) if tp else float("nan"))


# --------------------------------------------------------------------------------------- mix

def owned(p):
    if not p["mix"].exists():
        return None
    rep = L.load(p["report"], {}) if p["report"].exists() else {}
    return rep.get("built_by") == BUILT_BY and sha_file(p["mix"]) == rep.get("mix_sha256")


def mix(proj, force=False, log=print):
    p = cp(proj)
    r, info = plan(proj)
    if info is None or not r.ok:
        r.error("nothing was mixed"); return r
    if not shutil.which("ffmpeg"):
        r.error("ffmpeg is not installed"); return r
    try:
        np = np_()
    except ImportError:
        r.error("numpy is not installed (pip install numpy)"); return r
    cfg, total = info["cfg"], info["total"]
    key = sha({"by": BUILT_BY, "lang": p["code"], "music": info["music"], "sfx": info["sfx"], "gaps": info["gaps"],
               "cfg": cfg, "total": total, "narration": sha_file(p["narration_track"]),
               "sections": sorted(info["sections"].items()),
               "sfx_file": sha_file(info["sfx_file"]) if info["sfx_file"] else None})
    mine = owned(p)
    rep = L.load(p["report"], {}) if p["report"].exists() else {}
    if mine and rep.get("input_hash") == key:
        r.note(f"{p['code']} mix is up to date ({rep.get('lufs')} LUFS); nothing remixed"); return r
    if mine is False:
        if not force:
            r.error("audio/mix.m4a was not made by cuesheet.py, or was changed since: it is yours and left as it is "
                    "(--force replaces it, keeping it as mix.m4a.bak)"); return r
        shutil.copyfile(p["mix"], p["mix"].with_name("mix.m4a.bak"))
        r.note("your mix.m4a kept as mix.m4a.bak")

    n = int(round(total * SR))
    fit = lambda x: np.concatenate([x, np.zeros((max(0, n - len(x)), 2))])[:n]  # noqa: E731
    voice = fit(decode(p["narration_track"]))
    vmono = voice.mean(axis=1)
    music = np.zeros((n, 2)); music_raw = np.zeros((n, 2))
    starts = [a for a, _ in sorted(set(info["sections"].values()))][1:]
    bed = None
    for c in info["music"]:
        span = c["t1"] - c["t0"]
        if c["asset"] == "synth:bed":
            if bed is None:
                bed = synth_bed(total, starts, c["seed"])
            sig = bed[int(c["t0"] * SR):int(c["t1"] * SR)]
        else:
            sig = decode(audiolib.lib_paths(proj)["dir"] / info["used"][c["asset"]]["file"], c["offset"], span, c["loop"])
        g = ramp_gain(len(sig), c["t0"], c["t1"], c["fade_in"], c["fade_out"]) * 10 ** (c["gain_db"] / 20.0)
        sig = sig * g[:, None]
        place(music if c["duck"] else music_raw, sig, c["t0"])
    gaps = gap_curve(n, info["gaps"])
    duck, speech = duck_curve(vmono, n, cfg["duck"])
    music_bus = music * (duck * gaps)[:, None] + music_raw * gaps[:, None]
    sfx = np.zeros((n, 2))
    if info["sfx_file"]:
        sfx += fit(decode(info["sfx_file"])) * 10 ** (cfg["synth_sfx"]["gain_db"] / 20.0)
    for c in info["sfx"]:
        place(sfx, decode(audiolib.lib_paths(proj)["dir"] / info["used"][c["asset"]]["file"]) * 10 ** (c["gain_db"] / 20.0), c["t"])
    # intelligibility: the narration over the music, while it speaks
    vr, mr = windows_rms(vmono), windows_rms(music_bus.mean(axis=1))
    m = min(len(vr), len(mr), len(speech))
    both = speech[:m] & (mr[:m] > 1e-5)
    margin = float(np.median(20 * np.log10(np.maximum(vr[:m][both], 1e-9) / mr[:m][both]))) if both.any() else None
    pre = voice + music_bus + sfx
    p["build"].mkdir(parents=True, exist_ok=True)
    raw = p["build"] / f"premix_{key}.f32"
    raw.write_bytes(pre.astype(np.float32).tobytes())
    lufs, tp = cfg["loudness"]["lufs"], cfg["loudness"]["true_peak"]
    src = ["-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw)]
    chain = "alimiter=limit=0.89:level=disabled"
    first = run(["ffmpeg", "-v", "info", "-y", *src, "-af", f"{chain},loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json",
                 "-f", "null", "-"])
    import re
    mm = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", first.stderr, re.S).group(0))
    ln = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={mm['input_i']}:measured_TP={mm['input_tp']}:"
          f"measured_LRA={mm['input_lra']}:measured_thresh={mm['input_thresh']}:offset={mm['target_offset']}:linear=true")
    tmp = p["mix"].with_name("mix.tmp.m4a")
    run(["ffmpeg", "-v", "error", "-y", *src, "-af", f"{chain},{ln},aresample={SR}", "-ar", str(SR), "-c:a", "aac", "-b:a", "256k", str(tmp)])
    raw.unlink()
    # validation of what came out
    got_i, got_tp = measure(tmp)
    out = decode(tmp)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    clipped = int(np.sum(np.abs(out) >= 0.9999))
    dur = len(out) / SR
    problems, warns = [], []
    if not abs(got_i - lufs) <= LOUDNESS_TOL:
        problems.append(f"integrated loudness {got_i:.1f} LUFS is not within {LOUDNESS_TOL} LU of {lufs}")
    if not got_tp <= tp + 0.5:
        problems.append(f"true peak {got_tp:.1f} dBTP is over the {tp} dBTP ceiling")
    if clipped:
        problems.append(f"{clipped} clipped sample(s)")
    if abs(dur - total) > 0.25:
        problems.append(f"the mix lasts {dur:.2f}s; the narration timing says {total:.2f}s")
    if margin is not None and margin < MIN_MARGIN:
        problems.append(f"the narration is only {margin:.1f} dB over the music while it speaks (at least {MIN_MARGIN} dB): "
                        f"lower the music (gain_db) or duck it more")
    elif margin is not None and margin < GOOD_MARGIN:
        warns.append(f"the narration is {margin:.1f} dB over the music while it speaks; {GOOD_MARGIN} dB or more reads clearly")
    if problems:
        tmp.unlink()
        for x in problems:
            r.error(f"mix check: {x}")
        r.error("the mix failed its checks; nothing was written"); return r
    for x in warns:
        r.warn(x)
    tmp.replace(p["mix"])
    assets = [{"id": a["id"], "kind": a["kind"], "title": a.get("title", ""), "creator": a.get("creator", ""),
               "source": a["source"], "license": a["license"]["label"], "license_url": a["license"].get("url", ""),
               "attribution": a.get("attribution", ""), "attribution_required": bool(a.get("attribution_required")),
               "cleared_by": a["clearance"].get("by", ""), "override": bool(a["clearance"].get("override")),
               "sha256": a["sha256"]} for a in info["used"].values()]
    report = {"lang": p["code"], "built_by": BUILT_BY, "input_hash": key, "mix_sha256": sha_file(p["mix"]),
              "at": datetime.datetime.now().isoformat(timespec="seconds"), "duration": round(dur, 3),
              "lufs": round(got_i, 2), "true_peak_dbtp": round(got_tp, 2), "sample_peak": round(peak, 4), "clipped_samples": clipped,
              "target_lufs": lufs, "ceiling_dbtp": tp, "voice_over_music_db": None if margin is None else round(margin, 1),
              "duck_db": cfg["duck"]["db"], "music": info["music"], "sfx": info["sfx"], "gaps": info["gaps"],
              "synth_sfx": bool(info["sfx_file"]), "assets": assets}
    L.save(p["report"], report)
    write_credits(p, assets, info)
    log(f"{p['code']} mix: {dur:.1f}s, {got_i:.1f} LUFS, true peak {got_tp:.1f} dBTP"
        + (f", narration {margin:.1f} dB over the music" if margin is not None else ""))
    r.note(f"audio/mix.m4a for {p['code']}: {got_i:.1f} LUFS, {got_tp:.1f} dBTP, no clipping")
    return r


def write_credits(p, assets, info):
    lines = [f"# Music and sound credits ({p['code']})", "",
             "Written by cuesheet.py from the audio library. Every asset below was cleared before it was mixed.", ""]
    if any(c["asset"] == "synth:bed" for c in info["music"]):
        lines.append("- Music bed: synthesised for this film (no third-party material).")
    if info["sfx_file"]:
        lines.append("- Sound effects: synthesised for this film (no samples).")
    for a in assets:
        txt = a["attribution"] or f"{a['title']} ({a['license']})"
        lines.append(f"- {txt}" + ("" if a["attribution_required"] else "") + (" [cleared by override]" if a["override"] else ""))
    L.write_text(p["credits"], "\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "plan", "mix"):
        s = sub.add_parser(name); s.add_argument("--project", required=True)
        if name == "mix":
            s.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init":
        r = init(a.project)
    elif a.cmd == "plan":
        r, info = plan(a.project)
        for c in (info or {}).get("music", []):
            print(f"  music {c['id']:<4} {c['asset']:<10} {L.mmss(c['t0'])}-{L.mmss(c['t1'])}  {c['gain_db']:+.1f} dB"
                  f"  fades {c['fade_in']:.1f}/{c['fade_out']:.1f}s{'  ducked' if c['duck'] else ''}")
        for c in (info or {}).get("sfx", []):
            print(f"  sfx   {c['id']:<4} {c['asset']:<10} {L.mmss(c['t'])}  {c['gain_db']:+.1f} dB")
        for g in (info or {}).get("gaps", []):
            print(f"  gap        {L.mmss(g['t0'])}-{L.mmss(g['t1'])}")
    else:
        r = mix(a.project, a.force)
    print(r.report(f"cue sheet ({cp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
