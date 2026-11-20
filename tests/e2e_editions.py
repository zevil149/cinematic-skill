"""End to end, offline: a two-edition documentary (English and Hindi) through every docpipe stage
with the real free espeak-ng voices, then checks the outputs. Run by the CI film job:

  python tests/e2e_editions.py OUT_DIR

The research, outline and scripts are the test fixtures (the agent writes them in real use); the
gates are approved here as a person would. No network (CINEMATIC_OFFLINE=1, --offline), no paid voice.
"""
import json
import os
import pathlib
import subprocess
import sys

os.environ["CINEMATIC_OFFLINE"] = "1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path[:0] = [str(SCRIPTS), str(ROOT / "tests")]

from test_editions import production, write_english, write_hindi  # noqa: E402


def dp(*args, ok=True):
    r = subprocess.run([sys.executable, str(SCRIPTS / "docpipe.py"), *map(str, args)], capture_output=True, text=True)
    print(r.stdout[-3000:])
    if ok and r.returncode != 0:
        sys.exit(f"docpipe {' '.join(map(str, args))} failed:\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")
    return r


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    proj = production(out)
    dp("run", "--project", proj, "--offline", ok=False); dp("approve", "--project", proj, "outline")
    write_english(proj)
    dp("run", "--project", proj, "--offline", ok=False); dp("approve", "--project", proj, "script", "--lang", "en")
    dp("run", "--project", proj, "--lang", "hi", "--offline", ok=False)
    write_hindi(proj)
    dp("run", "--project", proj, "--lang", "hi", "--offline", ok=False); dp("approve", "--project", proj, "script", "--lang", "hi")
    dp("run", "--project", proj, "--lang", "all", "--offline", ok=False); dp("approve", "--project", proj, "visuals")
    small = ("--size", "256x144", "--workers", "2")                           # the film at a size CI can render
    r = dp("run", "--project", proj, "--lang", "all", "--offline", *small, ok=False)   # assets ... reviews
    for code in ("en", "hi"):
        if f"[review@{code}] passes its checks" not in r.stdout:
            sys.exit(f"review@{code} did not reach the look gate:\n{r.stdout[-3000:]}")
    r = dp("run", "--project", proj, "--lang", "all", "--offline", *small, ok=False)   # the run after a new voice re-checks scenes
    for code in ("en", "hi"):                                                  # a person looks at 07_review/<lang>/ here
        dp("approve", "--project", proj, "look", "--lang", code)
    dp("run", "--project", proj, "--lang", "all", "--offline", *small)        # the finishing stages
    r = dp("run", "--project", proj, "--lang", "all", "--offline", *small)
    stale = [ln for ln in r.stdout.splitlines() if ln.startswith("[") and "up to date" not in ln]
    if stale:
        sys.exit(f"the third run should change nothing: {stale}")
    report = {}
    for code in ("en", "hi"):
        ed = proj / "editions" / code
        t = json.loads((ed / "audio" / "timing.json").read_text())
        m = json.loads((ed / "audio" / "mix_report.json").read_text())
        s = json.loads((ed / "audio" / "subs.json").read_text())
        assert t["lang"] == m["lang"] == s["lang"] == code, code
        assert abs(m["lufs"] + 15.0) <= 1.0 and m["clipped_samples"] == 0 and m["true_peak_dbtp"] <= -1.0, m
        for f in ("audio/narration.m4a", "audio/mix.m4a", f"out/subtitles.{code}.srt", f"out/subtitles.{code}.vtt"):
            assert (ed / f).stat().st_size > 0, f
        report[code] = {"lines": len(t["segments"]), "duration": t["total_duration"], "lufs": m["lufs"],
                        "true_peak_dbtp": m["true_peak_dbtp"], "voice_over_music_db": m["voice_over_music_db"],
                        "cues": len(s["cues"]), "timing": s["timing_counts"]}
        for f in ("audio/mix.m4a", f"out/subtitles.{code}.srt", f"out/subtitles.{code}.vtt", "audio/mix_report.json"):
            dst = out / "outputs" / code / pathlib.Path(f).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((ed / f).read_bytes())
        rv = json.loads((proj / "07_review" / code / "review.json").read_text())
        assert rv["lang"] == code and rv["acts"], rv
        report[code]["review"] = {"acts": len(rv["acts"]), "stills": sum(len(a["probes"]) for a in rv["acts"]),
                                  "strips": sum(len(a["strips"]) for a in rv["acts"]),
                                  "flagged": [x["name"] for a in rv["acts"] for x in a["probes"] + a["strips"] if x["flags"]]}
        import shutil
        shutil.copytree(proj / "07_review" / code, out / "outputs" / code / "review", dirs_exist_ok=True)
        fin = json.loads((ed / "out" / "finish.json").read_text())
        assert fin["lang"] == code and fin["acts"], fin
        report[code]["render"] = {str(k): {"frames": v["frames"], "from": v["from"], "to": v["to"]} for k, v in fin["acts"].items()}
        report[code]["film"] = {k: fin["join"][k] for k in ("duration", "frames", "size", "order")}
        report[code]["captions"] = {k: fin["captions"][k] for k in ("style", "frames", "duration")}
        for f in (f"film.{code}.mp4", f"film.{code}.captions.mp4"):
            (out / "outputs" / code / f).write_bytes((ed / "out" / f).read_bytes())
        assert abs(fin["join"]["duration"] - t["total_duration"]) < 0.1, fin["join"]
        q = json.loads((ed / "out" / f"qc.{code}.json").read_text())
        dl = json.loads((ed / "out" / f"delivery.{code}.json").read_text())
        assert q["lang"] == dl["lang"] == code and q["complete"] and dl["complete"] and not q["errors"], q["errors"]
        report[code]["qc"] = {"complete": q["complete"], "checks": len(q["checks"]), "warnings": q["warnings"],
                              "delivered": sorted({f["kind"] for f in dl["files"]})}
        for f in (f"qc.{code}.md", f"delivery.{code}.json"):
            (out / "outputs" / code / f).write_bytes((ed / "out" / f).read_bytes())
    chk = subprocess.run([sys.executable, str(SCRIPTS / "editions.py"), "check", "--project", str(proj)], capture_output=True, text=True)
    print(chk.stdout)
    if chk.returncode != 0:
        sys.exit("editions check failed")
    (out / "outputs" / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
