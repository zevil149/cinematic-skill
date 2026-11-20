# Documentary pipeline: implementation plan

Goal: one command from a topic to a finished, credited, captioned 1080p documentary of 5, 10, 20 or 30 minutes, built on the existing Cinematic Skill (Skia engine, film tools, approval gates) without breaking what works.

Principles carried over from the skill:

- **The agent researches and writes; the tools check.** Nothing reaches the film without a source, and every stage refuses to continue while its check fails.
- **People approve at gates**: outline, script, the look, a draft.
- **The existing tools stay the engine.** Pipeline stages wrap them, never fork them. Every project stays a valid project for `make_beats.py`, `render.py` and the rest.
- **No credentials in files.** API keys come from environment variables (or the cloud proxy) at run time.

## What exists today

| Area | In the repo | State |
| --- | --- | --- |
| Research | `references/story.md` guidance; free-text `fact_notes` in `script.json` | No store, no sources, no checks. **Built in phase 1** |
| Script | `script.json` format; `make_beats.py` lints chronology, line length, digits, typed vs spoken | Works for short films; no fact check, no length presets. **Extended in phase 1** |
| Storyboard | `beats.md` beat table | Per line, no camera or image plan. **Built in phase 1** |
| Images | `fetch_commons.py`: Commons search, licence check, refusal of non-free files, `credits.md`; retry and resume (PR #1) | Commons only; picked by hand into `photos.json`; no link from the script's needs |
| Licensing | Free-licence regex, `credits.md`, rights rules in `references/archive.md` | Works; needs per-image checks in the final QC |
| Footage | none | **Engine is stills only** (see decision C) |
| Camera | `engine.py`: one board, spline camera, spotlight, items, looks; `scene.py` written by hand per film | Works; no generator from a storyboard |
| Voice | `tts_say.py` (say, espeak-ng, any CLI), `split_takes.py`, `build_narration.py` | Works; no API provider adapters, no per-take resume |
| Music, effects | `build_sfx.py` (synthesised), `mix_soundtrack.py` (ducked, two-pass loudness, optional score) | Works; the score is a file the user supplies |
| Render | `render.py`: probes, strips, cue list, memory-aware parallel MP4 | Works for one board; a 20 to 30 minute board needs splitting (see decision B) |
| Captions | `burn_captions.py`: four styles, SRT | Works |
| Automation | none: the agent runs each tool | **`docpipe.py` built in phase 1** |
| QC | `check_setup.py`; the self-review list in SKILL.md; `tests/check.mjs`; CI renders the starter film | No per-stage validators for images, audio or video; no final report |

## Phases

### Phase 1: project, topic, research, outline, script, scenes (this change)

- `docpipe.py`: `new`, `run`, `status`, `approve`. Stage folders `00_topic` to `04_scenes`; each stage records a hash of its inputs and is skipped when they are unchanged (resume); gates on outline and script; approvals lapse on edits.
- `research.py`: sources (url or print citation, accessed date, reliability tier) and claims tied to them; status supported, single-source, weak, disputed or unsupported; `research.md`; optional url check.
- `outline.py`: length budgets for 5, 10, 20 and 30 minutes (any length from 1 to 60); acts for long films; chronology and budget checks; `outline.md`.
- `narration.py`: lines cite claims; fact check (uncited lines, numbers not in the cited claims, disputed without a hedge, unsupported claims); spoken text for numbers, years, dates, money and percentages; export to `script.json` that never replaces a hand-written one.
- `storyboard.py`: one scene per line with timestamps (estimated, or from `audio/timing.json`), key word, camera suggestion and image needs.
- `tests/test_docpipe.py` (25 tests, standard library only), run in CI.

### Phase 2: visual engine (done)

Built as planned below, plus footage (decision C) and scene starters (decision D), which moved forward from phases 4 and 5:

- `archives.py`, `visuals.py`: Commons (images and video), Library of Congress, Openverse, Smithsonian Open Access and Europeana; licences as stated (free, check, refuse); attribution; paced, cached, cooldown-aware HTTP; resumable downloads; designed fallback cards; `photos.json` and `footage.json` merged without touching user entries.
- Engine: `Print(move=ken_burns(...))`, `Footage`, `Parallax`, camera moves; `prep_footage.py`.
- `scenegen.py`, `scenekit.py`: an editable `scene.py` per act, edits never overwritten.
- docpipe stages `visuals` (gate) and `scenegen`; tests never reach the network.

The original phase 2 plan:


- `docpipe` stage `images`: read `04_scenes/image_needs.json`, search each need, write candidates for the agent to choose from, then download the chosen ones with retry and resume, and merge them into `photos.json`.
- More archives behind one interface: Library of Congress (`?fo=json`), Smithsonian Open Access (CC0), National Archives catalog, Europeana. Each adapter records licence, credit and source url, and refuses non-free files as `fetch_commons.py` does.
- Rights QC: every image used has a licence and credit; BY and BY-SA get their attribution text; "no known restrictions" stays flagged until a person clears it.
- Tests with recorded API responses (no network in CI).

### Phase 3: voice, audio and language editions (approved; milestone by milestone)

English is the default language for the main (US) channel; Hindi is a fully supported second channel. One shared production (topic, research, outline, beats, visuals) feeds separate language editions with their own script, voice, timing, subtitles, metadata and films.

| Milestone | Scope | State |
|---|---|---|
| 3.0 | Language plugins (`scripts/lang/`), `editions/<lang>/` folders, shared beats, isolation checks, legacy projects unchanged | done |
| 3.1 | Hindi language plugin: numbers, dates, currency, Devanagari digits, syllable timing, lexicon, fact-check number words | done |
| 3.2 | Devanagari rendering: Noto Devanagari fonts and HarfBuzz shaping (licences verified first) | done |
| 3.3 | Voice framework: per-edition voice and lexicon, mock, espeak and command providers, manifest, resume, edit lock | done |
| 3.4 | ElevenLabs and Sarvam adapters, cost estimate, auditions (built and tested offline; no live or paid call yet: the first audition needs separate approval) | done |
| 3.5 | Timing per edition: segments, `narration.m4a`, word timings in `timing.json`, re-timed storyboard and scenes | done |
| 3.6 | Music and effects: user-licensed tracks and a synthesised bed, rights gate, per-edition cue sheet and mix | done |
| 3.7 | Subtitles per edition (SRT, WebVTT) and word-level caption timing, actual and estimated times labelled | done (per-edition metadata such as titles and chapters is not part of this milestone; open for a later decision) |
| 3.8 | docpipe stages (voice, narration, sound, subtitles, per edition and single-language), docs, CI with both editions end to end | done (metadata, in the original acceptance line, is not built: open for a later decision) |

Approved decisions: ElevenLabs and Sarvam adapters plus espeak and command providers (Azure later); section-level synthesis split into line segments where timestamps are reliable, per-line otherwise; Devanagari for Hindi narration and subtitles, Latin only for allowed technical terms; music from user-licensed tracks and a synthesised bed (CC libraries optional, gated); synthesised effects (Freesound later); `uharfbuzz` and Noto Devanagari after licence checks; a $5 spend cap per run and explicit confirmation for every paid call; optional `words` and `lang` in `timing.json`; Hindi 130-140 and English 145-155 words a minute, configurable; shared beats with a fork option; native-speaker review before paid Hindi synthesis; research canonical in English; per-edition on-screen text; no voice cloning.

### The original phase 3 sketch: voice

- Provider adapters for API TTS (ElevenLabs, OpenAI and others) next to the existing `say`, espeak-ng and `--cmd` routes. Keys only from environment variables; never written to the project or logs.
- One call per take, cached by a hash of its text, voice and settings, so a re-run only records what changed.
- Stage `voice`: scratch voice first, final voice when configured; `split_takes.py` flags become QC warnings; `timing.json` re-times the storyboard.

### Phase 4: film assembly (starters done in phase 2)

What remains: probes and strips per act as a `review` stage, smarter layouts (maps and strings between clusters from the storyboard), and title cards between acts.

Approved milestones (one at a time, each approved before the next; branch `claude/film-assembly-phase-4`, draft PR #5 on PR #4):

| Milestone | Scope | State |
|---|---|---|
| 4.1 | `assets` stage: textures, graded photos, footage frames and map data (prep_assets, prep_footage, make_map), resumable, edits kept, map downloads only with `--download-maps` | done |
| 4.2 | `review` per edition and act: probes at each line's key word, strips of every move, checklist; `look` gate per edition, not blocking the audio stages | done |
| 4.3 | Title cards between acts of multi-act films, about 2.5 s of held silence at each act change; optional `act_titles`, localized per edition | done |
| 4.4 | Strings between clusters from explicit links only | done |
| 4.5 | Maps and routes from explicit `place` fields tied to `map.json`, localized labels | done |

Approved decisions: new features switch on only when their data is present (multi-act films, `place`, `links`), so single-act films, the starter film and the English golden outputs stay unchanged; nothing geographic or linked is inferred from the narration; no new transitions, image-aware composition or camera styles in this phase.


- `scene.py` starter generated from the storyboard: one cluster per section, items for each image and typed text, camera and spotlight keys on the key words, using the existing engine API. The agent then edits it, as the skill does today.
- Per-act scenes for long films (decision B).
- Stage `film`: probes of every line and strips of every move, saved for the look test gate.

### Phase 5: sound, render, captions

- Stage `sound`: cues, synthesised effects, an optional score (a licensed file, or a provider through the same adapter rules as voice), ducked mix at -15 LUFS.
- Stage `render`: 1080p, memory-aware workers, one file per act joined with short crossfades, then the soundtrack.
- Stage `captions`: chosen style burned in, plus SRT.

Milestones (authorized in full; branch `claude/film-finishing-phase-5`, draft PR on PR #5):

| Milestone | Scope | State |
|---|---|---|
| 5.1 | `effects@<lang>`: the effects track from every act's scene cues and the cue sheet's `synth_cues`, per act, resumable, protected | done |
| 5.2 | `render@<lang>`: each act rendered at its approved timing (after the look gate), resumable per act, verified | |
| 5.3 | `join@<lang>`: acts joined in order with short crossfades, the full mix laid over, timeline checked | |
| 5.4 | `captions@<lang>`: the chosen caption style burned in (Devanagari shaped), SRT and VTT kept | |
| 5.5 | `qc@<lang>`: the finished film checked (streams, duration, black frames, silence, clipping, subtitles, act order) and a delivery manifest; Phase 6's script and image validators and final report are not part of it | |

### Phase 6: QC and report

- Validators: script (phase 1 checks), images (every need filled, decodable, licensed), audio (duration matches timing, loudness, no clipping), video (ffprobe: 1920x1080, frame rate, duration matches the narration, audio present).
- `reports/final_report.md`: stages, warnings, the facts and their sources, image credits, voice and music provenance; `credits.md` next to the film.
- Tests for each validator, and an end-to-end CI run of a tiny documentary through every stage with a scratch voice.

## Decisions

Approved before phase 2:

- **A.** The agent researches and writes the narration; the scripts check it. No model API is called from the scripts.
- **B.** Long documentaries are built as separate acts, each on its own board.
- **C.** Archive footage is supported as optional clips inside a print frame (`Footage`).
- **D.** An editable `scene.py` starter is generated per act.

The options as they were proposed:

- **A. Who writes the research and narration.** Phase 1 assumes the agent running the skill writes them and the tools check them; no LLM API is called from the scripts. The alternative is scripts that call a model API directly with a configured key. Recommended: keep the agent as the writer (no extra key, gates stay human), and add an optional API route later only if unattended runs are wanted.
- **B. Long films on several boards.** One board for 30 minutes would be enormous to render and to review. Recommended: one board per act (or chapter), rendered separately and joined with crossfades, with a shared look and a title card between acts.
- **C. Archive footage.** The engine draws stills. Moving footage needs a new item that decodes frames with ffmpeg (memory and speed costs, and footage rights are harder). Recommended: phase 5 or later, as an opt-in `Footage` item that plays a clip inside a print frame.
- **D. Generated or hand-written scenes.** Recommended: generate a starter `scene.py` per act from the storyboard, and keep the agent's edit and the look test gate, since layout is where the films earn their quality.
