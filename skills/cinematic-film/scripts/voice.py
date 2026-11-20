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
  python3 voice.py audition  --project P/editions/en [--lines 8] [--confirm-cost]  # a short sample, for choosing
  python3 voice.py verify    --project P/editions/en --online   # free check that the voice id exists (ElevenLabs)
  python3 voice.py providers

--project is an edition folder (or a single-language project, which is English).

Files (all inside the edition):
  voice.json                       provider, voice, model, settings for this language only
  audio/voice/segments/L0012.wav   one segment per line, made by the provider
  audio/voice/manual/L0012.wav     your own recording of a line: always used, never touched
  audio/voice/manifest.json        per line: text, spoken text, request hash, file hash, duration,
                                   levels, word timings, status; tagged with the edition's language
  audio/voice/spend.json           every paid request of this edition: provider, characters, dollars
                                   (and rupees for Sarvam), request id; never a key
  audio/voice/auditions/<name>/    audition samples and audition.json; never used as segments

A line is made again only when it is missing, its file is invalid, or its request changed (the
spoken text after the lexicon, provider, model, voice, settings or language: the request hash).
A segment file that differs from what was recorded is yours (edited) and is locked; --force makes
it again and keeps yours as .bak. Manual files are never touched, even with --force.

Providers with reliable word timings read a whole section at once and the section is cut into line
segments; the others read line by line. A paid provider needs an estimate under the cap ($5 a run
by default), --confirm-cost, and for Hindi a native-speaker review of the current script. That
holds for auditions and retakes too. API keys come from the environment only (ELEVENLABS_API_KEY,
SARVAM_API_KEY); a voice.json that holds one is refused.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import lang  # noqa: E402
import voices as V  # noqa: E402

DEFAULT_CAP = 5.0
DEFAULT_BUDGET = 25.0          # the most a production spends on paid voices across all its runs and editions
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
            "note": "scratch voice; the final voice is chosen by audition (voice.py audition)"}


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
    secrets = V.secret_fields(cfg)
    for e in secrets:
        r.error(e)
    try:
        prov = V.get(cfg.get("provider", ""), cfg)
    except V.ProviderError as e:
        r.error(str(e)); return cfg, None
    if not prov.supports(code):
        r.error(f"the {prov.name} provider does not speak {code}")
    for e in prov.check(cfg, code):
        if e not in secrets and not e.startswith(f"the {prov.name} provider speaks"):
            r.error(e)
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
    conf = {k: v for k, v in cfg.items() if k not in V.NOT_IN_REQUEST}     # not the price or exchange rate
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
           f"; {len(todo)} to make, {chars} characters" + (f", about {prov.describe_cost(info['cost'])}" if prov.paid else " (free)"))
    if prov.paid:
        r.note(f"spent so far in the {p['code']} edition: ${spent(p):.2f} over {len(L.load(p['spend'], {}).get('requests', []))} request(s)")
        budget, total = production_budget(p)
        r.note(f"the production has spent ${total:.2f} of its ${budget:.2f} voice budget (00_topic/topic.json voice_budget_usd)")
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


def production_budget(p):
    """(budget in USD, what the production has spent so far: every edition's spend log, failed
    requests that may have been billed included). The budget is 00_topic/topic.json
    "voice_budget_usd" (default DEFAULT_BUDGET)."""
    import editions as E
    root = pathlib.Path(p["root"])
    topic = L.load(L.paths(root)["topic"], {})
    budget = float(topic.get("voice_budget_usd", DEFAULT_BUDGET))
    eds = [E.edition_dir(root, c) for c in E.editions_of(root)] or [root]
    total = sum(float(x.get("usd") or 0) for ed in eds
                for x in L.load(ed / "audio" / "voice" / "spend.json", {}).get("requests", []))
    return budget, total


def spend_guard(p, info, max_cost, confirm, r):
    prov = info["provider"]
    if not prov.paid or not info["todo"]:
        return True
    cost = info["cost"]
    for t in info.get("requests") or []:
        if prov.max_chars and len(t) > prov.limit():
            r.error(f"one request would carry {len(t)} characters; {prov.name} takes at most {prov.limit()}: "
                    f"use \"mode\": \"line\" or shorter lines (nothing was sent)"); return False
    if cost == float("inf"):
        r.error(f"{prov.name}: the cost in dollars is unknown (inr_per_usd is not set); nothing was sent"); return False
    if cost > max_cost:
        r.error(f"estimated {prov.describe_cost(cost)} for {info['chars']} characters is over the cap of ${max_cost:.2f}; "
                f"make fewer lines (--only) or raise --max-cost"); return False
    budget, total = production_budget(p)
    if total + cost > budget:
        r.error(f"this would bring the production's paid voice spending to ${total + cost:.2f} (${total:.2f} so far, "
                f"failed requests that may have been billed included), over its budget of ${budget:.2f}; raise "
                f"\"voice_budget_usd\" in 00_topic/topic.json if you mean to (nothing was sent)"); return False
    if not confirm:
        r.error(f"{prov.name} is a paid provider: {info['chars']} characters, about {prov.describe_cost(cost)}. "
                f"Run again with --confirm-cost to spend it"); return False
    if p["code"] == "hi":
        rv = L.load(p["review"], {})
        if not rv.get("by") or rv.get("script_hash") != script_hash(p):
            r.error("paid Hindi synthesis needs a native-speaker review of the current script: voice.py review --by NAME")
            return False
    return True


