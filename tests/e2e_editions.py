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
    dp("run", "--project", proj, "--lang", "all", "--offline")                 # scenes, voices, timing, mixes, subtitles
    r = dp("run", "--project", proj, "--lang", "all", "--offline")             # the run after a new voice re-checks scenes
    r = dp("run", "--project", proj, "--lang", "all", "--offline")
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
    chk = subprocess.run([sys.executable, str(SCRIPTS / "editions.py"), "check", "--project", str(proj)], capture_output=True, text=True)
    print(chk.stdout)
    if chk.returncode != 0:
        sys.exit("editions check failed")
    (out / "outputs" / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
