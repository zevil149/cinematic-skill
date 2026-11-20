# Sound

Three layers: the narration, synthesised effects, and an optional score. Effects should be felt, not noticed; the voice always wins.

## Effects

```bash
python3 scripts/render.py --project my-film --cues     # sfx_cues.json
python3 scripts/build_sfx.py --project my-film          # audio/sfx.wav
```

Items cue their own sounds:

| Item | Sound |
| --- | --- |
| `Print` | pop (slide for torn clippings) |
| `Stamp` | stamp |
| `PenMark` | pencil (marker for highlights, snip for quick strikes) |
| `Chalk` | tick per mark |
| `Counter` | ticks |
| `Route` | whoosh |
| `StringLine` | slide |
| `XMarker`, `MapPin` | pop |
| `Ledger` | impact |

Fast camera moves get a whoosh. A cue the scene places by hand within 0.15 s replaces the automatic one, and `sfx=False` mutes an item.

Add the score-like moments by hand:

- `film.cue("boom", title_t, 0.55)`: the title or the biggest reveal. Use it once or twice per film.
- `film.cue("riser", L(9) - 1.3, 0.5, dur=1.2)`: a crescendo into a new section. It peaks at `t + dur`, so end it on the line start.
- `film.cue("heartbeat", t)` once a second, 3 to 6 beats, under the tensest line. Or `film.cue("clock", t, dur=4)`.
- `film.cue("impact", t, 0.4)`: a number or year landing. Also available as `BigText(hit=0.4)`.
- `film.room_tone = [[0, film.duration]]`: a quiet room bed. Leave gaps in it for deliberate silence.

## Score

Optional. A documentary bed works best when it is sparse:

- a low pulse
- a few held notes
- silences that line up with section changes

Generate one (ElevenLabs Music, or any music model whose terms allow it), use a licensed track, or skip it. Most tense true stories play better on effects alone, with the score very low. Check where the score's own breaks fall, and move it (or cut lines) so they hit section starts.

## Mix

```bash
python3 scripts/mix_soundtrack.py --project my-film                                    # voice + effects
python3 scripts/mix_soundtrack.py --project my-film --music audio/score.mp3 \
    --music-db -4 --sfx-db -3 --duck-ratio 3 --duck-threshold 0.03 --music-level 0.07 --music-eq-dip 4
```

- The score ducks under the narration (sidechain), and a slow leveller stops a building score swamping the voice. A small dip at 2.4 kHz clears the voice's presence band.
- Two-pass loudness: -15 LUFS integrated, -1.5 dBTP. That suits X, YouTube and Instagram; YouTube turns louder files down anyway.
- Check the result by listening on phone speakers and on headphones. If you can follow the score's melody, it is too loud.
- `--stems` writes the ducked music alone, to measure it. Under -30 LUFS in a -15 mix reads as "felt, not followed".

## Language editions: library, cue sheets and the mix

In a production with editions, music and sounds come from one shared library and each edition has its own cue sheet and mix, placed on its own narration timing (`narrate.py`). `mix_soundtrack.py` above stays as it is for single films.

### The library (`audiolib.py`)

Nothing is downloaded for you: you bring the files, and each is copied into `audio_library/files/` at the production root (your original is never moved or changed) with its SHA-256, source, licence, attribution and clearance in `audio_library/library.json`.

```bash
python3 scripts/audiolib.py add --project my-doc ~/music/pulse.wav --kind music --source own --by "Your Name"
python3 scripts/audiolib.py add --project my-doc track.mp3 --kind music --source licensed \
    --license "Music library standard licence" --license-ref "licence 8812, downloaded 2026-11-01" --title "..." --creator "..."
python3 scripts/audiolib.py clear --project my-doc A002 --by "Your Name" --note "the standard licence covers online video"
python3 scripts/audiolib.py add --project my-doc rain.wav --kind sfx --source cc \
    --license-url https://creativecommons.org/licenses/by/4.0/ --creator NAME --source-url PAGE --title "Rain"
python3 scripts/audiolib.py add --project my-doc door.wav --kind sfx --source freesound --freesound-id 4242 \
    --license-url http://creativecommons.org/publicdomain/zero/1.0/
python3 scripts/audiolib.py verify --project my-doc A004 --online      # reads the licence its Freesound page states
python3 scripts/audiolib.py list  --project my-doc
```

| Source | Usable when |
| --- | --- |
| `own` (`--by` required) | at once: your own work |
| `cc` | CC0 and public domain at once; CC BY and BY-SA at once, with the attribution recorded and written to the credits. NC, ND, an unrecognised or unstated licence ("free to download" is not a licence): refused |
| `licensed` (`--license-ref` required) | after you clear it: `clear --by NAME --note WHY` (does the licence cover this film, its platforms, monetisation?) |
| `freesound` (`--freesound-id` required) | after its licence is verified against the sound's page (`verify --online`, metadata only, `FREESOUND_API_KEY` from the environment) or cleared by you. NC and Sampling+ are refused |
| `synth:bed` (in a cue sheet) | always: made here from code |

A refused licence can still be cleared by you, with your name and a note; it is recorded as an override and marked in the credits. An asset whose file changed after it was added, or went missing, is refused until it is added again. Nothing that is pending or refused is ever mixed.

### The cue sheet (`cuesheet.py`)

```bash
python3 scripts/cuesheet.py init --project my-doc/editions/en    # audio/cues.json: a synthesised bed under the whole film
python3 scripts/cuesheet.py plan --project my-doc/editions/en    # every cue resolved to times
python3 scripts/cuesheet.py mix  --project my-doc/editions/en    # audio/mix.m4a, mix_report.json, music_credits.md
```

`audio/cues.json` belongs to the edition (tagged with its language) and places music cues (`from`, `to`, `offset`, `loop`, `gain_db`, `fade_in`, `fade_out`, `duck`), library sounds (`at`, `gain_db`) and gaps (music silent, with short fades) on anchors: `{"t": 12.5}`, `{"film": "end"}`, `{"line": 7, "edge": "end"}`, `{"line": 7, "word": "storm"}` (the word's own time from `timing.json`) or `{"section": "s02", "edge": "start"}`, each with an optional `"shift"`. The same cue sheet shape gives the English and Hindi films different times, because each reads its own timing. Effects are synthesised by default: `render.py --cues` and `build_sfx.py` on the edition write `audio/sfx.wav`, which the mix includes (`"synth_sfx"`).

The synthesised bed (`"asset": "synth:bed"`) is a low drone and a soft pulse, about -20 dBFS, falling silent for a breath into each section change.

### The mix and its checks

- Music is faded, levelled and silenced in the gaps, then ducked under the narration (12 dB by default, starting just before each line, released over 0.6 s); effects ride on top; a limiter and two-pass loudness bring it to **-15 LUFS integrated, -1.5 dBTP**.
- Checked before anything is written: integrated loudness within 1 LU of the target, true peak under the ceiling, no clipped samples, the mix as long as the narration, and the narration at least 6 dB over the music while it speaks (a warning under 10 dB). A failed check writes nothing.
- `audio/mix_report.json` records the measured loudness, true peak, sample peak, the voice-over-music margin, every cue and every asset with its licence, attribution and who cleared it. `audio/music_credits.md` lists the credits for the film's description.
- Resume: the same inputs make nothing new. `narration.m4a`, the library files and `sfx.wav` are only read. A `mix.m4a` that `cuesheet.py` did not make (from `mix_soundtrack.py`, or yours), or that changed since, is never replaced without `--force`, which keeps it as `mix.m4a.bak`.
