#!/usr/bin/env python3
"""The documentary pipeline, one command from topic to (in later phases) a finished film. Every
stage keeps its work in its own folder, records a hash of its inputs, and is skipped on the next
run when nothing it reads has changed, so an interrupted job picks up where it stopped.

  python3 docpipe.py new my-doc --topic "The Wright brothers' first flight" --minutes 10 \\
        [--angle "..."] [--audience "..."] [--look wall]
  python3 docpipe.py run --project my-doc            # run every stage that is out of date
  python3 docpipe.py run --project my-doc --until outline
  python3 docpipe.py status --project my-doc
  python3 docpipe.py approve --project my-doc outline # a person signs off a gate

Stages (phase 1):
  topic     00_topic/topic.json is complete
  research  01_research: every claim tied to sources; research.md       (research.py)
  outline   02_outline: sections, periods, claims, time budget  [gate]  (outline.py)
  script    03_script: narration fact-checked, exported to script.json  [gate]  (narration.py)
  scenes    04_scenes: storyboard with timestamps, camera, image needs  (storyboard.py)

Language editions (phase 3): `new --editions en,hi` makes one production with an edition per
language (editions/<lang>/), English first and the default. Then:
  topic, research, outline    shared
  script@<source>  [gate]     the default edition's narration, checked as above, tagged with its language
  beats                       the shared beats, built from the source narration (beats.py)
  script@<lang>    [gate]     every other edition: one line per beat, in its own language and script
  scenes@<lang>               each edition's storyboard, timed by its own voice
  visuals          [gate]     shared: one set of images for every edition
  scenegen@<lang>             each edition's scene.py starters, with its own text
  run --lang hi | --lang all chooses editions (default: the default edition); approve takes --lang.
  A project made without --editions is a single English edition, exactly as before.

Stages (phase 2):
  visuals   05_visuals: archive search, licences, downloads, fallbacks  [gate]  (visuals.py)
  scenegen  06_film: an editable scene.py starter per act               (scenegen.py)

Stage (phase 4), shared by every edition:
  assets     after the visuals gate: board textures, graded photos, footage frames and map data
             in assets/prep, made only when their sources change; prepared files you edited are
             kept (prepare.py --force replaces them with a .bak). Map boundary data that is not
             downloaded yet needs `run --download-maps`; nothing is downloaded --offline.  (prepare.py)

Stage (phase 4), per edition, last:
  review     07_review/<lang>/act_NN/: a still at each line's key word, strips of the camera moves,
             a contact sheet, automated flags (blank, near-uniform, very dark) and a checklist
             [gate "look"]: `approve --project P look --lang hi`, one approval per edition. It is the
             last stage, so waiting for a look never holds up a voice, a mix or the other edition;
             a change to a scene, the timing or the assets lapses the approval.  (review.py)

Stages (phase 5), per edition, after its look is approved:
  render     out/acts/act_NN.mp4: every act at its approved timing, through render.py (memory-aware
             parallel workers), checked frame by frame count, resumable per act  (finish.py render)
  join       out/film.<lang>.mp4: the acts in order, crossfaded where they meet, with the mix over
             the whole film; checked against the timeline  (finish.py join)
  These wait, without rendering anything, until `approve look` for that edition; `run --size
  1280x720` (default 1920x1080) and `--workers N` set the render.

Stages (phase 3), per edition (voice@<lang> ...) or for a single-language project:
  voice      audio/voice: one segment per line, from voice.json (espeak scratch voice by default)  (voice.py)
             a paid voice needs `run --confirm-cost` (and --max-cost, $5 by default); Hindi also
             needs the native-speaker review (voice.py review). Nothing paid runs without them.
  narration  audio/narration.m4a and audio/timing.json with word times; re-times the storyboard
             and scene starters (scenes you edited are kept)                (narrate.py)
  effects    audio/sfx.wav: every act's scene cues and the cue sheet's "synth_cues", synthesised
             (no samples); partial without skia or scenes (the mix goes on without)  (effects.py)
  sound      audio/cues.json (a synthesised bed to start) and the checked -15 LUFS mix.m4a, with
             only cleared library assets and audio/sfx.wav if you made it   (cuesheet.py, audiolib.py)
  subtitles  out/subtitles.<lang>.srt and .vtt, each cue marked voice-timed or estimated  (subtitles.py)
  run --until scenegen stops before the voice, as before phase 3. The run after a new voice
  re-checks the storyboard and scene starters once (they follow the voice; nothing else changes).
  Files you edited (segments, recordings, narration, timing, mix, subtitles, scenes) are never
  replaced: a stage that would need to stops with the reason, and the tool's own --force (with a
  .bak) is yours to use.

visuals talks to the archives (politely: paced, cached, and silent towards any archive that is
rate-limiting us). --offline uses cached searches only. Downloads deferred by a rate limit leave
the stage "partial": the film goes on with designed cards, and the next run retries them.

The research, outline and narration are written by the agent (or a person) into the stage files;
the pipeline scaffolds them, checks them and refuses to move on while a check fails. A stage
marked [gate] waits for `approve` before the next stage runs, and an approval lapses when the
stage's inputs change. Planned stages (effects, render, captions, report) are
listed by status and arrive in later phases; until then the film tools run as SKILL.md describes.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audiolib  # noqa: E402
import beats  # noqa: E402
import cuesheet  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import finish  # noqa: E402
import effects  # noqa: E402
import narrate  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import prepare  # noqa: E402
import research  # noqa: E402
import review  # noqa: E402
import scenegen  # noqa: E402
import storyboard  # noqa: E402
import subtitles  # noqa: E402
import visuals  # noqa: E402
import voice  # noqa: E402

LOOKS = ("wall", "slate", "charcoal", "paper", "studio", "blueprint", "night")
PLANNED = [("captions", "captions burned into the render (burn_captions.py)"),
           ("report", "final report, credits.md and QC")]


OPTS = {"offline": False, "confirm_cost": False, "max_cost": voice.DEFAULT_CAP, "download_maps": False,
        "size": finish.SIZE, "workers": 0}
AFTER_LOOK = ("render", "join")                          # stages that wait for the edition's look approval


def stage_topic(proj):
    p = L.paths(proj)
    r = L.Result()
    t = L.load(p["topic"], {})
    if not str(t.get("topic", "")).strip():
        r.error("00_topic/topic.json has no topic")
    try:
        plan = L.length_plan(t.get("minutes", 0))
        r.note(f"{plan['minutes']:g} minutes: about {plan['words']} words, {plan['chapters']} chapters, {plan['acts']} act(s)")
    except (TypeError, ValueError) as e:
        r.error(f"minutes: {e}")
    if t.get("look") and t["look"] not in LOOKS:
        r.warn(f"look {t['look']!r} is not one of {LOOKS}")
    return r


def stage_research(proj):
    return research.check(proj)


def stage_outline(proj):
    p = L.paths(proj)
    if not p["outline"].exists():
        outline.init(proj)
    return outline.check(proj)


def stage_script(proj):
    p = L.paths(proj)
    if not p["narration"].exists():
        narration.init(proj)
    return narration.export(proj)


def stage_scenes(proj):
    return storyboard.build(proj)


def stage_visuals(proj):
    return visuals.run(proj, offline=OPTS["offline"])


def stage_scenegen(proj):
    return scenegen.generate(proj)


def stage_render(proj):
    return finish.render_acts(proj, OPTS["size"], OPTS["workers"])


def stage_join(proj):
    return finish.join(proj)


def stage_review(proj):
    return review.build(proj)


def stage_assets(proj):
    return prepare.run(proj, download_maps=OPTS["download_maps"], offline_flag=OPTS["offline"])


class Fingerprint(str):
    """A stage input hash computed by the stage's own tool (instead of hashing a file list)."""


