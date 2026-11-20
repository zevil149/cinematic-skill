#!/usr/bin/env python3
"""An edition's narration track and timing, from its voice segments (voice.py), then the
storyboard and scenes re-timed to it.

  python3 narrate.py --project P/editions/hi                # natural read
  python3 narrate.py --project P/editions/hi --target 300   # fit to 300 s (tempo 0.90-1.15x only)
  python3 narrate.py --project P/editions/en --no-retime    # the track and timing only
  python3 narrate.py --project P/editions/en --force        # replace a track narrate.py did not make (.bak kept)

Reads   script.json, audio/voice/manifest.json, audio/voice/segments/ and manual/ (never written)
Writes  audio/narration.m4a (-16 LUFS), audio/timing.json, audio/voice/build/ (a cache of parts)
Then    04_scenes/storyboard.* (when there is one) and 06_film/ (when scenegen has run) re-timed

Each line's audio is its manual recording if there is one, else its segment (yours when edited).
Silence is trimmed off both ends of every line, so the pacing is set here: lead, each line's
gap_after (0.45 s, 1.0 s after a take, as the script says) and tail. Nothing is called that
costs money: lines without audio are reported (voice.py synth makes them).

timing.json is the film's clock, as before (id, caption, vo, start, end, duration per line), plus
"lang" and per-line "words": [{"w", "start", "end"}] in film seconds. Words come from the voice
where it gave reliable timings (ElevenLabs, and the mock) and from the language's own timing rules
otherwise ("words_from": "voice" | "estimate"). doc.W uses them, so the camera lands on the word.

A run with the same inputs (the same audio files, script, pacing and tempo) changes nothing. A
narration.m4a or timing.json that narrate.py did not make, or that changed since, is yours: it is
never replaced without --force, and --force keeps it as .bak.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import wave
import array

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import lang  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402

TEMPO_LIMITS = (0.90, 1.15)
RATE = 48000
SILENT = 0.003        # about -50 dBFS: quieter than this at either end of a line is trimmed
PAD = 0.03            # kept around the speech when trimming (s)
BUILT_BY = "narrate.py"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))}... failed: {r.stderr.strip()[-400:]}")
    return r


def speech_bounds(path):
    """(t0, t1, duration) of the speech in a 16-bit WAV: 10 ms windows louder than SILENT."""
    with wave.open(str(path), "rb") as w:
        rate, n, width = w.getframerate(), w.getnframes(), w.getsampwidth()
        ch = w.getnchannels()
        data = w.readframes(n)
    if width != 2:
        raise V.ProviderError(f"{path.name}: {8 * width}-bit; 16-bit WAV expected")
    a = array.array("h"); a.frombytes(data)
    if ch > 1:
        a = a[::ch]
    dur = len(a) / float(rate)
    win = max(1, rate // 100)
    thr = SILENT * 32768
    loud = [i for i in range(0, len(a), win) if max(a[i:i + win]) > thr or min(a[i:i + win]) < -thr]
    if not loud:
        return 0.0, 0.0, dur
    t0 = max(0.0, loud[0] / rate - PAD)
    t1 = min(dur, (loud[-1] + win) / rate + PAD)
    return round(t0, 4), round(t1, 4), dur


def wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def estimate_words(lg, spoken, dur):
    """Word times inside a line by the language's own timing rules, when the voice gave none."""
    toks = [m.group(0) for m in lang.TOKEN.finditer(spoken)]
    if not toks:
        return []
    weights = [max(0.12, lg.est_seconds(t)) for t in toks]
    s, acc, out = sum(weights), 0.0, []
    for t, wt in zip(toks, weights):
        a, b = dur * acc / s, dur * (acc + wt) / s
        out.append({"w": t, "start": a, "end": a + (b - a) * 0.92})
        acc += wt
    return out


def voice_words(entry, spoken, t0, t1):
    """The provider's word times for this segment, moved to the trimmed audio; None if they do not
    match the line's words (a segment you edited, or another text)."""
    words = (entry or {}).get("words")
    toks = [m.group(0) for m in lang.TOKEN.finditer(spoken)]
    if not words or len(words) != len(toks):
        return None
    out = []
    for w in words:
        a = min(max(w["start"] - t0, 0.0), t1 - t0)
        b = min(max(w["end"] - t0, a), t1 - t0)
        out.append({"w": w["w"], "start": a, "end": b})
    return out


