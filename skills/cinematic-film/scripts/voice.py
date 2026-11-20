#!/usr/bin/env python3
"""The narration voice of one language edition: one WAV segment per narration line, with a manifest
that records how each was made, so runs resume, edits are never overwritten, and an edition never
gets another language's voice.

  python3 voice.py init      --project P/editions/hi [--provider espeak] [--voice hi]
  python3 voice.py plan      --project P/editions/hi      # what would be made, characters, estimated cost
  python3 voice.py synth     --project P/editions/hi [--only 3,4] [--force] [--max-cost 5] [--confirm-cost]
  python3 voice.py validate  --project P/editions/hi      # missing, invalid, stale, edited, outliers
  python3 voice.py status    --project P/editions/hi
  python3 voice.py review    --project P/editions/hi --by "Reviewer name"   # native-speaker review of the script
  python3 voice.py providers

--project is an edition folder (or a single-language project, which is English).

Files (all inside the edition):
  voice.json                       provider, voice, model, settings for this language only
  audio/voice/segments/L0012.wav   one segment per line, made by the provider
  audio/voice/manual/L0012.wav     your own recording of a line: always used, never touched
  audio/voice/manifest.json        per line: text, spoken text, request hash, file hash, duration,
                                   levels, word timings, status; tagged with the edition's language
  audio/voice/spend.json           every paid request (paid providers arrive in milestone 3.4)

A line is made again only when it is missing, its file is invalid, or its request changed (the
spoken text after the lexicon, provider, model, voice, settings or language: the request hash).
A segment file that differs from what was recorded is yours (edited) and is locked; --force makes
it again and keeps yours as .bak. Manual files are never touched, even with --force.

Providers with reliable word timings read a whole section at once and the section is cut into line
segments; the others read line by line. A paid provider needs an estimate under the cap ($5 a run
by default), --confirm-cost, and for Hindi a native-speaker review of the current script.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import lang  # noqa: E402
import voices as V  # noqa: E402

DEFAULT_CAP = 5.0
MIN_SECONDS, MIN_RMS, CLIP_PEAK = 0.05, 0.002, 0.99


def vp(proj):
    p = L.paths(proj)
    d = p["proj"] / "audio" / "voice"
    return {**p, "voice_json": p["proj"] / "voice.json", "vdir": d, "segments": d / "segments", "manual": d / "manual",
            "sections": d / "sections", "manifest": d / "manifest.json", "spend": d / "spend.json",
            "review": p["script_dir"] / "review.json", "code": p["lang"] or "en"}


def seg_name(line_id):
    return f"L{int(line_id):04d}.wav"


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def default_config(code):
    lg = lang.get(code)
    return {"lang": code, "locale": lg.locale, "provider": "espeak", "voice": V.Espeak().default_voice(code),
            "model": "", "settings": {"wpm": int(lg.wpm)}, "mode": "auto",
            "note": "scratch voice; the final voice is chosen by audition (milestone 3.4)"}


def init(proj, provider="espeak", voice="", force=False):
    p = vp(proj)
    if p["voice_json"].exists() and not force:
        print(f"{p['voice_json']} exists; leaving it alone"); return False
    cfg = default_config(p["code"])
    cfg["provider"] = provider
    cfg["voice"] = voice or V.get(provider).default_voice(p["code"])
    L.save(p["voice_json"], cfg)
    print(f"voice.json for {p['code']}: {provider} {cfg['voice']!r}")
    return True


def load_config(p, r):
    """The edition's voice.json, checked: its language, the provider's, and the voice's locale."""
    if not p["voice_json"].exists():
        r.error(f"no voice.json in {p['proj']}: run voice.py init"); return None, None
    cfg = L.load(p["voice_json"])
    code = p["code"]
    if cfg.get("lang") != code:
        r.error(f"voice.json is for {cfg.get('lang')!r}; this is the {code} edition"); return None, None
    loc = (cfg.get("locale") or "").lower()
    if loc and not loc.startswith(code):
        r.error(f"voice.json locale {cfg['locale']!r} is not {code}")
    try:
        prov = V.get(cfg.get("provider", ""), cfg)
    except V.ProviderError as e:
        r.error(str(e)); return cfg, None
    if not prov.supports(code):
        r.error(f"the {prov.name} provider does not speak {code}")
    voice_id = (cfg.get("voice") or "").lower()
    other = [c for c in lang.supported() if c != code]
    if prov.name == "espeak" and voice_id and any(voice_id == V.Espeak.VOICES.get(c) or voice_id.startswith(c + "-") for c in other):
        r.error(f"voice {cfg['voice']!r} speaks another language; the {code} edition needs a {code} voice")
    return cfg, prov