def hash_of(files):
    return str(files) if isinstance(files, Fingerprint) else L.hash_files(files)


def stage_voice(proj):
    """One segment per line from the project's voice.json. Free voices run; a paid one only with
    run --confirm-cost under the cap (and, for Hindi, after the native-speaker review)."""
    p = voice.vp(proj)
    if not p["voice_json"].exists():
        voice.init(proj)                            # the free espeak scratch voice for this language
    r = voice.synth(proj, max_cost=OPTS["max_cost"], confirm=OPTS["confirm_cost"])
    if any("--confirm-cost" in e for e in r.errors):
        r.note("from docpipe: run again with --confirm-cost (and --max-cost) to allow the paid voice")
    return r


def stage_narration(proj):
    return narrate.build(proj, retime=True)


def stage_effects(proj):
    return effects.build(proj)


def stage_sound(proj):
    r = cuesheet.init(proj)
    r.extend(cuesheet.mix(proj))
    return r


def stage_subtitles(proj):
    return subtitles.build(proj)


def audio_inputs(proj, stage):
    """The files each phase 3 stage reads (and the ones it writes, so an edit is noticed)."""
    vp = voice.vp(proj)
    a = vp["proj"] / "audio"
    lines = sorted(vp["segments"].glob("L*.wav")) + sorted(vp["manual"].glob("L*.wav"))
    if stage == "voice":
        return [vp["script_json"], vp["voice_json"], vp["review"], vp["lexicon"], vp["manifest"]] + lines
    if stage == "narration":
        return [vp["script_json"], vp["manifest"], a / "timing.json", a / "narration.m4a"] + lines
    if stage == "effects":
        ep_ = effects.ep(proj)
        scenes = sorted(vp["film_dir"].glob("act_*/scene.py")) + [vp["proj"] / "scene.py"]
        here = pathlib.Path(__file__).resolve().parent
        return Fingerprint(effects.fingerprint(proj) + L.hash_files([a / "sfx.wav", ep_["report"]] + scenes))
    if stage == "sound":
        lib = audiolib.lib_paths(proj)["json"]
        return [a / "cues.json", a / "timing.json", a / "narration.m4a", lib, a / "sfx.wav", a / "mix.m4a", a / "mix_report.json"]
    sp = subtitles.sp(proj)
    return [a / "timing.json", sp["subs"], sp["srt"], sp["vtt"]]


