# Release voice evaluation — Hindi edition (Phase 8, Task 1)

Status: **evaluation only.** No narration was generated or replaced; the espeak scratch voice,
`audio/voice/segments/`, `narration.m4a`, `timing.json` and the mix are unchanged
(checksums in `editions/hi/out/release_backup/SHA256SUMS`).

## 1. Audit of the 55 approved lines

Full per-line table: `release/voice_line_audit.json` (characters, words, timed duration, espeak
duration, numbers, names and loanwords, scripted pause).

| | |
|---|---|
| Lines / characters / words | 55 / 3,557 / 732 |
| Narration time (scratch voice) | 5:56.0 incl. 10 scripted pauses (0.9–2.0 s) |
| Longest lines | 24 and 46 (107 characters, ~9 s), 41 (106 characters) |
| Lines with numbers | 16 — years (1915, 1919, 1925), dates (15 जनवरी), counts (11, 14, 21, 31, 35, 50, 100, 150) |
| Lines with English names or loanwords | 29 — places (बोस्टन, नॉर्थ एंड, कमर्शियल स्ट्रीट, चार्टर स्ट्रीट, कॉप्स हिल, नॉर्थ एंड पार्क), people (जॉर्ज लेही, डब्ल्यू. एल. वेजर), organisations (बोस्टन पोस्ट, सिटी ऑफ़ बोस्टन, प्यूरिटी डिस्टिलिंग कंपनी, रेवियर रबर कंपनी, बोस्टन फ़ायर डिपार्टमेंट), terms (एलिवेटेड, स्ट्रक्चरल, ऑडिटर, ट्रॉली टर्मिनल, गैलन, फ़ुट, मील) |
| Hard cases for any TTS | "डब्ल्यू. एल. वेजर" (initials), "23,00,000"-style figures are already words in the script ("तेईस लाख"), years read as "उन्नीस सौ उन्नीस", English-origin names with nukta and ऑ |

Pronunciation already flagged (voice review): रेवियर (Revere; रिवियर may be closer), लेही (Lahey,
spelled as the Post prints it). The pipeline's `lexicon.json` can map any word to a spoken form
for every provider; it is empty today.

## 2. What this machine can run

4 CPU cores, 15 GB RAM, **no GPU**, ~45 GB free disk. Installed: espeak-ng 1.51 (Hindi voice in
use), onnxruntime 1.29 (CPU), numpy. Not installed: PyTorch, Transformers, Piper, MBROLA (espeak
lists `mb-in1`/`mb-in2` but the MBROLA program and voice data are absent). Network: PyPI is
reachable; **Hugging Face (where most open TTS models are hosted) is not on this environment's
allowlist**, so any model download needs an environment change you approve first.

## 3. Options (free or local only)

Facts marked *verify* are from general knowledge and could not be checked from this session (the
model and licence pages are not reachable). Check each model card's licence before downloading.

| Option | Quality for Hindi documentary | Licence (commercial/YouTube use) | Resources | Pipeline fit |
|---|---|---|---|---|
| **A. Human native narrator, recorded** | best: natural prosody, correct names | the narrator's consent/release (no software licence) | a quiet room, a USB mic; ~1–2 h recording + edit | built in: put `audio/voice/manual/L0001.wav …` (16-bit WAV, one per line); `voice.py` always uses them and never touches them |
| B. espeak-ng (current) | robotic, flat; not releasable | GPL-3 | installed | in use |
| C. espeak-ng + MBROLA hi voices | slightly more natural than B, still synthetic | MBROLA voices are traditionally free for non-commercial use only — *verify* | small (MBROLA + voice ~10–30 MB) | `espeak` provider with an `mb-in*` voice |
| D. Piper (local neural TTS, ONNX) | good for some languages; a Hindi voice may exist — *verify* in the Piper voice list | Piper code MIT; **each voice has its own licence** — *verify* | `piper-tts` from PyPI (1.8.0 seen); one "medium" voice ≈ 60 MB — *verify*; runs on CPU faster than real time | `command` provider: `"cmd": "piper --model <voice>.onnx --output_file {out} < {txt}"`-style (wrap in a small script, since the provider passes files) |
| E. AI4Bharat Indic-Parler-TTS | natural Indian-language voices with style prompts | Apache-2.0 — *verify* | PyTorch + Transformers (~2–3 GB) + model (~3–4 GB) — *verify*; CPU-only would be slow (minutes per line) | `command` provider via a small wrapper script |
| F. Meta MMS-TTS (hin) | intelligible, plain | CC-BY-NC-4.0 (non-commercial) — *verify*; **unsuitable for a monetised release** | PyTorch + ~150 MB model | `command` provider |
| G. Coqui XTTS-v2 | expressive, cloning | Coqui Public Model License (non-commercial) — *verify*; **unsuitable for a monetised release** | PyTorch + ~1.8 GB model; slow on CPU | `command` provider |

Paid services (ElevenLabs, Sarvam) exist in the pipeline but are excluded by the Phase 8 rules.

## 4. Recommendation

1. **Primary: a native Hindi narrator recording (option A).** It is free (if volunteered or
   commissioned outside this pipeline), needs no model download, avoids licence doubt, fixes the
   name pronunciation, and the pipeline already supports it per line. Give the narrator the
   approved script (`editions/hi/03_script/script.md`), the pronunciation notes above, and the
   per-line target durations from `voice_line_audit.json`.
2. **Fallback for a synthetic release: Piper (option D) — only if** a Hindi voice exists whose
   licence allows commercial/online use. Smallest footprint, CPU-fast, onnxruntime already here.
3. If neither works, AI4Bharat Indic-Parler-TTS (E) after confirming its licence and accepting a
   ~6–7 GB install and slow CPU synthesis.
4. Do not use F or G for a public, monetised release (non-commercial licences, to verify).

## 5. Workflow (when authorised; nothing below has been run)

1. Native-speaker review of the script: `voice.py review --project …/editions/hi --by "<name>"`
   (records who checked the Hindi; required anyway before any paid voice).
2. Add pronunciations to `editions/hi/lexicon.json` (e.g. वेजर, रेवियर, लेही) — affects synthetic voices.
3. **Samples first:** 6 lines that cover the hard cases — 1 (date and year), 8 (year, company
   name), 24 (100, long line), 37 (count list), 41 (initials "डब्ल्यू. एल. वेजर"), 46 (1925, longest).
   For a narrator: record these 6, check level and room tone, then the rest. For a TTS: synthesise
   only these 6 into a scratch folder (`voice.py audition` or the `command` provider with `--only`).
4. Listen and compare against the scratch voice; check names, numbers, pace (~130 words/min).
5. Full take: manual WAVs in `audio/voice/manual/`, or `voice.json` switched to the chosen provider.
6. Then the pipeline re-runs **narration → effects → sound → subtitles → review (look) → render →
   join → captions → QC → report**. A new voice changes every line's timing: the storyboard and
   scene re-time automatically, **the look approval lapses and must be given again**, subtitles are
   regenerated, and the film is re-rendered (~70 min here).

## 6. Estimated resources

| | Narrator (A) | Piper (D) | Indic-Parler (E) |
|---|---|---|---|
| Install | none | ~10 MB package + ~60 MB voice (*verify*) | ~6–7 GB (*verify*) |
| Synthesis / recording time | 1–2 h session | < 2 min for all 55 lines | ~1–3 h on 4 CPU cores (*estimate*) |
| Network change needed | no | yes (Hugging Face host) | yes (Hugging Face host) |
| Re-render after | yes (~70 min) | yes | yes |