def script_lines(p, r):
    if not p["script_json"].exists():
        r.error("no script.json: export the script first (narration.py export or docpipe.py run)"); return []
    s = L.load(p["script_json"])
    tag = s.get("lang") or "en"
    if tag != p["code"]:
        r.error(f"script.json is the {tag} script; this is the {p['code']} edition"); return []
    out = []
    for t in s.get("takes", []):
        for l in t["lines"]:
            out.append({"line": l["id"], "take": t["take"], "section": t.get("section", t["take"]), "beat": l.get("beat", ""),
                        "text": l.get("text", ""), "spoken": (l.get("spoken") or l.get("text", "")).strip()})
    return out


def mode_of(cfg, prov):
    m = cfg.get("mode", "auto")
    return "section" if (m in ("auto", "section") and prov.timestamps) else "line"


def request_hash(cfg, prov, line, take_text=None):
    """Everything that shapes the audio: the provider and its whole configuration (model, voice,
    settings, a command template...), the language, and the spoken text after the lexicon."""
    conf = {k: v for k, v in cfg.items() if k not in ("note", "provider")}
    req = {"provider": prov.name, "config": conf, "spoken": line["spoken"], "take": take_text}
    return hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def take_texts(lines):
    takes = {}
    for l in lines:
        takes.setdefault(l["take"], []).append(l)
    return {k: "\n\n".join(x["spoken"] for x in v) for k, v in takes.items()}, takes


def load_manifest(p, r=None):
    m = L.load(p["manifest"], {"version": 1, "lang": p["code"], "segments": {}})
    if m.get("lang", p["code"]) != p["code"] and r is not None:
        r.error(f"audio/voice/manifest.json is the {m.get('lang')} voice; this is the {p['code']} edition")
    return m


def line_state(p, entry, line, want_hash):
    """manual | edited | missing | invalid | stale | ok, from the files and the manifest."""
    if (p["manual"] / seg_name(line["line"])).exists():
        return "manual"
    f = p["segments"] / seg_name(line["line"])
    if not f.exists():
        return "missing"
    if not entry or entry.get("source") != "provider":
        return "edited"                                   # a file nobody recorded making: yours
    if sha_file(f) != entry.get("file_sha256"):
        return "edited"
    try:
        dur, _, rms, _ = V.wav_info(f)
    except Exception:
        return "invalid"
    if dur < MIN_SECONDS or rms < MIN_RMS:
        return "invalid"
    if entry.get("request_hash") != want_hash:
        return "stale"
    return "ok"


def plan(proj, r=None):
    p = vp(proj)
    r = r or L.Result()
    cfg, prov = load_config(p, r)
    lines = script_lines(p, r)
    if not r.ok or prov is None:
        return r, None
    man = load_manifest(p, r)
    texts, takes = take_texts(lines)
    mode = mode_of(cfg, prov)
    rows = []
    for l in lines:
        h = request_hash(cfg, prov, l, texts[l["take"]] if mode == "section" else None)
        st = line_state(p, man["segments"].get(str(l["line"])), l, h)
        rows.append({**l, "state": st, "hash": h})
    todo = [x for x in rows if x["state"] in ("missing", "stale", "invalid")]
    if mode == "section":
        send_takes = sorted({x["take"] for x in todo})
        chars = sum(len(texts[t]) for t in send_takes)
    else:
        chars = sum(len(x["spoken"]) for x in todo)
    lg = lang.for_paths(p)
    allow = set(L.load(p["lexicon"], {}).get("allow", [])) if p["lexicon"].exists() else set()
    for x in rows:
        for w in lg.spoken_warnings(x["spoken"]):
            r.warn(f"line {x['line']}: {w}")
        for prob in lg.check_script(x["spoken"], allow):
            r.warn(f"line {x['line']} spoken: {prob}")
    info = {"config": cfg, "provider": prov, "mode": mode, "rows": rows, "todo": todo, "chars": chars,
            "cost": prov.estimate_cost(chars), "texts": texts, "takes": takes}
    counts = {}
    for x in rows:
        counts[x["state"]] = counts.get(x["state"], 0) + 1
    r.note(f"{p['code']} voice: {prov.name} {cfg.get('voice')!r}, {mode} mode; " +
           ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) +
           f"; {len(todo)} to make, {chars} characters" + (f", about ${info['cost']:.2f}" if prov.paid else " (free)"))
    return r, info


