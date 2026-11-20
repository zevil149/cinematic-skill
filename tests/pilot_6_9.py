"""Phase 6.9 pilot driver (docs/pilot-6.9.md) (offline, controlled): a two-edition, two-act production through every
docpipe stage and gate at 1080p, with the repository's own example images as "own" visuals.

  python3 pilot.py OUT [step]     steps: build (to the look gate), finish (after the looks are approved)

Gates are passed only with docpipe.py approve, after the outputs they cover were looked at.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

os.environ["CINEMATIC_OFFLINE"] = "1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path[:0] = [str(SCRIPTS), str(ROOT / "tests")]

import doclib as L  # noqa: E402
from test_editions import production, write_english, write_hindi  # noqa: E402

OUT = pathlib.Path(sys.argv[1])
STEP = sys.argv[2] if len(sys.argv) > 2 else "build"
LOG = OUT / "pilot.log"
TIMES = OUT / "times.json"
OWN = {"film-wall.webp": "The evidence-wall look (repository example frame)",
       "film-cold-open.webp": "The cold-open look (repository example frame)",
       "film-explainer.webp": "The explainer look (repository example frame)"}


def dp(*args, ok=True, tag=None):
    t0 = time.time()
    r = subprocess.run([sys.executable, str(SCRIPTS / "docpipe.py"), *map(str, args)], capture_output=True, text=True)
    dt = time.time() - t0
    with open(LOG, "a") as f:
        f.write(f"\n$ docpipe {' '.join(map(str, args))}   ({dt:.0f}s, exit {r.returncode})\n{r.stdout}\n{r.stderr[-2000:]}\n")
    if tag:
        t = json.loads(TIMES.read_text()) if TIMES.exists() else {}
        t[tag] = round(dt, 1); TIMES.write_text(json.dumps(t, indent=1))
    if ok and r.returncode != 0:
        sys.exit(f"docpipe {' '.join(map(str, args))} failed:\n{r.stdout[-3000:]}\n{r.stderr[-1500:]}")
    return r


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    proj = production(OUT)
    dp("run", "--project", proj, "--offline", ok=False)
    # the author splits the film into two acts: the later chapters, the turn and the close are act 2
    o = L.load(L.paths(proj)["outline"])
    chapters = [s for s in o["sections"] if s["kind"] == "chapter"]
    for s in o["sections"]:
        s["act"] = 2 if (s["kind"] in ("turn", "close") or (s["kind"] == "chapter" and chapters.index(s) >= len(chapters) // 2)) else 1
    o["acts"] = 2
    o["act_titles"] = {"2": "Twelve seconds in the air"}
    L.save(L.paths(proj)["outline"], o)
    dp("run", "--project", proj, "--offline", ok=False)
    dp("approve", "--project", proj, "outline")
    en, n = write_english(proj)
    # three lines show the repository's own example frames instead of a designed card
    photos = proj / "assets" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    files = list(OWN)
    k = 0
    for sec in n["sections"]:
        for ln in sec["lines"]:
            if ln.get("images") and k < len(files):
                f = files[k]
                shutil.copyfile(ROOT / "examples" / f, photos / f)
                ln["images"] = [{"what": OWN[f], "kind": "own", "file": f, "license": "MIT (cinematic-skill repository)",
                                 "credit": "cinematic-skill examples"}]
                k += 1
    L.save(L.paths(en)["narration"], n)
    dp("run", "--project", proj, "--offline", ok=False)
    dp("approve", "--project", proj, "script", "--lang", "en")
    dp("run", "--project", proj, "--lang", "hi", "--offline", ok=False)
    hi = write_hindi(proj)
    hn = L.load(L.paths(hi)["narration"]); hn["act_titles"] = {"2": "हवा में बारह सेकंड"}; L.save(L.paths(hi)["narration"], hn)
    dp("run", "--project", proj, "--lang", "hi", "--offline", ok=False)
    dp("approve", "--project", proj, "script", "--lang", "hi")
    dp("run", "--project", proj, "--lang", "all", "--offline", ok=False)
    dp("approve", "--project", proj, "visuals")
    full = ("--size", "1920x1080", "--workers", "3")
    dp("run", "--project", proj, "--lang", "all", "--offline", *full, ok=False, tag="to_look_1")
    dp("run", "--project", proj, "--lang", "all", "--offline", *full, ok=False, tag="to_look_2")
    # the gate holds: no render before the look is approved, even with --only
    r = dp("run", "--project", proj, "--lang", "en", "--only", "render", "--offline", *full, ok=False)
    assert "waits for the look" in r.stdout and not (proj / "editions" / "en" / "out" / "acts").exists(), r.stdout[-1500:]
    print(f"built {proj}; look at 07_review/<lang>/act_NN/sheet.jpg, then: pilot.py {OUT} finish")


def finish():
    proj = OUT / "doc"
    for code in ("en", "hi"):
        dp("approve", "--project", proj, "look", "--lang", code)
    full = ("--size", "1920x1080", "--workers", "3")
    r = dp("run", "--project", proj, "--lang", "all", "--offline", *full, ok=False, tag="finish")
    print(r.stdout[-2500:])
    r = dp("run", "--project", proj, "--lang", "all", "--offline", *full, ok=False, tag="rerun")
    stale = [ln for ln in r.stdout.splitlines() if ln.startswith("[") and "up to date" not in ln]
    print("rerun, not up to date:", stale)


if __name__ == "__main__":
    build() if STEP == "build" else finish()
