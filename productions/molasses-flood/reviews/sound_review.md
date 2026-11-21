# Sound stage — Hindi edition

`docpipe.py run --until sound`, 2026-11-21: **0 errors, 0 warnings**; `cuesheet.py plan`: ok; a
rerun reports it up to date.

## Cue sheet (`audio/cues.json`, the pipeline's default)

* **Music:** one cue, M1 `synth:bed`, 0:00.0–5:56.0, −8 dB, 2 s fade in, 3 s fade out, ducked
  under the narration (−12 dB, attack 0.08 s, release 0.6 s).
  The bed is synthesised by cuesheet.py: a low drone (root, fifth, octave) breathing slowly, a
  soft low pulse once a second (slightly stronger every fourth), falling silent for a breath into
  every section change. About −20 dBFS RMS before mixing. No melody, no rise, no sound that
  imitates the flood or its effects. Restrained by design.
* **Effects:** `audio/sfx.wav` from the effects stage (43 board and camera cues), at −7 dB.
* **Library sounds:** none. **Gaps:** none. Nothing downloaded, bought or licensed;
  `music_credits.md`: music and effects "synthesised for this film".

## Mix (`audio/mix.m4a`, `audio/mix_report.json`)

| | Pipeline report | Measured independently (ffmpeg ebur128) |
|---|---|---|
| Duration | 356.03 s (5:56.0) | 356.1 s |
| Integrated loudness | −15.0 LUFS (target −15.0, tolerance 1 LU) | −15.0 LUFS |
| True peak | −1.5 dBTP (ceiling −1.5) | −1.5 dBFS |
| Sample peak | 0.842 | |
| Clipped samples | 0 | |
| Loudness range | | 2.1 LU |
| Narration over music | 17.8 dB while speaking (≥ 10 dB is good; < 6 dB is an error) | |

The true peak sits exactly at the ceiling: within the pipeline's tolerance (cuesheet `TP_TOL`).

## Tests

test_audio_mix, test_pipeline_audio, test_editions, test_report: all OK.

## Notes for the look and final review

* The once-a-second pulse is gentle, but over six minutes it gives a steady, slightly tense
  rhythm; if it reads as dramatic, lower M1's `gain_db` or ask for a pulse-free bed.
* Every level is judged on a robotic scratch voice; a real narrator will need a new mix.

## Files

Committed: `audio/cues.json`, `audio/mix_report.json`, `audio/music_credits.md`, this note.
Not committed: `audio/mix.m4a` (generated audio, ignored; the stage rebuilds it).
Approved content (script, storyboard, scene starter, timing, effects list, visuals, credits) is unchanged.