def script_hash(p):
    s = L.load(p["script_json"], {})
    return hashlib.sha256(json.dumps([(l.get("id"), l.get("text"), l.get("spoken")) for t in s.get("takes", [])
                                      for l in t.get("lines", [])], ensure_ascii=False).encode()).hexdigest()[:20]


def review(proj, by, note=""):
    p = vp(proj)
    if not by.strip():
        raise SystemExit("--by needs the reviewer's name")
    L.save(p["review"], {"lang": p["code"], "by": by.strip(), "note": note, "at": datetime.datetime.now().isoformat(timespec="seconds"),
                         "script_hash": script_hash(p)})
    print(f"review of the {p['code']} script recorded: {by}")


def spend_guard(p, info, max_cost, confirm, r):
    prov = info["provider"]
    if not prov.paid or not info["todo"]:
        return True
    cost = info["cost"]
    if cost > max_cost:
        r.error(f"estimated ${cost:.2f} for {info['chars']} characters is over the cap of ${max_cost:.2f}; "
                f"make fewer lines (--only) or raise --max-cost"); return False
    if not confirm:
        r.error(f"{prov.name} is a paid provider: {info['chars']} characters, about ${cost:.2f}. "
                f"Run again with --confirm-cost to spend it"); return False
    if p["code"] == "hi":
        rv = L.load(p["review"], {})
        if not rv.get("by") or rv.get("script_hash") != script_hash(p):
            r.error("paid Hindi synthesis needs a native-speaker review of the current script: voice.py review --by NAME")
            return False
    return True


def record_spend(p, prov, chars, cost, what):
    log = L.load(p["spend"], {"lang": p["code"], "requests": []})
    log["requests"].append({"at": datetime.datetime.now().isoformat(timespec="seconds"), "provider": prov.name,
                            "chars": chars, "usd": cost, "what": what})
    L.save(p["spend"], log)


def entry_for(p, l, cfg, prov, mode, h, f, words=None):
    dur, rate, rms, peak = V.wav_info(f)
    return {"line": l["line"], "take": l["take"], "section": l["section"], "beat": l["beat"], "text": l["text"],
            "spoken": l["spoken"], "request_hash": h, "file": str(f.relative_to(p["proj"])), "file_sha256": sha_file(f),
            "duration": round(dur, 3), "sample_rate": rate, "rms": round(rms, 4), "peak": round(peak, 4),
            "words": words, "status": "ok", "source": "provider", "provider": prov.name, "voice": cfg.get("voice", ""),
            "model": cfg.get("model", ""), "mode": mode, "chars": len(l["spoken"]),
            "created": datetime.datetime.now().isoformat(timespec="seconds")}