AUDIO = [("voice", stage_voice), ("narration", stage_narration), ("effects", stage_effects), ("sound", stage_sound),
         ("subtitles", stage_subtitles)]


def _inputs(p, *keys):
    d = p["visuals_dir"]
    extra = {"image_needs": p["image_needs"], "selection": d / "selection.json", "assets": d / "assets.json"}
    return [p[k] if k in p else extra[k] for k in keys]


def stage_hash(p, keys):
    """The input hash of a single-language stage. The image needs count by the images they ask
    for, not the storyboard's timing note in the same file, so a new voice (which re-times the
    storyboard) never reopens the approved visuals."""
    files = _inputs(p, *keys)
    if "image_needs" not in keys:
        return L.hash_files(files)
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        if f == p["image_needs"] and f.exists():
            d = L.load(f)
            h.update(json.dumps({k: v for k, v in d.items() if k not in ("timing", "duration")}, sort_keys=True,
                                ensure_ascii=False).encode())
        else:
            h.update(f.read_bytes() if f.exists() else b"<missing>")
    return h.hexdigest()[:16]


def migrate_hash(st, p, keys, h):
    """A stage recorded before stage_hash existed (by its file bytes) keeps its status and approval."""
    if st and st.get("inputs") != h and "image_needs" in keys and st.get("inputs") == L.hash_files(_inputs(p, *keys)):
        if st.get("approved") == st["inputs"]:
            st["approved"] = h
        st["inputs"] = h


STAGES = [
    ("topic", stage_topic, ("topic",), False),
    ("research", stage_research, ("sources", "claims"), False),
    ("outline", stage_outline, ("topic", "outline", "claims", "sources"), True),
    ("script", stage_script, ("narration", "outline", "claims", "sources"), True),
    ("scenes", stage_scenes, ("narration", "timing"), False),
    ("visuals", stage_visuals, ("image_needs", "selection", "topic"), True),
    ("assets", stage_assets, ("prepared:",), False),
    ("scenegen", stage_scenegen, ("storyboard", "assets", "outline"), False),
] + [(name, fn, ("audio:" + name,), False) for name, fn in AUDIO] + [("review", stage_review, ("review:",), "look"),
                                                                        ("render", stage_render, ("render:",), False),
                                                                        ("join", stage_join, ("join:",), False)]
