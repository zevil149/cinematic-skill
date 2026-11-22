# Render, join, captions, QC and report — Hindi edition (2026-11-22)

`docpipe.py run --project <absolute path>/productions/molasses-flood --lang hi --size 1920x1080 --workers 3`,
after the producer's render authorisation. All stages passed; exit 0.

| Stage | Result |
|---|---|
| render@hi | act 1: 10,680 frames, 356.00 s at 1920×1080 (single act, delivery quality); Hindi credits `out/credits.hi.mp4`: 24.0 s, 16 lines |
| join@hi | `out/film.hi.mp4`: 380.02 s (356.02 s film + 24.00 s credits), 11,400 frames, 1920×1080, 30 fps, H.264 + AAC 48 kHz stereo, 1.09 GB (~22.9 Mbit/s) |
| captions@hi | `out/film.hi.captions.mp4`: clean style burned in, 380.00 s, 11,400 frames, 0.93 GB |
| qc@hi | **complete: 0 errors, 2 warnings, 0 checks not made** (`out/qc.hi.md`, `out/qc.hi.json`, `out/delivery.hi.json`) |
| report | `reports/final_report.md` complete, `reports/credits.md`, `reports/report.json`, `out/credits.hi.md` |

## QC warnings (not fixed: warnings, not failures)

1. **fonts:** the condensed type role fell back to the system default (Inter); Devanagari uses the
   bundled Noto Sans Devanagari as designed. Pinning a condensed Latin font needs a download.
2. **caption clearance, 349.5–352.0 s:** during the closing pull-back the last two captions sit over
   the bottom row of the (very small) board items. Captions stay legible. Cause: the motion-check
   change let the final frame use the bottom caption margin, but the last caption runs until
   353.0 s. Fix if wanted: keep the bottom margin until the last caption ends (scene change + re-render).

## Measurements (QC, on the finished film)

Loudness −15.0 LUFS (target −15.0); true peak −1.2 dBTP in the film (mix −1.5 dBTP; within the
pipeline's tolerance after the final AAC encode); narration found under every line, lowest
12.5 dB over music and effects, aligned at +5 ms; no stray black frames, silences or empty frames;
74 SRT and 74 VTT cues parsed, every cue on its line; text fit ok; rights ok (12 assets).

## A pipeline bug found and avoided (not fixed)

With a **relative** `--project`, `finish.py` passes the act's output and chunk paths already prefixed
with the project path, and `render.py` resolves them relative to the project again: chunks went to
`editions/hi/productions/molasses-flood/editions/hi/out/acts/…` and the act would have been written
there too. The first run was stopped after ~2 minutes, its 44 KB of misplaced chunks removed, and
the pipeline re-run with an **absolute** project path (the tests and the pilot always use absolute
paths). The code is unchanged; the fix belongs in its own PR.

## Files (not in git: generated video, rebuilt by these stages)

`editions/hi/out/film.hi.mp4`, `film.hi.captions.mp4`, `credits.hi.mp4`, `acts/act_01.mp4`,
`burn/` (caption working segments, 884 MB, can be deleted).

## Tests

test_qc, test_qc_smarter, test_report, test_rights, test_subtitles, test_burned_captions, test_gates: all OK.