def spent(p):
    return sum(float(x.get("usd") or 0) for x in L.load(p["spend"], {}).get("requests", []))


def record_spend(p, prov, chars, cost, what, status="ok"):
    """One line per paid request, in this edition only. Only these named fields are written, so
    nothing from a request (headers, keys) can reach the file. status "failed, may be billed": a
    request that gave no result but may have been charged; it counts against the budget."""
    log = L.load(p["spend"], {"lang": p["code"], "requests": []})
    row = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "provider": prov.name,
           "model": prov.config.get("model", ""), "chars": chars, "usd": cost, "what": what}
    if status != "ok":
        row["status"] = status
    last = getattr(prov, "last", None) or {}
    for k in ("request_id", "billed_chars", "inr"):
        if last.get(k) not in (None, ""):
            row[k] = last[k] if k != "request_id" else str(last[k])[:80]
    if getattr(prov, "inr_per_usd", 0):
        row["inr_per_usd"] = prov.inr_per_usd
    log["requests"].append(row)
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
    if provider is not None:
        if not prov.supports(p["code"]):
            r.error(f"the {prov.name} provider does not speak {p['code']}")
        for e in prov.check(cfg, p["code"]):
            if not e.startswith(f"the {prov.name} provider speaks"):
                r.error(e)
        if not r.ok:
            return r
    if provider is not None:                            # the hashes belong to the provider actually used
        for x in info["rows"]:
            x["hash"] = request_hash(cfg, prov, x, info["texts"][x["take"]] if mode == "section" else None)
    rows = info["rows"]
    if only:
        rows = [x for x in rows if x["line"] in only]
    todo = [x for x in rows if x["state"] in ("missing", "stale", "invalid") or (force and x["state"] == "edited")]
    if mode == "section":
        info["requests"] = [info["texts"][t] for t in sorted({x["take"] for x in todo})]
    else:
        info["requests"] = [x["spoken"] for x in todo]
    info["chars"] = sum(len(t) for t in info["requests"])
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
                r.error(f"{take}: {e}")
                if prov.paid and e.maybe_billed:
                    record_spend(p, prov, len(info["texts"][take]), prov.estimate_cost(len(info["texts"][take])), take,
                                 "failed, may be billed")
                continue
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
                r.error(f"line {x['line']}: {e}"); tmp.unlink(missing_ok=True)
                if prov.paid and e.maybe_billed:
                    record_spend(p, prov, len(x["spoken"]), prov.estimate_cost(len(x["spoken"])), f"line {x['line']}",
                                 "failed, may be billed")
                continue
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