def lines_of(p, r):
    s = L.load(p["script_json"], {}) if p["script_json"].exists() else {}
    tag = s.get("lang") or "en"
    if not s:
        r.error("no script.json: export the script first"); return []
    if tag != p["code"]:
        r.error(f"script.json is the {tag} script; this is the {p['code']} edition"); return []
    out = []
    for t in s.get("takes", []):
        for k, l in enumerate(t["lines"]):
            last = k == len(t["lines"]) - 1
            out.append({"id": l["id"], "take": t["take"], "section": t.get("section", t["take"]), "caption": l.get("text", ""),
                        "vo": (l.get("spoken") or l.get("text", "")).strip(),
                        "gap_after": float(l.get("gap_after", L.TAKE_GAP if last else L.GAP))})
    # a film of several acts holds a silence before each act after the first: its title card
    starts = L.act_starts(L.load(p["outline"], {}) if p["outline"].exists() else {}, [(x["id"], x["section"]) for x in out])
    if starts:
        acts = L.section_acts(L.load(p["outline"]))
        for prev, x in zip(out, out[1:]):
            if x["id"] in starts:
                prev["gap_after"] = max(prev["gap_after"], L.ACT_GAP)
        for x in out:
            x["act"] = acts.get(x["section"], 1)
    return out


def owned(p, timing_p, track):
    """Is the existing track and timing ours (made by narrate.py and unchanged)? None when absent."""
    if not track.exists() and not timing_p.exists():
        return None
    t = L.load(timing_p, {}) if timing_p.exists() else {}
    if t.get("built_by") != BUILT_BY or not track.exists():
        return False
    return voice.sha_file(track) == t.get("narration_sha256")


def build(proj, target=0.0, lead=L.LEAD, tail=L.TAIL, force=False, retime=True, log=print):
    p = voice.vp(proj)
    r = L.Result()
    code = p["code"]
    timing_p, track = p["timing"], p["proj"] / "audio" / "narration.m4a"
    old = L.load(timing_p, {}) if timing_p.exists() else {}
    if old.get("lang") and old["lang"] != code and not force:
        r.error(f"audio/timing.json is the {old['lang']} voice; this is the {code} edition "
                f"(--force replaces it, keeping a .bak)"); return r
    if not shutil.which("ffmpeg"):
        r.error("ffmpeg is not installed: it resamples the lines and encodes narration.m4a"); return r
    lines = lines_of(p, r)
    if not r.ok:
        return r
    v = voice.validate(proj)                     # the voice's own checks: missing, invalid, silent, wrong language
    rows = {x["line"]: x for x in (voice.plan(proj)[1] or {}).get("rows", [])} if v.ok else {}
    r.extend(v)
    if not r.ok:
        r.error("the voice is not complete: voice.py synth makes the missing lines (paid voices only with "
                "--confirm-cost); nothing was built"); return r
    stale = [str(i) for i, x in rows.items() if x["state"] == "stale"]
    if stale:
        r.error(f"line(s) {', '.join(stale)} were voiced from older text or settings: voice.py synth makes them "
                f"again; nothing was built"); return r
    man = voice.load_manifest(p)
    lg = lang.for_paths(p)
    plan_rows = []
    for l in lines:
        st = rows.get(l["id"], {}).get("state")
        f = (p["manual"] if st == "manual" else p["segments"]) / voice.seg_name(l["id"])
        t0, t1, dur = speech_bounds(f)
        if t1 <= t0:
            r.error(f"line {l['id']}: {f.name} has no speech"); continue
        entry = man.get("segments", {}).get(str(l["id"]))
        words = voice_words(entry, l["vo"], t0, t1) if st == "ok" else None
        plan_rows.append({**l, "file": f, "file_sha": voice.sha_file(f), "state": st, "t0": t0, "t1": t1,
                          "words": words})
    if not r.ok:
        return r
    speech = sum(x["t1"] - x["t0"] for x in plan_rows)
    fixed = lead + tail + sum(x["gap_after"] for x in plan_rows[:-1])
    tempo = 1.0 if target <= 0 else speech / (target - fixed) if target > fixed else 0.0
    if not TEMPO_LIMITS[0] <= tempo <= TEMPO_LIMITS[1]:
        r.error(f"tempo {tempo:.3f} is outside {TEMPO_LIMITS} for a {target:g}s film ({speech:.1f}s of speech + "
                f"{fixed:.1f}s of pauses): make the script shorter or longer instead"); return r
    key = sha(json.dumps({"lang": code, "lead": lead, "tail": tail, "tempo": round(tempo, 6), "rate": RATE,
                          "lines": [(x["id"], x["file_sha"], x["t0"], x["t1"], x["gap_after"], x["vo"], x["caption"],
                                     x["words"] is not None) + ((x["act"],) if "act" in x else ()) for x in plan_rows]},
                         ensure_ascii=False))
    mine = owned(p, timing_p, track)
    if mine and old.get("build_hash") == key:
        r.note(f"{code} narration is up to date ({old.get('total_duration')}s, {len(plan_rows)} lines); nothing rebuilt")
        if retime:
            r.extend(retime_scenes(proj))
        return r
    if mine is False:
        if not force:
            r.error("audio/narration.m4a or audio/timing.json was not made by narrate.py, or was changed since: "
                    "it is yours and left as it is (--force replaces it, keeping both as .bak)"); return r
        for f in (track, timing_p):
            if f.exists():
                shutil.copyfile(f, f.with_name(f.name + ".bak"))
                r.note(f"your {f.name} kept as {f.name}.bak")

    work = p["vdir"] / "build"
    parts_dir = work / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    timeline, parts, cursor = [], [], lead

    def silence(sec):
        f = parts_dir / f"silence_{int(round(sec * 1000))}ms.wav"
        if not f.exists():
            V.write_wav(f, [0] * int(round(sec * RATE)), RATE)
        return f
    for x in plan_rows:
        x["part"] = parts_dir / f"L{int(x['id']):04d}_{sha(json.dumps([x['file_sha'], x['t0'], x['t1'], round(tempo, 6)]))}.wav"
    make_parts([x for x in plan_rows if not x["part"].exists()], tempo)    # resume: once per audio and tempo
    parts.append(silence(lead))
    for i, x in enumerate(plan_rows):
        part = x["part"]
        d = wav_seconds(part)
        raw = x["t1"] - x["t0"]
        if x["words"] is not None:
            ws, src = x["words"], "voice"
        else:
            ws, src = estimate_words(lg, x["vo"], raw), "estimate"
        k = d / raw if raw > 0 else 1.0
        words = [{"w": w["w"], "start": round(cursor + w["start"] * k, 3), "end": round(cursor + w["end"] * k, 3)} for w in ws]
        seg_ = {"id": x["id"], "scene": x["take"], "caption": x["caption"], "vo": x["vo"],
                         "start": round(cursor, 3), "end": round(cursor + d, 3), "duration": round(d, 3),
                         "words": words, "words_from": src,
                         "audio": "manual" if x["state"] == "manual" else "edited" if x["state"] == "edited" else "voice"}
        if "act" in x:
            seg_["act"] = x["act"]
        timeline.append(seg_)
        parts.append(part)
        cursor += d
        if i < len(plan_rows) - 1:
            parts.append(silence(x["gap_after"])); cursor += x["gap_after"]
    parts.append(silence(tail))
    total = round(cursor + tail, 3)

    joined = work / "narration.wav"
    with wave.open(str(joined), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)
        for f in parts:
            with wave.open(str(f), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))
    tmp_track = track.with_name("narration.tmp.m4a")
    track.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
         "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(tmp_track)])
    tmp_track.replace(track)
    L.save(timing_p, {"lang": code, "built_by": BUILT_BY, "source": "voice", "build_hash": key,
                      "narration_sha256": voice.sha_file(track), "total_duration": total, "lead_in": lead,
                      "tail_out": tail, "tempo": round(tempo, 4), "segments": timeline})
    est = sum(1 for s in timeline if s["words_from"] == "estimate")
    log(f"{code} narration: {len(timeline)} lines, {total:.2f}s, tempo {tempo:.4f}"
        + (f"; word times estimated for {est} line(s)" if est else "; word times from the voice"))
    r.note(f"audio/narration.m4a and audio/timing.json for {code}: {len(timeline)} lines, {L.mmss(total)}")
    if retime:
        r.extend(retime_scenes(proj))
    return r


