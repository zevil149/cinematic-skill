# Phase 6.9 pilot: a controlled production through every stage

The roadmap's last milestone asks for a production made under real conditions, to show what automated fixtures cannot. This pilot ran the whole pipeline once, offline, end to end. **It is not a real production.** The separation below is deliberate.

## What was real and what was not

| | In this pilot | Real-production equivalent | Validated here? |
|---|---|---|---|
| Pipeline | every docpipe stage and gate, through the CLI, two editions (English, Hindi) | the same | **yes** |
| Approvals | given with `docpipe.py approve`, after the review stills were looked at, by the agent running the pilot | a person | gates exercised; **no human judged the film** |
| Acts | two acts, title cards in English and Hindi, crossfaded join | the same | **yes** |
| Resolution | 1920x1080, full render, captions burned | the same | **yes** |
| Research and script | the repository's test fixtures (the Wright brothers' first flight; three lines repeated per section) | a researched, written script | **no**: content is a fixture |
| Images | the repository's own example frames (`examples/*.webp`, MIT), used as "own" files with a stated licence and credit; the rest designed cards | archive photos and footage | rights path, prints and credits exercised; **no archive image was downloaded** (not authorised) |
| Voice | espeak-ng (free, local), estimated word timing | a professional or paid TTS voice | **no**: paid voices need separate authorisation |
| Music | the synthesised bed; synthesised effects | licensed music | **no**: no licensed music was available |
| Fonts | the condensed role fell back to the system default (Inter) on this machine | pinned fonts (`get_fonts.py` downloads them) | QC warned, as designed; **no font was downloaded** |

Driver: `tests/pilot_6_9.py OUT build`, look at `07_review/<lang>/act_NN/sheet.jpg`, then `tests/pilot_6_9.py OUT finish`.

## Results

| | English | Hindi |
|---|---|---|
| Film | 126.15 s: the timeline (116.15 s) and 10.0 s of closing credits; 3,784 frames at 1920x1080 | 111.70 s: 101.69 s and 10.0 s of credits; 3,351 frames |
| Acts | 2, crossfade at 49.31 s (centred on the act change), title card "Twelve seconds in the air" | 2, title card "हवा में बारह सेकंड" (label भाग 2) |
| QC | complete; 0 errors; 1 warning (font fallback); nothing left unchecked | complete; 0 errors; 1 warning (font fallback) |
| Loudness | -15.0 LUFS (target -15.0), true peak -1.2 dBTP | -15.0 LUFS, -1.5 dBTP |
| Narration found in the film | every line; lowest share 14.8 dB over music and effects; aligned at 5 ms | every line; lowest 13.8 dB; 5 ms |
| Layout | 20 typed words and 6 cards measured: no overflow, no caption collision, no still frame of bare board | the same |
| Rights | 3 images used (own files, MIT, as stated), all usable; credited on screen and in `credits.md` | the same, with Hindi headings |
| Final report | complete for both editions; 9 claim-to-line warnings on the English fixture lines that paraphrase their claim | |
| Resume | a second run: every stage up to date in 1.7 s | |
| Gate | `run --only render` before the look was approved: refused, nothing rendered | |

Time on this machine (4 cores, 16 GB, 3 render workers): from the visuals gate to the look, 96 s; the finishing stages for both editions (render, credits, join, captions, QC, report), 56 minutes for about 4 minutes of finished film (two editions), so about 14 minutes of machine time per minute of film, captions included.

Sizes: the clean 1080p films are 370 MB (English, 126 s) and 337 MB (Hindi, 112 s), about 23 Mbit/s; the captioned films 318 MB and 287 MB; the near-lossless act intermediates (CRF 12) 286 MB and 382 MB for the English acts.

## What the pilot showed that the fixtures did not

1. **The closing pull-back cuts items at the frame edges.** The wide shot that ends each act is placed from the slot centres, not from the items' measured extent, and frames typed words and cards half outside (review stills `probe_close`). Hero shots were reworked in 6.3; this shot was not.
2. **Frames between lines are not framed.** While the camera moves from one line's hero to the next, items pass the frame edge (for example 5.5 s in the English film). Only settled shots are framed and checked.
3. **The films are large.** About 23 Mbit/s at CRF 18, mostly because the film grain is expensive to encode; a platform will re-encode them, but uploads and storage are heavy. Neither the grain strength nor the delivery CRF was tuned for size.
4. **Machine-dependent fonts are the norm, not the exception.** On a clean Linux machine the condensed role falls back to Inter; QC said so on every edition. Without `get_fonts.py` (a download) or project font files, the type is not the type the look was designed with.
5. **The claim-to-line check is noisy on paraphrase.** The fixture's opening line ("a machine left the sand") cites a claim it paraphrases; the check flagged it nine times. It is a warning and reads as intended, but on a real script it needs calibrating against a person's judgement.
6. **What the pilot could not test.** Real archive photographs and their framing, licensed music and its mix against the voice, a professional voice and its word timing (every word time here was an estimate), and a person's judgement of the film. These are the conditions that decide whether the film is good; they need authorisation for downloads and paid services, and a human reviewer.

## Not done

Real archive downloads, paid voices and licensed music were not used: they were not authorised. No human watched the films. The pilot's outputs (films, reports) are not committed; they are reproducible with the driver.
