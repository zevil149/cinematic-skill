# Visuals review — The Great Molasses Flood (Hindi)

Prepared for the producer before the **visuals** gate (not approved). Every choice below is a
**proposal by the agent**, written into `05_visuals/selection.json`. Because they are explicit
selections, the pipeline does not count them as "automatic picks", so its acknowledgement check
will not stop the gate: **only your review does**.

Searched: Wikimedia Commons and the Library of Congress (the two archives this environment can
reach), 2026-11-21. Openverse could not be reached; Smithsonian and Europeana need API keys and
were skipped. Commons file records (source, author, date, licence templates, permission,
description, checksum) were read through the Commons API for every candidate considered. No other
site (Flickr, the City of Boston Archives, BPL, the Bostonian Society) could be opened to confirm
a record at its origin.

## Licence basis, and its limits

* **US public domain for works published before 1931.** Commons tags the photographs
  `PD-US-expired` or `PD-US`. That holds if each photograph was *published* before 1931. A
  photograph that stayed unpublished in a corporate archive could still be under copyright
  (120 years from creation for works made for hire, so to 2039 for 1919). The Commons records
  do not show publication, and this session could not check it at the holding institution.
  **Status: PD as Commons states it; publication not independently verified.**
* **The Boston Post front page** was published on 16 January 1919, so it is public domain in the
  US without that doubt; a faithful scan of it adds no new copyright.
* **The detail map** was drawn in 2005 by a Commons user and released by its author into the
  public domain (`PD-self`).
