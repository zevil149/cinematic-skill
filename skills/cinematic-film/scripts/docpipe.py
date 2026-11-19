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

Stages (phase 2):
  visuals   05_visuals: archive search, licences, downloads, fallbacks  [gate]  (visuals.py)
  scenegen  06_film: an editable scene.py starter per act               (scenegen.py)

visuals talks to the archives (politely: paced, cached, and silent towards any archive that is
rate-limiting us). --offline uses cached searches only. Downloads deferred by a rate limit leave
the stage "partial": the film goes on with designed cards, and the next run retries them.

The research, outline and narration are written by the agent (or a person) into the stage files;
the pipeline scaffolds them, checks them and refuses to move on while a check fails. A stage
marked [gate] waits for `approve` before the next stage runs, and an approval lapses when the
stage's inputs change. Planned stages (images, voice, sound, render, captions, report) are listed
by status and arrive in later phases; until then the film tools run as SKILL.md describes.
"""
import argparse
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402
import research  # noqa: E402
import scenegen  # noqa: E402
import storyboard  # noqa: E402
import visuals  # noqa: E402

LOOKS = ("wall", "slate", "charcoal", "paper", "studio", "blueprint", "night")
PLANNED = [("voice", "scratch then final voice; timing.json (tts_say, split_takes, build_narration)"),
           ("assets", "maps, graded images and footage frames (make_map, prep_assets, prep_footage)"),
           ("review", "probes and strips of every act for the look test (render.py)"),
           ("sound", "effects, music, ducked mix (build_sfx, mix_soundtrack)"),
           ("render", "1080p render by chapter, memory-aware (render.py)"),
           ("captions", "burned captions and SRT (burn_captions.py)"),
           ("report", "final report, credits.md and QC")]


OPTS = {"offline": False}


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


def _inputs(p, *keys):
    d = p["visuals_dir"]
    extra = {"image_needs": p["image_needs"], "selection": d / "selection.json", "assets": d / "assets.json"}
    return [p[k] if k in p else extra[k] for k in keys]


STAGES = [
    ("topic", stage_topic, ("topic",), False),
    ("research", stage_research, ("sources", "claims"), False),
    ("outline", stage_outline, ("topic", "outline", "claims", "sources"), True),
    ("script", stage_script, ("narration", "outline", "claims", "sources"), True),
    ("scenes", stage_scenes, ("narration", "timing"), False),
    ("visuals", stage_visuals, ("image_needs", "selection", "topic"), True),
    ("scenegen", stage_scenegen, ("storyboard", "assets", "outline"), False),
]
NAMES = [s[0] for s in STAGES]


def load_state(proj):
    return L.load(L.paths(proj)["state"], {"version": 1, "stages": {}})


def new(folder, topic, minutes, angle="", audience="", look="wall", working_title=""):
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
    print(f"created {proj}: {minutes:g} minute documentary on {topic!r}")
    print("next: research the topic into 01_research (research.py add-source / add-claim), then docpipe.py run")
    return proj


def run(proj, until=None, only=None, force=False):
    p = L.paths(proj)
    if not p["state"].exists():
        raise SystemExit(f"{proj} is not a docpipe project (no docpipe.json); start one with docpipe.py new")
    state = load_state(proj)
    stop_at = NAMES.index(until) if until else len(NAMES) - 1
    ok = True
    for idx, (name, fn, keys, gate) in enumerate(STAGES):
        if idx > stop_at:
            break
        if only and name != only:
            continue
        st = state["stages"].setdefault(name, {})
        h = L.hash_files(_inputs(p, *keys))
        if not force and st.get("status") in ("done", "awaiting approval") and st.get("inputs") == h:   # "partial" always reruns
            if st["status"] == "done":
                print(f"[{name}] up to date"); continue
        r = fn(proj)
        h = L.hash_files(_inputs(p, *keys))           # stages may scaffold their own inputs
        st.update(inputs=h, at=datetime.datetime.now().isoformat(timespec="seconds"),
                  errors=r.errors, warnings=r.warnings, notes=r.notes)
        print(r.report(f"[{name}]"))
        if not r.ok:
            st["status"] = "blocked"; ok = False
            print(f"[{name}] blocked: fix the errors above, then run again")
            break
        if gate and st.get("approved") != h:
            st["status"] = "awaiting approval"; ok = False
            print(f"[{name}] passes its checks; review it, then: docpipe.py approve --project {proj} {name}")
            break
        st["status"] = "partial" if getattr(r, "partial", False) else "done"
        if st["status"] == "partial":
            print(f"[{name}] partial: some work is deferred; the next run retries it")
    L.save(p["state"], state)
    return ok


def approve(proj, name):
    p = L.paths(proj)
    state = load_state(proj)
    st = state["stages"].get(name)
    keys = dict((s[0], s[2]) for s in STAGES)[name]
    h = L.hash_files(_inputs(p, *keys))
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
    for name, _, keys, gate in STAGES:
        st = state["stages"].get(name, {})
        s = st.get("status", "not run")
        if s == "done" and st.get("inputs") != L.hash_files(_inputs(p, *keys)):
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
    r = sub.add_parser("run")
    r.add_argument("--project", required=True); r.add_argument("--until", choices=NAMES)
    r.add_argument("--only", choices=NAMES); r.add_argument("--force", action="store_true")
    r.add_argument("--offline", action="store_true", help="no network: archive searches come from the cache only")
    s = sub.add_parser("status"); s.add_argument("--project", required=True)
    a = sub.add_parser("approve"); a.add_argument("--project", required=True); a.add_argument("stage", choices=[x[0] for x in STAGES if x[3]])
    args = ap.parse_args()
    if args.cmd == "new":
        new(args.folder, args.topic, args.minutes, args.angle, args.audience, args.look, args.title)
    elif args.cmd == "run":
        OPTS["offline"] = args.offline
        sys.exit(0 if run(args.project, args.until, args.only, args.force) else 1)
    elif args.cmd == "status":
        status(args.project)
    else:
        approve(args.project, args.stage)


if __name__ == "__main__":
    main()