def make_parts(todo, tempo, batch=48):
    """Trim, re-time and resample lines to 48 kHz mono, many lines per ffmpeg call. Each part is
    written to a temporary name first, so an interrupted run never leaves half a part."""
    for k in range(0, len(todo), batch):
        chunk = todo[k:k + batch]
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for x in chunk:
            cmd += ["-i", str(x["file"])]
        for n, x in enumerate(chunk):
            af = f"atrim={x['t0']:.4f}:{x['t1']:.4f},asetpts=PTS-STARTPTS" + (f",atempo={tempo:.6f}" if tempo != 1.0 else "")
            cmd += ["-map", f"{n}:a", "-af", af, "-ar", str(RATE), "-ac", "1", "-sample_fmt", "s16",
                    str(x["part"].with_suffix(".tmp.wav"))]
        run(cmd)
        for x in chunk:
            x["part"].with_suffix(".tmp.wav").replace(x["part"])


def retime_scenes(proj):
    """The storyboard and the scene starters follow the voice. scenegen keeps edited scenes as they are."""
    p = L.paths(proj)
    r = L.Result()
    if p["storyboard"].exists():
        import storyboard
        r.extend(storyboard.build(proj))
        if (p["film_dir"] / "acts.json").exists():
            import scenegen
            r.extend(scenegen.generate(proj))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--target", type=float, default=0.0, help="finished length in seconds; 0 keeps the natural read")
    ap.add_argument("--lead", type=float, default=L.LEAD, help="silence before the first word (s)")
    ap.add_argument("--tail", type=float, default=L.TAIL, help="hold after the last word (s)")
    ap.add_argument("--force", action="store_true", help="replace a narration narrate.py did not make (kept as .bak)")
    ap.add_argument("--no-retime", action="store_true", help="leave the storyboard and scenes as they are")
    a = ap.parse_args()
    r = build(a.project, a.target, a.lead, a.tail, a.force, not a.no_retime)
    print(r.report(f"narration ({voice.vp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