NAMES = [s[0] for s in STAGES]


def single_hash(proj, p, keys):
    if keys and keys[0] == "prepared:":
        return prepare.fingerprint(proj)
    if keys and keys[0] == "review:":
        return review.fingerprint(proj)
    if keys and keys[0] == "render:":
        return finish.render_fingerprint(proj, OPTS["size"])
    if keys and keys[0] == "join:":
        return finish.join_fingerprint(proj)
    if keys and keys[0].startswith("audio:"):
        return hash_of(audio_inputs(proj, keys[0][6:]))
    return stage_hash(p, keys)


def load_state(proj):
    return L.load(L.paths(proj)["state"], {"version": 1, "stages": {}})


def new(folder, topic, minutes, angle="", audience="", look="wall", working_title="", langs=None):
    proj = pathlib.Path(folder)
    if proj.exists() and any(proj.iterdir()):
        raise SystemExit(f"{proj} exists and is not empty")
    L.length_plan(minutes)                       # validates the length
    p = L.paths(proj)
    for k in L.STAGE_DIRS:
        p[k + "_dir"].mkdir(parents=True, exist_ok=True)
    for sub in ("assets/photos", "assets/prep", "audio/takes", "out", "reports"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    L.save(p["topic"], {"topic": topic, "working_title": working_title, "angle": angle, "audience": audience,
                        "minutes": minutes, "look": look, "language": "en", "created": L.today()})
    L.save(p["sources"], {"sources": []})
    L.save(p["claims"], {"claims": []})
    L.save(p["state"], {"version": 1, "created": L.today(), "stages": {}})
    for code in langs or []:
        editions.add(proj, code)
    print(f"created {proj}: {minutes:g} minute documentary on {topic!r}" +
          (f", editions {', '.join(langs)} (default {langs[0]})" if langs else ""))
    print("next: research the topic into 01_research (research.py add-source / add-claim), then docpipe.py run")
    return proj


EDITION_ORDER = ["topic", "research", "outline", "script", "beats", "scenes", "visuals", "assets", "scenegen",
                 "voice", "narration", "effects", "sound", "subtitles", "review", "render", "join"]


def edition_steps(root, langs):
    """The stages of a production with editions, in order: (key, stage name, run, input files, gate)."""
    root = pathlib.Path(root)
    src = editions.default_edition(root)
    E = lambda c: editions.edition_dir(root, c)              # noqa: E731
    P = L.paths(root)
    shared = {s[0]: s for s in STAGES}
    steps = []
    for name in ("topic", "research", "outline"):
        _, fn, keys, gate = shared[name]
        steps.append((name, name, (lambda fn=fn: fn(root)), (lambda keys=keys: _inputs(P, *keys)), gate))

    def script(code):
        def go():
            ed = E(code)
            r = L.Result()
            editions.check(root, code, r)
            if not r.ok:
                return r
            if not L.paths(ed)["narration"].exists():
                narration.init(ed)
            r.extend(narration.export(ed))
            if code != src and r.ok:
                beats.check(root, code, r)
            return r
        return go

    def script_inputs(code):
        ep = L.paths(E(code))
        return [E(code) / "edition.json", ep["lexicon"], ep["narration"], P["outline"], P["claims"], P["sources"]] + \
               ([P["beats"]] if code != src else [])

    order = [src] + [c for c in langs if c != src] if src in langs else [src] + list(langs)
    steps.append((f"script@{src}", "script", script(src), lambda: script_inputs(src), True))
    steps.append(("beats", "beats", lambda: beats.build(root, src), lambda: [L.paths(E(src))["narration"], P["beats"]], False))
    targets = [c for c in order if c in langs] or [src]
    for code in targets:
        if code != src:
            steps.append((f"script@{code}", "script", script(code), (lambda c=code: script_inputs(c)), True))
        steps.append((f"scenes@{code}", "scenes", (lambda c=code: storyboard.build(E(c))),
                      (lambda c=code: [L.paths(E(c))["narration"], L.paths(E(c))["timing"], P["image_needs"]]), False))
    steps.append(("visuals", "visuals", lambda: visuals.run(root, offline=OPTS["offline"]),
                  lambda: _inputs(P, "image_needs", "selection", "topic"), True))
    steps.append(("assets", "assets", lambda: stage_assets(root), lambda: Fingerprint(prepare.fingerprint(root)), False))
    for code in targets:
        def gen(c=code):
            editions.link_shared(root, E(c))                  # photos.json and footage.json exist by now
            return scenegen.generate(E(c))
        steps.append((f"scenegen@{code}", "scenegen", gen,
                      (lambda c=code: [L.paths(E(c))["storyboard"], P["visuals_dir"] / "assets.json", P["outline"], P["beats"]]), False))
    for code in targets:                                     # phase 3: each edition's voice, timing, mix and subtitles
        for name, fn in AUDIO:
            steps.append((f"{name}@{code}", name, (lambda c=code, fn=fn: fn(E(c))),
                          (lambda c=code, n=name: audio_inputs(E(c), n)), False))
    for code in targets:                                     # phase 4: the look of each edition, approved per edition
        steps.append((f"review@{code}", "review", (lambda c=code: stage_review(E(c))),
                      (lambda c=code: Fingerprint(review.fingerprint(E(c)))), "look"))
    for code in targets:                                     # phase 5: finishing, once the look is approved
        steps.append((f"render@{code}", "render", (lambda c=code: stage_render(E(c))),
                      (lambda c=code: Fingerprint(finish.render_fingerprint(E(c), OPTS["size"]))), False))
        steps.append((f"join@{code}", "join", (lambda c=code: stage_join(E(c))),
                      (lambda c=code: Fingerprint(finish.join_fingerprint(E(c)))), False))
    return steps


def run_steps(proj, steps, until=None, only=None, force=False):
    p = L.paths(proj)
    state = load_state(proj)
    stop_at = EDITION_ORDER.index(until) if until else len(EDITION_ORDER)
    ok = True
    for key, name, fn, files, gate in steps:
        if EDITION_ORDER.index(name) > stop_at or (only and name != only):
            continue
        st = state["stages"].setdefault(key, {})
        if name in AFTER_LOOK:
            code = key.split("@")[1]
            if state["stages"].get(f"review@{code}", {}).get("status") != "done":
                st["status"] = "waiting for the look"; ok = False
                print(f"[{key}] waits for the look of the {code} edition: docpipe.py approve --project {proj} look --lang {code}")
                continue
        h = hash_of(files())
        if not force and st.get("status") == "done" and st.get("inputs") == h:
            print(f"[{key}] up to date"); continue
        r = fn()
        h = hash_of(files())
        st.update(inputs=h, at=datetime.datetime.now().isoformat(timespec="seconds"),
                  errors=r.errors, warnings=r.warnings, notes=r.notes)
        print(r.report(f"[{key}]"))
        if not r.ok:
            st["status"] = "blocked"; ok = False
            print(f"[{key}] blocked: fix the errors above, then run again")
            break
        if gate and st.get("approved") != h:
            st["status"] = "awaiting approval"; ok = False
            lang_arg = f" --lang {key.split('@')[1]}" if "@" in key else ""
            what = "look" if gate == "look" else name
            print(f"[{key}] passes its checks; review it, then: docpipe.py approve --project {proj} {what}{lang_arg}")
            if gate == "look":
                continue                                     # nothing waits on the look: the other editions go on
            break
        st["status"] = "partial" if getattr(r, "partial", False) else "done"
        if st["status"] == "partial":
            print(f"[{key}] partial: some work is deferred; the next run retries it")
    L.save(p["state"], state)
    return ok


def langs_for(root, lang):
    eds = editions.editions_of(root)
    if lang in (None, ""):
        return [editions.default_edition(root)]
    if lang == "all":
        return eds
    if lang not in eds:
        raise SystemExit(f"this production has editions {eds}; add {lang!r} with editions.py add")
    return [lang]


def run(proj, until=None, only=None, force=False, lang=None):
    p = L.paths(proj)
    if not p["state"].exists():
        raise SystemExit(f"{proj} is not a docpipe project (no docpipe.json); start one with docpipe.py new")
    if editions.editions_of(proj):
        return run_steps(proj, edition_steps(proj, langs_for(proj, lang)), until, only, force)
    if lang not in (None, "", "en"):
        raise SystemExit(f"{proj} is a single-language (English) project; add editions with editions.py add")
    if (until and until not in NAMES) or (only and only not in NAMES):
        raise SystemExit(f"the beats stage exists only in a production with editions (editions.py add)")
    state = load_state(proj)
    stop_at = NAMES.index(until) if until else len(NAMES) - 1
    ok = True
    for idx, (name, fn, keys, gate) in enumerate(STAGES):
        if idx > stop_at:
            break
        if only and name != only:
            continue
        st = state["stages"].setdefault(name, {})
        if name in AFTER_LOOK and state["stages"].get("review", {}).get("status") != "done":
            st["status"] = "waiting for the look"; ok = False
            print(f"[{name}] waits for the look: docpipe.py approve --project {proj} look")
            continue
        h = single_hash(proj, p, keys)
        migrate_hash(st, p, keys, h)
        if not force and st.get("status") in ("done", "awaiting approval") and st.get("inputs") == h:   # "partial" always reruns
            if st["status"] == "done":
                print(f"[{name}] up to date"); continue
        r = fn(proj)
        h = single_hash(proj, p, keys)                # stages may scaffold their own inputs
        st.update(inputs=h, at=datetime.datetime.now().isoformat(timespec="seconds"),
                  errors=r.errors, warnings=r.warnings, notes=r.notes)
        print(r.report(f"[{name}]"))
        if not r.ok:
            st["status"] = "blocked"; ok = False
            print(f"[{name}] blocked: fix the errors above, then run again")
            break
        if gate and st.get("approved") != h:
            st["status"] = "awaiting approval"; ok = False
            what = "look" if gate == "look" else name
            print(f"[{name}] passes its checks; review it, then: docpipe.py approve --project {proj} {what}")
            if gate == "look":
                continue
            break
        st["status"] = "partial" if getattr(r, "partial", False) else "done"
        if st["status"] == "partial":
            print(f"[{name}] partial: some work is deferred; the next run retries it")
    L.save(p["state"], state)
    return ok


def approve(proj, name, lang=None):
    p = L.paths(proj)
    state = load_state(proj)
    if name == "look":
        name = "review"
    if editions.editions_of(proj):
        code = lang or editions.default_edition(proj)
        key = f"{name}@{code}" if name in ("script", "review") else name
        steps = {k: f for k, _, _, f, _ in edition_steps(proj, editions.editions_of(proj))}
        if key not in steps:
            raise SystemExit(f"no stage {key}")
        st = state["stages"].get(key)
        h = hash_of(steps[key]())
        if not st or st.get("status") not in ("awaiting approval", "done", "partial") or st.get("inputs") != h:
            raise SystemExit(f"{key} has not passed its checks on its current files; run docpipe.py run first")
        st["approved"] = h
        st["approved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        if st["status"] == "awaiting approval":
            st["status"] = "done"
        L.save(p["state"], state)
        print(f"[{key}] approved")
        return
    st = state["stages"].get(name)
    keys = dict((s[0], s[2]) for s in STAGES)[name]
    h = single_hash(proj, p, keys)
    migrate_hash(st, p, keys, h)
    if not st or st.get("status") not in ("awaiting approval", "done", "partial") or st.get("inputs") != h:
        raise SystemExit(f"{name} has not passed its checks on its current files; run docpipe.py run first")
    st["approved"] = h
    st["approved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if st["status"] == "awaiting approval":
        st["status"] = "done"
    L.save(p["state"], state)
    print(f"[{name}] approved")


def status(proj):
    p = L.paths(proj)
    state = load_state(proj)
    t = L.load(p["topic"], {})
    print(f"{t.get('topic', '?')}  ({t.get('minutes', '?')} min)")
    if editions.editions_of(proj):
        print(f"  editions: {', '.join(editions.editions_of(proj))} (default {editions.default_edition(proj)})")
        for key, name, _, files, gate in edition_steps(proj, editions.editions_of(proj)):
            st = state["stages"].get(key, {})
            s = st.get("status", "not run")
            if s == "done" and st.get("inputs") != hash_of(files()):
                s = "out of date"
            extra = f"  {len(st.get('errors', []))} errors, {len(st.get('warnings', []))} warnings" if st else ""
            print(f"  {key:<14} {s:<18}{' [gate]' if gate else '       '}{extra}")
        return
    for name, _, keys, gate in STAGES:
        st = state["stages"].get(name, {})
        s = st.get("status", "not run")
        h = single_hash(proj, p, keys)
        migrate_hash(st, p, keys, h)
        if s == "done" and st.get("inputs") != h:
            s = "out of date"
        extra = f"  {len(st.get('errors', []))} errors, {len(st.get('warnings', []))} warnings" if st else ""
        print(f"  {name:<9} {s:<18}{' [gate]' if gate else '       '}{extra}")
    for name, what in PLANNED:
        print(f"  {name:<9} {'planned':<18}         {what}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("folder"); n.add_argument("--topic", required=True); n.add_argument("--minutes", type=float, default=5)
    n.add_argument("--angle", default=""); n.add_argument("--audience", default=""); n.add_argument("--title", default="")
    n.add_argument("--look", default="wall", choices=LOOKS)
    n.add_argument("--editions", default="", help="language editions, the first is the default: en,hi")
    r = sub.add_parser("run")
    r.add_argument("--project", required=True); r.add_argument("--until", choices=EDITION_ORDER)
    r.add_argument("--only", choices=EDITION_ORDER); r.add_argument("--force", action="store_true")
    r.add_argument("--offline", action="store_true", help="no network: archive searches come from the cache only")
    r.add_argument("--lang", default=None, help="edition to run (default: the default edition), or all")
    r.add_argument("--confirm-cost", action="store_true", help="allow a paid voice to spend, under --max-cost")
    r.add_argument("--max-cost", type=float, default=voice.DEFAULT_CAP, help="USD cap for this run's paid voice (default 5)")
    r.add_argument("--size", default=finish.SIZE, help="render size, e.g. 1920x1080 (default) or 1280x720")
    r.add_argument("--workers", type=int, default=0, help="render workers (0: as many as fit in memory)")
    r.add_argument("--download-maps", action="store_true", help="assets: download map boundary data not cached yet (public domain)")
    s = sub.add_parser("status"); s.add_argument("--project", required=True)
    a = sub.add_parser("approve"); a.add_argument("--project", required=True)
    a.add_argument("stage", choices=[x[0] for x in STAGES if x[3] is True] + ["look"])
    a.add_argument("--lang", default=None, help="the edition, for a script or look approval")
    args = ap.parse_args()
    if args.cmd == "new":
        langs = [x.strip() for x in args.editions.split(",") if x.strip()]
        new(args.folder, args.topic, args.minutes, args.angle, args.audience, args.look, args.title, langs)
    elif args.cmd == "run":
        OPTS["offline"] = args.offline
        OPTS["confirm_cost"], OPTS["max_cost"] = args.confirm_cost, args.max_cost
        OPTS["download_maps"] = args.download_maps
        OPTS["size"], OPTS["workers"] = args.size, args.workers
        sys.exit(0 if run(args.project, args.until, args.only, args.force, args.lang) else 1)
    elif args.cmd == "status":
        status(args.project)
    else:
        approve(args.project, args.stage, args.lang)


if __name__ == "__main__":
    main()
