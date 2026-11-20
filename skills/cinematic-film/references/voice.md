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
python3 scripts/voice.py audition --project my-doc/editions/en --lines 8 --confirm-cost   # a short sample, to choose by ear
python3 scripts/voice.py verify   --project my-doc/editions/en [--online]
python3 scripts/voice.py providers
```

- **Providers.** `espeak` is the free scratch voice (`en-us` for English, `hi` for Hindi; every new edition starts with it). `command` runs any local TTS tool: `"cmd": "mytts --in {txt} --out {out} --voice {voice} --lang {lang}"` in `voice.json`. `mock` makes test audio. `elevenlabs` (English) and `sarvam` (Hindi) are the paid voices; see below.
- **One language per edition.** `voice.json`, its locale and its voice must belong to the edition's language, and the script, manifest and segments are all tagged with it: an English voice is refused for the Hindi edition, and the other way round.
- **Resume.** Each segment records a request hash (the spoken text after the lexicon, the provider and its whole configuration, the language). A run makes only what is missing, invalid or changed.
- **Your edits are kept.** A segment you edit is locked; `synth --force` remakes it and keeps yours as `.bak`. A recording of your own at `audio/voice/manual/L0012.wav` (16-bit WAV) is always used and never touched.
- **Validation** flags missing, unreadable, empty or silent segments (errors), and clipping, stale text and lengths far from the expected pace (warnings: listen to those lines).
- **Whole sections or lines.** A provider with reliable word timings reads each section at once for an even delivery, and the read is cut into line segments; the others read line by line, with the neighbouring lines passed as context.
- **Spend.** A paid provider runs only with an estimate under the cap (`--max-cost`, $5 a run by default), `--confirm-cost`, and, for Hindi, a native-speaker review of the current script (`voice.py review --by NAME`; a changed script needs a new review). Every paid request is logged in `audio/voice/spend.json`. API keys come from the environment only.

### ElevenLabs (English) and Sarvam (Hindi)

Both are paid, both refuse the other edition's language, and neither runs without the spend guard. Keys come from the environment only, read at the moment of a request: `ELEVENLABS_API_KEY` and `SARVAM_API_KEY`. A `voice.json` with a field that looks like a key is refused; keys never reach a URL, a manifest, `spend.json`, an error message or the output (a refusal that echoes the key back is redacted). `voice.py providers` says whether each key is set, never what it is.

```json
{"lang": "en", "locale": "en-US", "provider": "elevenlabs", "voice": "<voice id from your library>",
 "model": "eleven_multilingual_v2", "output_format": "pcm_24000", "mode": "auto",
 "settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": true, "speed": 1.0}}
```

```json
{"lang": "hi", "locale": "hi-IN", "provider": "sarvam", "voice": "anushka", "model": "bulbul:v2",
 "inr_per_usd": 85.0, "mode": "auto",
 "settings": {"pace": 1.0, "pitch": 0.0, "loudness": 1.0, "speech_sample_rate": 22050, "enable_preprocessing": true}}
