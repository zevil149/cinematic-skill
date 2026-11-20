# Voice

The film is timed to the voice, so the voice comes before the picture. Use a free scratch voice to build against, then swap in the final one. The scene asks for line starts and spoken words, never fixed seconds, so it re-times itself.

## Scratch voice

```bash
python3 scripts/tts_say.py --project my-film                         # macOS say, or espeak-ng on Linux
python3 scripts/tts_say.py --project my-film --voice Daniel --rate 165
```

It reads each take in one go, with a clear pause between lines, and writes `audio/takes/<take>.wav`.

## Final voice: any provider

Record **one take per section**, not one call per line. One call keeps the delivery even. Per-line calls change pace and pitch from line to line, which sounds stitched together.

- **A command-line TTS** (Piper, a provider's CLI, your own script): `tts_say.py --cmd 'tool --in {txt} --out {out}'`. `{txt}` is a file with the take's lines, one paragraph each.
- **An API or app** (ElevenLabs, OpenAI, Higgsfield, PlayHT): send each take's `spoken` lines joined with a paragraph break (or the provider's pause tag), and save the result as `audio/takes/<take>.wav`. Any format ffmpeg reads is fine.
- **A person**: one file per take, a beat of silence between lines.

Then:

```bash
python3 scripts/split_takes.py --project my-film
python3 scripts/build_narration.py --project my-film                 # natural read
python3 scripts/build_narration.py --project my-film --target 88     # fit to 88 s (0.90 to 1.15x only)
```

## Checking the split

`split_takes.py` measures every line's speaking rate in letters per second of actual speech, and flags lines more than 35% off the median. A flag nearly always means one of three things:

- **Two lines run together.** The voice did not pause, so the cut landed a sentence late. Force the boundary in `audio/overrides.json`: `{"cut_before": {"53": 26.80}}`, the line id and the seconds into its take where that line starts. Find the spot by listening, or with `ffmpeg -i take.wav -af silencedetect=noise=-40dB:d=0.1 -f null -`.
- **A dramatic pause inside a line** ("He was... thirty-two") got taken for a boundary. Force the real one the same way.
- **A dropped or doubled word.** Re-record that take.

Listen to every flagged line. A cut in the wrong place shifts every visual hit after it.

## Re-recording

Re-record a whole take, never a single line: one line patched in from another call stands out. After any change, run `split_takes.py` and `build_narration.py` again, then `render.py --probe` on the affected lines. If a line got noticeably longer, check its camera keys still have time.

## Delivery notes

- Ask for a measured documentary read. A pace of 150 to 170 words a minute suits these films.
- Numbers and names go in `spoken` exactly as they should be said.
- A tempo fit beyond 0.90 to 1.15x sounds wrong. `build_narration.py` refuses it: cut or add lines instead.
- The narration lands at -16 LUFS. `mix_soundtrack.py` sets the final loudness.

## Language editions: the voice framework

In a production with editions (`references/pipeline.md`), each edition has its own voice: `editions/<lang>/voice.json` (provider, voice, model, settings), its own lexicon and its own audio. `voice.py` makes one WAV segment per narration line from the edition's exported `script.json`:

```bash
python3 scripts/voice.py plan     --project my-doc/editions/hi    # what would be made, characters, cost
python3 scripts/voice.py synth    --project my-doc/editions/hi
python3 scripts/voice.py validate --project my-doc/editions/hi
python3 scripts/voice.py providers
```

- **Providers.** `espeak` is the free scratch voice (`en-us` for English, `hi` for Hindi; every new edition starts with it). `command` runs any local TTS tool: `"cmd": "mytts --in {txt} --out {out} --voice {voice} --lang {lang}"` in `voice.json`. `mock` makes test audio. The paid ElevenLabs and Sarvam providers come next, one audition at a time.
- **One language per edition.** `voice.json`, its locale and its voice must belong to the edition's language, and the script, manifest and segments are all tagged with it: an English voice is refused for the Hindi edition, and the other way round.
- **Resume.** Each segment records a request hash (the spoken text after the lexicon, the provider and its whole configuration, the language). A run makes only what is missing, invalid or changed.
- **Your edits are kept.** A segment you edit is locked; `synth --force` remakes it and keeps yours as `.bak`. A recording of your own at `audio/voice/manual/L0012.wav` (16-bit WAV) is always used and never touched.
- **Validation** flags missing, unreadable, empty or silent segments (errors), and clipping, stale text and lengths far from the expected pace (warnings: listen to those lines).
- **Whole sections or lines.** A provider with reliable word timings reads each section at once for an even delivery, and the read is cut into line segments; the others read line by line, with the neighbouring lines passed as context.
- **Spend.** A paid provider runs only with an estimate under the cap (`--max-cost`, $5 a run by default), `--confirm-cost`, and, for Hindi, a native-speaker review of the current script (`voice.py review --by NAME`; a changed script needs a new review). Every paid request is logged in `audio/voice/spend.json`. API keys come from the environment only.

Joining the segments into `audio/narration.m4a` and `audio/timing.json` for the film is the next step of the pipeline.

