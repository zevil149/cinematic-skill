# Phase 9 — Controlled release preparation (Hindi, The Great Molasses Flood)

Release readiness: **NOT READY.** Two blockers remain open (release voice; rights of two images);
two are fixed in the sources and wait for a re-render (closing captions; credits).

## Changes made (commit 3509074)

| # | Change | Files | Reversible by |
|---|---|---|---|
| 1 | Closing camera keeps the caption band clear (the Phase 8 diff, applied as is) | `editions/hi/06_film/act_01/scene.py` | `git apply -R release/proposed_closing_fix.diff` |
| 2 | Credits list each distinct asset once, in first-use order, with full attribution | `skills/cinematic-film/scripts/credits.py` (on-screen roll), `report.py` (credits.md); new `tests/test_credits_dedupe.py` | reverting the two hunks |
| 3 | Panorama attribution corrected to the BPL record (as transcribed on Commons): creator Globe Newspaper Co.; BPL Print Department; "No known restrictions" quoted; provisional note kept | `photos.json` (I001, I010, I015) | previous entries in git history |
| 4 | Six-line narration sample workspace (script sheet, recording spec, read-only checker); recordings kept out of git | `release/narration_samples/`, `.gitignore` | delete the folder |
| 5 | Provenance investigation, evidence and replacement options (not applied) | `release/provenance_investigation.md`, `release/evidence/` | — |

Not changed: the finished films, their backups, the credits video, subtitles, narration, timing, mix,
effects, visuals selections, script and claims. **10/10 checksums verified** (`editions/hi/out/release_backup/SHA256SUMS`).

## Effect of the changes (measured, not rendered)

* **Captions:** QC's own geometry check on the patched scene: caption collisions **7 → 1** ("21" at
  349.5 s, 60 %, during the camera move); final frame board at 8–80 % of the height (clear of the
  caption band), 16 % smaller; no text overflow, no empty holds.
* **Credits:** this film's roll would go from **13 lines to 5** (4 images + narration): the panorama
  (now "Globe Newspaper Co. … Boston Public Library, Print Department", provisional wording), the Boston
  Post, the 2005 map, the railway photo (provisional wording), and the narration.

## Stale stages (`docpipe.py status` with the absolute project path)

| Stage | Status | Why |
|---|---|---|
| assets | out of date | `photos.json` changed (credit text only; no image changed) |
| effects@hi | out of date | the scene changed |
| review@hi [look gate] | **out of date: the look approval has lapsed** | the scene changed |
| render@hi | out of date | scene, credits code |
| qc@hi, report | out of date | upstream changes, `report.py` |
| sound, join, captions | show "done" | they follow once their inputs are rebuilt |

Nothing was re-run: no render, no audio regenerated. Note: always pass the **absolute** project path
to `docpipe.py` (a relative path makes `assets` look stale and triggers the render path bug).

## Tests

test_credits_dedupe, test_rights, test_report, test_visuals_credits, test_composition, test_scenegen,
test_review, test_gates, test_qc, test_voice, test_storyboard_direction: **all OK**.

## Rights findings

* **Panorama:** a Boston Globe press print (BPL record via Commons: creator Globe Newspaper Co., verso
  stamped Boston Globe, Print Department, "No known restrictions"). The Globe's 16 Jan 1919 front page
  prints a **different** photograph, so it does not prove publication. The current Commons file is a
  2017 larger scan whose source is not stated. **Still provisional.**
* **Railway photo:** no rights statement in the Commons record; nothing new. **Still provisional.**
* **Replacement options prepared, not applied:** Globe 16 Jan 1919 front-page photograph (published
  1919; not yet audited as an asset) or the Post's bird's-eye photo for the panorama; a designed
  placeholder for the railway photo.

## Decision required

1. **Rights:** request the BPL and City of Boston Archives records/permission, **or** authorise the
   replacements (re-opens the visuals gate).
2. **Narration:** record the six sample lines in `release/narration_samples/incoming/` and run the
   checker; then decide on the full recording.
3. Then authorise **one** combined re-run: (new visuals if chosen) → assets → narration (if new voice)
   → effects → sound → subtitles → look review and **re-approval** → render → join → captions → QC → report.