```

- **ElevenLabs** reads with character timestamps (`/v1/text-to-speech/{voice}/with-timestamps`, raw PCM, so no ffmpeg), so a whole section goes in one request and is cut into lines by word; in `"mode": "line"` each line carries its neighbours as `previous_text` and `next_text`. Checked before sending: the voice id's form, the model (`eleven_multilingual_v2`, `eleven_v3`, `eleven_turbo_v2_5`, `eleven_flash_v2_5`; `"allow_unknown_model": true` for a newer one), the settings and their ranges, `output_format`, `seed`, an optional `language_code` (must be `en`), and at most 5,000 characters a request. `verify --online` looks the voice id up (free, no synthesis).
- **Sarvam** (Bulbul) reads line by line in `hi-IN`. Checked: the model (`bulbul:v2`, `bulbul:v3`), the speaker (the `bulbul:v2` list: anushka, manisha, vidya, arya, abhilash, karun, hitesh), pitch, pace, loudness, sample rate, 1,500 characters a request. Sarvam bills in rupees and the cap is in dollars, so `inr_per_usd` (your own rate) is required; the spend log records rupees, dollars, the rate and the request id. If the API names its fields differently, `"text_field"` and `"language_field"` follow it.
- **Choose by audition.** The voice and model are never assumed: `voice.py audition` reads the first lines (8 by default) into `audio/voice/auditions/<provider-model-voice>/` with `audition.json`, never into the segments. It goes through the same guard (cap, `--confirm-cost`, Hindi review) and is once per provider and edition unless `--again`.
- **Prices** are cautious defaults, not your plan's: ElevenLabs $0.10 per 1,000 characters ($0.05 for turbo and flash), Sarvam ₹15 per 10,000 characters for `bulbul:v2` and ₹30 for `bulbul:v3`. Set `"price_per_1k"` (USD) or `"inr_per_10k_chars"` to your plan, and the estimate, the cap and the log follow. Price, rate and limit fields do not change the request hash, so a new rate never remakes audio.
- **Errors and retries.** A rate limit (429) or a server error (500, 502, 503, 504) is retried up to four attempts, honouring `Retry-After` (a wait over 60 seconds gives up). A refusal (bad key, invalid request, quota, unknown voice) is reported with the service's own words and not retried, and neither is a network failure or timeout, which the service may already have done and billed. A paid request is logged only when audio comes back.
- **Offline.** With `CINEMATIC_OFFLINE=1` (the tests set it) no request is sent. The tests replace the network with a fake; nothing in them reaches a real service.

### The edition's narration track and timing (`narrate.py`)

```bash
python3 scripts/narrate.py --project my-doc/editions/hi                # natural read
python3 scripts/narrate.py --project my-doc/editions/en --target 600   # fit to 10:00 (tempo 0.90-1.15x only)
```

- **What it joins.** Each line's manual recording if there is one, else its segment (yours when you edited it), in script order. Silence is trimmed off both ends of every line, and the pacing is set here: a 0.9 s lead, each line's `gap_after` (0.45 s, 1.0 s after a take, or what the script says) and a 3 s tail. The track is `audio/narration.m4a` at -16 LUFS. Segments, manual files and edited files are only read.
- **`audio/timing.json`** is the film's clock as before (per line `id`, `caption`, `vo`, `start`, `end`, `duration`), plus `"lang"` and per-line `"words"`: `[{"w", "start", "end"}]` in film seconds. Words come from the voice where it timed them (ElevenLabs, the mock: `"words_from": "voice"`), else from the language's own timing rules (`"estimate"`: espeak, Sarvam, manual and edited lines). `"audio"` says whether a line is the voice, yours (`edited`) or your recording (`manual`).
- **The camera lands on the word.** `doc.W(line, "word")` uses the word's own start when the line has word times, so `scenekit` starters and your scenes hit the key word. A timing file without words (from `build_narration.py`) works exactly as before.
- **Re-timed scenes.** Afterwards the storyboard is built again on the voice's times (`"timing": "voice"`) and, if `scenegen.py` has run, the scene starters too; a scene you edited is kept (`--no-retime` skips this step).
- **Resume.** Built parts are cached in `audio/voice/build/`; a run with the same audio, script, pacing and tempo changes nothing, and one changed line makes one new part.
- **Nothing is bought here.** A missing, invalid or stale line stops the build with a pointer to `voice.py synth`, which keeps its spend guard; `narrate.py` never calls a provider.
- **Yours is kept.** A `narration.m4a` or `timing.json` that `narrate.py` did not make (for example from `build_narration.py`), or that changed since, is never replaced without `--force`, which keeps both as `.bak`. A timing file of another language is refused.

Music and effects for each edition, placed on this timing, are in `references/sound.md` (`audiolib.py`, `cuesheet.py`).

