# Manual Hindi narration — six-line sample workspace

Purpose: hear a native Hindi narrator on the six hardest lines **before** recording all 55.
Nothing here is used by the film. The pipeline only uses recordings placed in
`editions/hi/audio/voice/manual/`; **do not put files there** until the samples are approved and a
full-recording decision is made (doing so replaces the narration on the next pipeline run).

## Files

* `SCRIPT_SHEET.md` — the six approved lines (1, 8, 24, 37, 41, 46), how numbers expand, why each line.
* `incoming/` — put the recordings here as `L0001.wav`, `L0008.wav`, `L0024.wav`, `L0037.wav`,
  `L0041.wav`, `L0046.wav`. WAVs here are kept out of git (a voice is personal data).
* `check_samples.py` — checks the six files (format, level, clipping, length); changes nothing.

## Recording specification

* **Format:** WAV, 16-bit PCM, mono, 48 kHz (44.1 kHz accepted). One file per line, the whole line
  in one take; ~0.3 s of silence before and after (the pipeline trims the ends).
* **Level:** speech peaks around −6 dBFS, never clipping; RMS roughly −20 to −16 dBFS.
* **Room:** quiet, no echo (a small furnished room; a blanket behind the microphone helps); no music,
  fan or traffic. Same microphone, distance and room for every line.
* **Delivery:** calm documentary narration, ~125–135 words a minute; read the text exactly; numbers
  read naturally in Hindi with the same values; names as noted in `SCRIPT_SHEET.md`.
* **Consent:** a short written note from the narrator that the recordings may be used in the film
  and its online release, with the credit they want. Keep it with the project, not in git.

## After recording

1. `python3 productions/molasses-flood/release/narration_samples/check_samples.py`
2. Listen against the scratch voice; note any word to fix.
3. Decide: record all 55 lines (then the voice workflow in `release/voice_evaluation.md` §5), or try
   another narrator. Moving files into `audio/voice/manual/` is a separate, authorised step; it
   re-times the film and re-opens the look gate.
