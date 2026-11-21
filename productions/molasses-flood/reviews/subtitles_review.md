# Subtitles stage — Hindi edition

`docpipe.py run --until subtitles`, 2026-11-21: **0 errors, 0 warnings**; a rerun reports it up to date.

* **Files:** `out/subtitles.hi.srt`, `out/subtitles.hi.vtt` (identical cues), `audio/subs.json`
  (settings, per-cue timing source, file hashes).
* **74 cues** from the 55 approved lines (cut at sentence ends, then commas, then by length;
  never across two narration lines). Text is the script's displayed text, digits as written.

## Checks (run against the approved script and `audio/timing.json`)

| Check | Result |
|---|---|
| Cue text, joined in order, equals the approved script text | yes |
| SRT and VTT identical (times and text) | yes |
| Overlaps | none; minimum gap 0.080 s (the setting) |
| Lines per cue / characters per line | at most 2 / at most 42 (the limits) |
| Cue duration | 1.15–7.03 s (limit 7.0 s; one cue 0.03 s over by rounding to word times) |
| Reading speed | median 11.4, max 13.4 characters/s (cue 37); limit 17 |
| Span | 0.900–352.992 s; narration 0.900–353.016 s |
| Script | Devanagari only (digits as in the script) |
| Timing source | **estimate** for all 74 cues (espeak gives no word times) |

## For review

* **Cue boundaries inside a line rest on estimated word times**; a cue can change slightly early or
  late against the voice. Line starts and ends are measured.
* **The name "डब्ल्यू. एल. वेजर" is split across cues 51 and 52** ("… रसायनज्ञ डब्ल्यू." / "एल. वेजर
  …"): the splitter treats the initial's full stop as a sentence end. The text is complete and in
  order; reads awkwardly. Fixable later by editing the two cues (the stage keeps edited subtitle
  files) — not done here, to leave the stage's output as generated.
* Subtitles follow the scratch voice; a new voice means new subtitles.

## Tests

test_subtitles, test_pipeline_audio, test_editions, test_lang_hi: all OK.
Approved script, storyboard, scene starter, timing, cue sheet, mix report, visuals and credits unchanged.
