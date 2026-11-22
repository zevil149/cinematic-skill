# Phase 8 — Professional release preparation (Hindi, The Great Molasses Flood)

## Release readiness: **NOT READY** (preparation complete; four blockers)

The finished film (`editions/hi/out/film.hi.mp4`, `film.hi.captions.mp4`; 380.02 s, 1920×1080,
QC 0 errors) is a complete, internally consistent production, but it is not releasable as it is:

| # | Blocker | Where |
|---|---|---|
| 1 | Narration is the espeak scratch voice (robotic) | `voice_evaluation.md` |
| 2 | Two images' US public-domain status is provisional (BPL panorama ×3 uses, City Archives railway photo ×1) | `provenance_audit.md` |
| 3 | The credits sequence repeats each image once per use (12 entries for 4 files), in a 24 s roll | `provenance_audit.md` |
| 4 | Last two captions overlap the closing board (QC warning) | `caption_clearance.md` |

Not blocking: the condensed-Latin font fallback (QC warning; Devanagari is correct).

## What was done (no destructive change)

* **Backups:** `editions/hi/out/release_backup/film.hi.mp4` and `film.hi.captions.mp4`, byte copies,
  read-only; `SHA256SUMS` records them and the live films, credits, subtitles, mix, narration and
  timing. All 10 verified unchanged at the end of Phase 8; the scene file's SHA-256 is unchanged
  (1329a6dd…).
* **Task 1, voice:** 55-line audit (`voice_line_audit.json`): 3,557 characters, 16 lines with numbers,
  29 with English names/loanwords, 10 scripted pauses. Machine: 4 CPU, 15 GB RAM, no GPU, onnxruntime
  present, no PyTorch, Hugging Face not reachable. Recommendation: a native Hindi narrator recorded
  per line into `audio/voice/manual/` (supported by the pipeline, no download, no licence doubt);
  fallback Piper (if a Hindi voice with a commercial-use licence exists — to verify); avoid
  non-commercial models (MMS-TTS, XTTS — to verify). Samples plan: lines 1, 8, 24, 37, 41, 46.
  Nothing generated.
* **Task 2, captions:** cause traced to the motion-check change (`9082f27`). Smallest fix: two camera
  lines in the closing (`proposed_closing_fix.diff`, not applied). Measured with QC's own check on a
  temporary copy: collisions 7 → 1 (a 60 % transient during the move); the board in the final frame
  moves from y 7–93 % to 8–80 % (clear of the caption band), drawn 16 % smaller. Narration, caption
  wording and timing, visuals and soundtrack untouched by the proposal.
* **Task 3, provenance:** 12 uses = 4 files. Post page: cleared (published 1919). Map: cleared
  (author's release; labelled reconstruction). Panorama and railway photo: provisional; the exact
  evidence needed is listed (institution record with rights statement, or proof of publication
  before 1931, or written permission). Documented alternatives: the Post's own 1919 photo; the
  Boston Daily Globe 16 Jan 1919 front page on Commons (not yet audited). Found: the credits repeat.
* **Task 4, packaging:** four Hindi titles (with what each rests on), description draft, chapter list
  from the real timing (10 chapters), one-line-per-file credits block, thumbnail concept from a cleared
  image, Hindi disclaimer, 15-item release checklist (`release_package.md`). Nothing published.

## Validation

* Checksums: 10/10 OK (finished films, backups, credits, subtitles, mix, narration, timing).
* Tests (non-destructive): test_voice, test_voice_spend, test_lang_hi, test_rights, test_report,
  test_qc, test_subtitles, test_gates, test_storyboard_direction, test_visuals_credits: all OK.

## Limitations

* Licence facts about TTS models are from general knowledge, marked "to verify"; their pages could
  not be opened here.
* No holding institution's page could be opened; the provisional items cannot be resolved from here.
* The caption fix was measured on geometry, not seen in a render.
* Any release voice changes all timing: chapters, subtitles, effects, mix, look approval and render
  all follow (re-render ~70 min on this machine).

## Recommended next actions (in order)

1. Ask BPL and the City of Boston Archives for the rights evidence (or decide to replace the two
   images with the documented alternatives).
2. Arrange the native Hindi narrator; record the six sample lines first.
3. Authorise the small code fix for the credits (one entry per file) and the closing caption diff.
4. Then one combined re-run: narration → effects → sound → subtitles → look review/approval →
   render → join → captions → QC → report; re-derive chapters; make the thumbnail.

## Files

`release/PHASE8_REPORT.md` (this), `release/voice_evaluation.md`, `release/voice_line_audit.json`,
`release/caption_clearance.md`, `release/proposed_closing_fix.diff`, `release/provenance_audit.md`,
`release/release_package.md`, `editions/hi/out/release_backup/SHA256SUMS` (the backup MP4s
themselves are not in git).