* Public domain outside the US is not assessed (it depends on each country's term and on the
  unknown photographers' dates).

## Selections (proposed)

| Need | Used in | Selection | Original source per Commons | Licence (Commons) | Verdict |
|---|---|---|---|---|---|
| I002, I004, I006, I009, I011, I012, I013 | hook, gallons, victims, rescue, explosion theory, Prohibition, close | `Boston_post-January_16,_1919,.jpg` (1127×1435) | The Boston Post, 16 Jan 1919, front page; scanner not stated | PD-US | **Selected, all seven the same file.** Checksum equals the scan read for the research (S1). Published 1919: PD in the US. Low resolution for full-screen close-ups of small type. |
| I001, I010, I015 | opening, rescue, close | `BostonMolassesDisaster.jpg` (3000×2388; 1920 px used) | Boston Public Library, Flickr 4901555337, "Panorama of the Molasses Disaster site", taken 15 Jan 1919 | PD-US-expired | **Selected, all three the same file.** Institutional source. Publication before 1931 not verified (Flickr not reachable). Its Commons description says "an eight foot wave" and "exploded": those words are **not** used by the film. |
| I008 | elevated railway (SEC05) | `…City_of_Boston_Archives_-_9800-018-035.jpg` (4112×2908; 1920 px used) | City of Boston Archives (Preservica), Boston Elevated Railway Company, Jan 1919 | PD-US-expired | **Selected.** Institutional source; clearest view of the damaged structure among six from the same series. Publication before 1931 not verified (archive not reachable); company documentation photos may never have been published. |
| I005 | the wave's path (SEC04) | `Boston_molasses_detail_map.png` (874×742) | Drawn 2005 by User:IMeowbot from 1895 and 1915 City of Boston maps, "published accounts" and photos | PD-self | **Selected as an illustration only.** A modern reconstruction, not a 1919 map; its placements are the author's, not verified here. Its labels are in English. Line 18 already carries the on-screen label "चित्रण · अनुमानित क्षेत्र". |
| I003, I014 | the tank (SEC03, close) | **fallback card** | — | — | **Not selected; your decision.** See below. |
| I007 | wreckage (SEC05) | **fallback card** | — | — | **Not selected.** See below. |

Repeated needs are consistent: every Post need names the same Commons file, and every panorama
need the same file. The pipeline still downloads one copy per need (7 + 3 copies); the copies made
so far are byte-identical.

**Downloads still owed:** I011, I012, I013 (the Post page again). upload.wikimedia.org rate-limited
us; after three polite retries (each after its cooldown) they are deferred, and the next
`docpipe.py run` retries them. Until then those three show as designed cards. Nothing about their
selection is open: they name the same file as the other four Post needs.

## Rejected candidates

| Candidate | Offered for | Why rejected |
|---|---|---|
| `North_End_molasses_tank.jpg` (417×327) | I003, I014 | Credited to "The Bostonian Society", but taken from a student website (acornsandmolasses.weebly.com), not the Society; date "before 1919"; publication unknown. Provenance and PD basis unverifiable here, and 417 px wide is too small for 1080p. **It is the only photo of the tank found.** To use it: set I003 and I014 to `commons:File:North_End_molasses_tank.jpg` in selection.json, ideally after confirming it with the Society (now Revolutionary Spaces). |
| `GreatMolassesFlood_1919-Wreckage_under_the_elevated_tracks.jpg` | I007, I008 | Author unknown; source a radio station's web page (WBUR), not an archive; the image looks colourised (tinted). Not authentic as presented. |
| `Boston_1919_molasses_disaster_-_el_train_structure.jpg` (1024×767) | I008 | Author unknown; source a Wired article; low resolution. A better-sourced view (City of Boston Archives) was available. |
| `Boston_molasses_area_map.png` (534×462) | I005 | No author, source or date; contradictory licence tags (PD-USGov-USGS and PD-self). |
| Five other City of Boston Archives views (9800-018-023, -031, -051, -052, -054) | I008 | Same provenance as the selection; not chosen only on content. **-031** (wreckage and a streetcar under the elevated) would suit I007, but the pipeline only offers it for I008. |
| `Boston_Post_logo.png`, a 1919 motor-truck photo | I002 … | Not the newspaper page. |
| LoC results (Hawaiian sugar mills, books) | I003, I005, I007 | Unrelated to the subject; most also "no licence stated". |
| Flickr book-scan results ("Programme (1919)", etc.) | I002 … | Unrelated; licence not recognised (refused by policy). |

No AI-generated, paid or restricted media was considered.

## Producer decisions (2026-11-21)

| # | Decision | Done |
|---|---|---|
| 1 | Tank (I003, I014): keep the designed placeholder cards; the 417 px student-site photo is not used | `selection.json`: `fallback` |
| 2 | Wreckage (I007): keep the placeholder; the script gate is not reopened | `selection.json`: `fallback` |
| 3 | BPL panorama (I001, I010, I015) and City Archives elevated-railway photo (I008): **provisional** | kept, with the publication-date doubt written into their licence line and attribution (below) |
| 4 | 2005 map (I005): keep, as an illustrative reconstruction | kept; credit corrected; on-screen label "चित्रण · अनुमानित क्षेत्र" (direction.json, line 18) |
| 5 | Boston Post: one image across all seven needs | all seven name `Boston_post-January_16,_1919,.jpg`; the four downloaded copies are byte-identical |
| 6 | Credits: the Post as "The Boston Post, 16 January 1919"; the map as a 2005 reconstruction | done (below) |

## Credits as the film will show them

Corrected through the pipeline's own mechanism: an entry written by hand in the production's
`photos.json` (no `generated_by`) wins over the downloaded record, and the rights stage judges it
by the licence it states. Each corrected entry carries `written_by` and a `provenance` note. The
credit lines below are what `rights.py` and `credits.py` produce from them (verified):

| Need | Credit line |
|---|---|
| I002, I004, I006, I009, I011, I012 | Boston Post front page, January 16, 1919 · The Boston Post, 16 January 1919 · Public domain in the US (published 1919) |
| I001, I010, I015 | Panorama of the molasses disaster site, January 15, 1919 (BPL) · Boston Public Library · Public domain (US; publication before 1931 assumed by Wikimedia Commons, not verified) |
| I008 | Boston Elevated Railway structure after the molasses flood, January 1919 · Boston Elevated Railway Company; City of Boston Archives · Public domain (US; publication before 1931 assumed by Wikimedia Commons, not verified) |
| I005 | Map of the molasses flood area, North End · 2005 reconstruction by Wikimedia Commons user IMeowbot, after 1895 and 1915 City of Boston maps · Public domain (released by its author) |

`05_visuals/credits.md` now says the same: for a download shadowed by a hand-written entry, the
visuals stage writes that entry's attribution (marked "as written in photos.json"), including the
provisional wording for the panorama and the elevated-railway photo. (visuals.py change, with a
test, 2026-11-21; before it, credits.md kept the uncorrected Commons wording.)

The visuals stage warns once for each corrected entry ("an entry I0xx you wrote; yours is used and
the download is not"). That is expected: each entry points at the same downloaded file and only
replaces its credit and licence wording.

## Verification (2026-11-21)

* Files at full Commons size (the Post page, the map) match their Commons SHA-1 checksums; the
  Post copies also match the scan read for the research (S1).
* Files over 1920 px (panorama, elevated railway) are Commons' own 1920 px renders, by the
  pipeline's design (all a 1080p film can show), so their checksums differ from the originals.
  The three panorama copies are byte-identical.
* Each download has a source record naming its Commons candidate and licence.

## Unresolved risks and blockers

1. **I013 not downloaded.** At the single retry at 16:00 UTC (after the 12:48 cooldown), I011 and
   I012 downloaded; their SHA-1 matches the Commons file and the other Post copies, their source
   records name the same Commons file, and they now have the same corrected credit entry as I002
   in `photos.json`. I013 was rate-limited again (cooling down until 16:15 UTC); per your
   instruction, retrying stopped. Until a later run fetches it, its scene (SEC09, the close) shows
   a designed card; when it arrives it needs the same credit entry. It is not pre-entered: an entry
   naming a file that does not exist yet would break the later assets stage.
2. **Copyright of the panorama and the elevated-railway photo is provisional.** Public domain in
   the US depends on publication before 1931, not verified at BPL or the City of Boston Archives.
   If either was unpublished until recently, its US term could run to 2039. Confirm before
   public release, or replace with designed cards.
3. **Outside the US**, public-domain status of all four images is not assessed.
4. **The map** is a modern reconstruction with English labels in a Hindi film; its placements are
   the mapmaker's, unverified.
5. **Resolution.** The Post scan (1127 × 1435) is soft for full-frame close-ups of small type.
6. **Three placeholders by choice** (tank × 2, wreckage) mean SEC03 has no photograph of the tank.

## What approval would mean

Approving the visuals gate accepts the selections above, including the provisional two, and the
fallback cards. The next stages (assets, scene starters, then voice) would follow. To approve,
when you are satisfied: `docpipe.py approve --project productions/molasses-flood visuals`.

## Checks run (16:00 UTC)

* visuals: 0 errors, 13 warnings (1 deferred: I013; 3 fallbacks by choice; 9 hand-written credit entries in use).
* rights, per asset: all 11 downloaded needs usable, with the corrected credit lines; I013 not usable until downloaded.
* `rights.py check` for the edition cannot run yet: it reads what the built scenes use, which needs the voice timing
  (a later stage). It runs again before rendering, where it blocks any unusable asset.