def audition(proj, lines=8, max_cost=DEFAULT_CAP, confirm=False, again=False, provider=None, log=print):
    """A short sample of this edition's voice, for choosing it: the first few lines, read one by
    one into audio/voice/auditions/, never into the segments or the manifest. A paid provider goes
    through the same guard as synth (cap, --confirm-cost, Hindi review). One audition per provider
    and edition; --again makes another (and spends again)."""
    p = vp(proj)
    r = L.Result()
    cfg, prov0 = load_config(p, r)
    script = script_lines(p, r)
    if not r.ok or prov0 is None:
        return r
    prov = provider or prov0
    if provider is not None:
        if not prov.supports(p["code"]):
            r.error(f"the {prov.name} provider does not speak {p['code']}"); return r
        for e in prov.check(cfg, p["code"]):
            r.error(e)
        if not r.ok:
            return r
    pick = [l for l in script if l["spoken"]][:max(1, int(lines))]
    root = p["vdir"] / "auditions"
    done = [d.parent.name for d in sorted(root.glob("*/audition.json")) if L.load(d, {}).get("provider") == prov.name]
    if done and not again:
        r.error(f"this edition already has a {prov.name} audition ({', '.join(done)}); listen to it, or --again "
                f"to make another (it spends again)"); return r
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{prov.name}-{cfg.get('model') or 'default'}-{cfg.get('voice') or 'default'}").strip("-")
    if again and (root / name / "audition.json").exists():
        name += "-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = root / name
    info = {"provider": prov, "todo": pick, "requests": [l["spoken"] for l in pick]}
    info["chars"] = sum(len(t) for t in info["requests"])
    info["cost"] = prov.estimate_cost(info["chars"])
    if not spend_guard(p, info, max_cost, confirm, r):
        return r
    rows, usd = [], 0.0
    for i, l in enumerate(pick):
        f = d / seg_name(l["line"])
        ctx = {"previous": pick[i - 1]["spoken"] if i else "", "next": pick[i + 1]["spoken"] if i + 1 < len(pick) else ""}
        try:
            res = prov.synthesize(l["spoken"], f, p["code"], cfg.get("voice", ""), cfg.get("settings"), context=ctx)
        except V.ProviderError as e:
            r.error(f"audition line {l['line']}: {e}")
            if prov.paid and e.maybe_billed:
                record_spend(p, prov, len(l["spoken"]), prov.estimate_cost(len(l["spoken"])), f"audition line {l['line']}",
                             "failed, may be billed")
            continue
        if prov.paid:
            c = prov.estimate_cost(len(l["spoken"])); usd += c
            record_spend(p, prov, len(l["spoken"]), c, f"audition line {l['line']}")
        rows.append({"line": l["line"], "spoken": l["spoken"], "file": str(f.relative_to(p["proj"])),
                     "duration": round(res.duration, 3), "word_timings": bool(res.words)})
        log(f"audition line {l['line']}: {f.name} ({res.duration:.2f}s)")
    if rows:
        L.save(d / "audition.json", {"lang": p["code"], "provider": prov.name, "model": cfg.get("model", ""),
                                     "voice": cfg.get("voice", ""), "settings": cfg.get("settings") or {},
                                     "lines": rows, "chars": sum(len(x["spoken"]) for x in rows), "usd": usd,
                                     "at": datetime.datetime.now().isoformat(timespec="seconds")})
        r.note(f"{len(rows)} audition line(s) in {d.relative_to(p['proj'])}" + (f", {prov.describe_cost(usd)}" if prov.paid else ""))
    return r


def verify(proj, online=False):
    """Does the configured voice exist for this key? Offline: the checks in voice.json only. With
    online=True, one free lookup where the provider has one (ElevenLabs); never a synthesis."""
    p = vp(proj)
    r = L.Result()
    cfg, prov = load_config(p, r)
    if not r.ok or prov is None:
        return r
    r.note(f"{p['code']} voice.json passes the offline checks for {prov.name}")
    if not hasattr(prov, "verify"):
        r.note(f"{prov.name} has no voice lookup; its speakers are checked offline")
    elif not online:
        r.note(f"--online looks the voice up at {prov.host} (free, no synthesis); nothing was sent")
    else:
        try:
            v = prov.verify(cfg.get("voice", ""))
            r.note(f"{prov.name} knows voice {v['voice_id']}: {v['name'] or 'unnamed'} ({v['category'] or 'no category'})")
        except V.ProviderError as e:
            r.error(str(e))
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
    au = sub.add_parser("audition"); au.add_argument("--project", required=True); au.add_argument("--lines", type=int, default=8)
    au.add_argument("--max-cost", type=float, default=DEFAULT_CAP); au.add_argument("--confirm-cost", action="store_true")
    au.add_argument("--again", action="store_true")
    ve = sub.add_parser("verify"); ve.add_argument("--project", required=True); ve.add_argument("--online", action="store_true")
    sub.add_parser("providers")
    a = ap.parse_args()
    if a.cmd == "providers":
        for name, cls in V.PROVIDERS.items():
            pv = cls()
            line = f"{name:<11} {'paid' if pv.paid else 'free'}  languages: {', '.join(pv.langs) or 'any':<4}"
            line += "  word timings (section reads)" if pv.timestamps else ""
            if pv.key_env:                                  # whether the key is there, never what it is
                line += f"  key: {pv.key_env} {'set' if os.environ.get(pv.key_env) else 'not set'}"
            print(line)
        return
    if a.cmd == "init":
        init(a.project, a.provider, a.voice, a.force); return
    if a.cmd == "review":
        review(a.project, a.by, a.note); return
    if a.cmd == "audition":
        r = audition(a.project, a.lines, a.max_cost, a.confirm_cost, a.again)
    elif a.cmd == "verify":
        r = verify(a.project, a.online)
    elif a.cmd == "synth":
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
