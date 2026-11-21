# Effects stage — Hindi edition

`docpipe.py run --until effects`, 2026-11-21: **0 errors, 0 warnings**. A rerun reports it up to date.

* **What:** `audio/sfx.wav` (356.0 s, the length of the narration timing) and `audio/effects.json`.
* **How:** synthesised locally by build_sfx.py from noise and tones. No samples, libraries,
  downloads or services; nothing to license.
* **Where the cues come from:** only the scene starter's own items (43 cues, all `source: scene`).
  No cue sheet exists yet (`from_cue_sheet: 0`), no room tone, scale 1.0.
* **Levels:** max −1.0 dBFS (the builder's headroom), mean −30.8 dB; the mix sets the track's level.

## The 43 cues

| Kind | Count | What it marks (build_sfx.py) |
|---|---|---|
| whoosh | 28 | a camera move to the next item |
| pop | 8 | a print or card landing on the board |
| slide | 7 | a newspaper clipping sliding in |

They fall on the lines where the camera moves or an image or card arrives: for example line 1
(pop, the panorama), 3 and 10 (whoosh + slide, the Post), 7 and 53 (whoosh + pop, the tank card),
18 (the map), 25 (the wreckage card), 26 (the elevated railway), 41 (the Post's explosion-theory
column), 54 (the panorama); `audio/effects.json` lists every time.

**No sound depicts the event.** All 43 are board and camera sounds, as in any evidence-wall film.
There is no rumble, boom, crash, water, crowd, siren or other sound that would suggest what
happened, how it sounded, or anything the sources do not support.

## Tests

test_effects, test_pipeline_audio, test_editions: all OK.

## Files

Committed: `audio/effects.json` (the cue list), this note. Not committed: `audio/sfx.wav` (98 MB of
generated audio, ignored; the stage rebuilds it from the scenes and timing).
Approved content (script, storyboard, scene starter, timing, visuals, `photos.json`) is unchanged.