def synth(proj, only=None, force=False, max_cost=DEFAULT_CAP, confirm=False, provider=None, log=print):
    """Make every segment that needs making. provider= overrides voice.json (tests use the mock)."""
    p = vp(proj)
    r, info = plan(proj)
    if info is None:
        return r
    prov = provider or info["provider"]
    info["provider"] = prov
    cfg, mode = info["config"], mode_of(info["config"], prov)
    if provider is not None:                            # the hashes belong to the provider actually used
        for x in info["rows"]:
            x["hash"] = request_hash(cfg, prov, x, info["texts"][x["take"]] if mode == "section" else None)
    rows = info["rows"]
    if only:
        rows = [x for x in rows if x["line"] in only]
    todo = [x for x in rows if x["state"] in ("missing", "stale", "invalid") or (force and x["state"] == "edited")]
    if mode == "section":
        info["chars"] = sum(len(info["texts"][t]) for t in sorted({x["take"] for x in todo}))
    else:
        info["chars"] = sum(len(x["spoken"]) for x in todo)
    info["cost"], info["todo"] = prov.estimate_cost(info["chars"]), todo
    if not spend_guard(p, info, max_cost, confirm, r):
        return r
    man = load_manifest(p, r)
    if not r.ok:
        return r
    man["lang"] = p["code"]
    p["segments"].mkdir(parents=True, exist_ok=True)

    def keep_theirs(x):
        f = p["segments"] / seg_name(x["line"])
        if x["state"] == "edited" and f.exists():
            shutil.copyfile(f, f.with_suffix(".wav.bak"))
            r.note(f"line {x['line']}: your edited segment kept as {f.name}.bak")

    made = 0
    if mode == "section":
        for take in sorted({x["take"] for x in todo}, key=lambda t: [l["take"] for l in info["rows"]].index(t)):
            lines = info["takes"][take]
            want = {x["line"] for x in todo if x["take"] == take}
            sec = p["sections"] / f"{take}.wav"
            try:
                res = prov.synthesize(info["texts"][take], sec, p["code"], cfg.get("voice", ""), cfg.get("settings"),
                                      context=None)
                cuts = V.split_takes_by_words([(l["line"], l["spoken"]) for l in lines], res.words or [])
            except V.ProviderError as e:
                r.error(f"{take}: {e}"); continue
            if prov.paid:
                record_spend(p, prov, len(info["texts"][take]), prov.estimate_cost(len(info["texts"][take])), take)
            k = 0
            for l in lines:
                n = len(lang.TOKEN.findall(l["spoken"]))
                t0, t1 = cuts[l["line"]]
                if l["line"] in want:
                    x = next(x for x in todo if x["line"] == l["line"])
                    keep_theirs(x)
                    f = p["segments"] / seg_name(l["line"])
                    V.cut_wav(sec, f, t0, t1)
                    words = [{"w": w["w"], "start": round(w["start"] - t0, 3), "end": round(w["end"] - t0, 3)} for w in res.words[k:k + n]]
                    man["segments"][str(l["line"])] = entry_for(p, l, cfg, prov, mode, x["hash"], f, words)
                    L.save(p["manifest"], man); made += 1
                k += n
            log(f"{take}: {len(want)} line(s) from one section read")
    else:
        rows_by_take = {}
        for x in info["rows"]:
            rows_by_take.setdefault(x["take"], []).append(x)
        for x in todo:
            f = p["segments"] / seg_name(x["line"])
            sib = rows_by_take[x["take"]]
            i = sib.index(next(s for s in sib if s["line"] == x["line"]))
            ctx = {"previous": sib[i - 1]["spoken"] if i else "", "next": sib[i + 1]["spoken"] if i + 1 < len(sib) else ""}
            keep_theirs(x)
            tmp = f.with_suffix(".new.wav")
            try:
                res = prov.synthesize(x["spoken"], tmp, p["code"], cfg.get("voice", ""), cfg.get("settings"), context=ctx)
            except V.ProviderError as e:
                r.error(f"line {x['line']}: {e}"); tmp.unlink(missing_ok=True); continue
            if prov.paid:
                record_spend(p, prov, len(x["spoken"]), prov.estimate_cost(len(x["spoken"])), f"line {x['line']}")
            tmp.replace(f)
            man["segments"][str(x["line"])] = entry_for(p, x, cfg, prov, mode, x["hash"], f, res.words)
            L.save(p["manifest"], man); made += 1
            log(f"line {x['line']}: {f.name} ({man['segments'][str(x['line'])]['duration']:.2f}s)")
    for x in info["rows"]:
        if x["state"] == "manual":
            mf = p["manual"] / seg_name(x["line"])
            try:
                dur, rate, rms, peak = V.wav_info(mf)
                man["segments"][str(x["line"])] = {"line": x["line"], "take": x["take"], "section": x["section"], "beat": x["beat"],
                                                   "text": x["text"], "spoken": x["spoken"], "file": str(mf.relative_to(p["proj"])),
                                                   "file_sha256": sha_file(mf), "duration": round(dur, 3), "sample_rate": rate,
                                                   "rms": round(rms, 4), "peak": round(peak, 4), "status": "manual", "source": "manual"}
            except Exception as e:
                r.error(f"line {x['line']}: your manual file {mf.name} is not a readable 16-bit WAV ({e})")
    L.save(p["manifest"], man)
    r.note(f"made {made} segment(s)")
    r.extend(validate(proj))
    return r


