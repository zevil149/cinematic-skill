# Narration stage — Hindi edition (scratch voice)

`docpipe.py run --until narration`, 2026-11-21: **0 errors, 2 warnings** (both expected):
1. "06_film/act_01/scene.py has your edits; left as it is" — the Phase 7 edits (Hindi card titles,
   map label) are kept; the file is byte-identical to before the stage.
2. "3 of 15 visuals are designed cards" — the placeholders I003, I014, I007, by the producer's choice.

## Result

* `audio/narration.m4a` (356.1 s by ffprobe) and `audio/timing.json` (total 356.016 s; lead-in 0.9 s,
  tail 3.0 s; tempo 1.0, the natural read: no speed-up or slow-down).
* **Duration 5:56.0** (the voice review's 6:21 summed the raw clips; this stage trims the silence
  espeak leaves at both ends of each clip).
* **Pauses:** all 10 scripted pauses placed exactly as approved (after lines 4, 51: 1.6 s; 5, 40: 1.0 s;
  15: 1.2 s; 25, 38, 43: 0.9 s; 32, 54: 2.0 s); every other gap is the pipeline default (0.45 s within
  a section, 1.0 s at a section's end).
* **Word timing: estimated** (`words_from: estimate` on all 55 lines). espeak gives no word times, so
  each line's words are spread over its measured duration by syllable count. Line starts and ends
  are measured; word times inside a line are approximations (expect tens to a few hundred ms off).
* **Landing words:** all 55 found in their line's word timing; the 46 overrides in direction.json
  still apply.

## Re-timing

Only `start`, `end` and `duration` of the 55 storyboard scenes changed, plus the storyboard's
timing note ("voice") and duration, and the act's end time in `06_film/acts.json` (339.11 → 356.01).
Scenes start later as the film goes (line 2: +0.7 s … line 55: +16.3 s); each line's duration
changed by −0.51 s to +1.65 s. Narration text, landing words, images, typed text, claims, graphics
labels, the scene starter, visuals, `photos.json` and credits are unchanged.

## Rights check (now possible)

`rights.py check --project editions/hi`: **ok — 12 images used, 0 not usable**, 0 clips, 0 sounds,
0 maps (the map I005 is an image, not map data); narration credited as "espeak (hi)". Credit lines in
`out/rights.hi.json` are the corrected ones, with the provisional wording kept:

| Images | Credit | Licence as stated |
|---|---|---|
| I002, I004, I006, I009, I011, I012, I013 | The Boston Post, 16 January 1919 | Public domain in the US (published 1919) |
| I001, I010, I015 | Boston Public Library | Public domain (US; publication before 1931 assumed by Wikimedia Commons, not verified) |
| I008 | Boston Elevated Railway Company; City of Boston Archives | Public domain (US; publication before 1931 assumed by Wikimedia Commons, not verified) |
| I005 | 2005 reconstruction by Wikimedia Commons user IMeowbot, after 1895 and 1915 City of Boston maps | Public domain (released by its author) |

"Usable" records what the entries state; it does not resolve the open publication-date question.

## Tests

test_narrate, test_rights, test_editions, test_scenegen, test_pipeline_audio: all OK.
`voice.py validate`: 55 ok.

## Files

Committed: `audio/timing.json`, the re-timed storyboard, `06_film/acts.json`, `out/rights.hi.json`,
this note. Not committed: `audio/narration.m4a` (generated audio, ignored; rebuilt from the segments).
