# Changelog

## Unreleased

- **Visual engine (documentary pipeline, phase 2).** `visuals.py` and `archives.py` find, license and fetch an image or clip for every storyboard scene across Wikimedia Commons, the Library of Congress, Openverse, Smithsonian Open Access and Europeana: licences only as the archive states them (free, needs clearing, refused), attribution recorded, polite rate limiting with cooldowns remembered across runs, resumable downloads, and designed fallback cards. Engine: `Print(move=ken_burns(...))`, `Footage` (archive clips in a print frame, via `prep_footage.py`), `Parallax`, and camera moves (`push_in`, `pull_back`, `pan`, `whip`, `reveal`, `hold`); existing items render unchanged. `scenegen.py` writes an editable `scene.py` per act (`scenekit.py`). New docpipe stages `visuals` (gate) and `scenegen`. Tests never reach the network (`CINEMATIC_OFFLINE=1`).
- **Documentary pipeline, phase 1.** `docpipe.py` runs a documentary as stages, each in its own folder, with checks, approval gates and resume: topic, research (`research.py`: sources with reliability tiers, claims tied to them, weak and unsupported claims flagged), outline (`outline.py`: 5, 10, 20 and 30 minute budgets, chronology), script (`narration.py`: every line fact-checked against the claims it cites, numbers and dates written as words, exported to `script.json`) and scenes (`storyboard.py`: timestamps, camera moves, image needs). `tests/test_docpipe.py` covers every stage and runs in CI. See `references/pipeline.md` and `docs/pipeline-plan.md`.
- `fetch_commons.py` survives Wikimedia rate limits: it retries 429 and 503 with `Retry-After` or exponential backoff, saves `photos.json` after every photo so an interrupted `get` resumes where it stopped, and writes each download through a temporary file.

## 1.0.1 (2026-11-09)

- `get_fonts.py` fetches open-licensed fonts (Bebas Neue, Homemade Apple) for text roles that Linux and Windows cannot match, so labels, stamps and handwriting keep their look. `check_setup.py` points to it.

## 1.0.0 (2026-11-09)

First release: `cinematic-film`, narrated cinematic films drawn entirely in code, on any subject.

- **Engine.** One continuous camera with motion blur and handheld drift, a spotlight, shakes and auto sound cues.
  - Items: prints and torn clippings, typeset documents, cards, big type, counters, stamps, pen marks, string, maps with region fills, routes and markers.
  - Seven looks.
- **Voice.** Scratch voice for timing, any-TTS take splitting with flagged cuts, and a narration track with a timing file.
- **Story.** Beat table with a chronology lint.
- **Images.** Wikimedia Commons fetcher that records licences and refuses non-free files; a map builder for any country; one-look grading.
- **Sound and finish.**
  - Synthesised sound effects.
  - A ducked, loudness-normalised mix.
  - A memory-aware parallel render.
  - Four caption styles and SRT.
- **Projects.** "Twelve Seconds", a 90 second documentary from seven public-domain photos, and a starter explainer.