def validate(proj):
    """Is every line's audio there, readable, current and plausible? Missing and invalid are errors."""
    p = vp(proj)
    r, info = plan(proj)
    if info is None:
        return r
    lg = lang.for_paths(p)
    man = load_manifest(p)
    for x in info["rows"]:
        st, lid = x["state"], x["line"]
        if st in ("missing", "invalid"):
            r.error(f"line {lid}: segment {st}")
        elif st == "stale":
            r.warn(f"line {lid}: the text, voice or settings changed since its segment was made; make it again")
        elif st == "edited":
            r.note(f"line {lid}: your edited segment is locked (synth --force replaces it, keeping a .bak)")
        if st in ("ok", "stale", "edited", "manual"):
            f = (p["manual"] if st == "manual" else p["segments"]) / seg_name(lid)
            try:
                dur, _, rms, peak = V.wav_info(f)
            except Exception as e:
                r.error(f"line {lid}: {f.name} unreadable ({e})"); continue
            if st in ("edited", "manual") and (dur < MIN_SECONDS or rms < MIN_RMS):
                r.error(f"line {lid}: {f.name} is empty or silent")
            if peak >= CLIP_PEAK:
                r.warn(f"line {lid}: {f.name} clips (peak {peak:.2f})")
            est = lg.est_seconds(x["spoken"])
            if est > 0.5 and not (0.4 <= dur / est <= 2.5):
                r.warn(f"line {lid}: {dur:.1f}s against about {est:.1f}s expected; listen to it (a cut or a stumble?)")
    stray = {int(k) for k in man.get("segments", {})} - {x["line"] for x in info["rows"]}
    for k in sorted(stray):
        r.note(f"line {k}: in the manifest but no longer in the script")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("--project", required=True); i.add_argument("--provider", default="espeak")
    i.add_argument("--voice", default=""); i.add_argument("--force", action="store_true")
    for name in ("plan", "validate", "status"):
        s = sub.add_parser(name); s.add_argument("--project", required=True)
    s = sub.add_parser("synth"); s.add_argument("--project", required=True); s.add_argument("--only", default="")
    s.add_argument("--force", action="store_true"); s.add_argument("--max-cost", type=float, default=DEFAULT_CAP)
    s.add_argument("--confirm-cost", action="store_true")
    rv = sub.add_parser("review"); rv.add_argument("--project", required=True); rv.add_argument("--by", required=True)
    rv.add_argument("--note", default="")
    sub.add_parser("providers")
    a = ap.parse_args()
    if a.cmd == "providers":
        for name, cls in V.PROVIDERS.items():
            pv = cls()
            print(f"{name:<9} {'paid' if pv.paid else 'free'}  languages: {', '.join(pv.langs) or 'any'}")
        for name, when in V.PLANNED.items():
            print(f"{name:<9} planned for {when}")
        return
    if a.cmd == "init":
        init(a.project, a.provider, a.voice, a.force); return
    if a.cmd == "review":
        review(a.project, a.by, a.note); return
    if a.cmd == "synth":
        only = {int(x) for x in a.only.split(",") if x.strip()} or None
        r = synth(a.project, only, a.force, a.max_cost, a.confirm_cost)
    elif a.cmd == "validate":
        r = validate(a.project)
    else:
        r, info = plan(a.project)
        if info and a.cmd == "status":
            for x in info["rows"]:
                print(f"  {x['line']:>4}  {x['state']:<8} {x['take']:<20} {x['spoken'][:60]}")
    print(r.report(f"voice ({vp(a.project)['code']})"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
