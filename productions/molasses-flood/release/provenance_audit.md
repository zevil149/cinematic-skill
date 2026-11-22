# Copyright and provenance audit (Phase 8, Task 3)

Status: **two of the four distinct images are still provisional.** Nothing here confirms a
copyright status that was not confirmed; no permission or publication date is assumed.

Evidence used: the Commons file records read through the Commons API on 2026-11-21 (source,
author, date, licence templates, SHA-1), the downloads' source records
(`assets/photos/.I0xx.*.source.json`), `photos.json`, `05_visuals/assets.json`,
`editions/hi/out/rights.hi.json`, `reviews/visuals_review.md`. No holding institution's own page
(BPL, Flickr, City of Boston Archives) could be opened from this environment.

## The 12 uses = 4 distinct files

| Uses | File (Wikimedia Commons) | Commons record | US status | Verdict |
|---|---|---|---|---|
| I002, I004, I006, I009, I011, I012, I013 (7) | `Boston_post-January_16,_1919,.jpg` 1127×1435, SHA-1 309f2d18… | author "not specified", source "Boston Post", date 1919-01-16, template PD-US | published 16 Jan 1919 (the page itself is the publication) → public domain in the US (works published before 1931) | **cleared (US)**; scanner not stated (a faithful scan adds no copyright in the US) |
| I001, I010, I015 (3) | `BostonMolassesDisaster.jpg` 3000×2388, SHA-1 4987ef0f… | author "BPL", source Flickr `boston_public_library/4901555337`, date "Taken on 15 January 1919", template PD-US-expired | depends on **publication before 1931** (an unpublished photo of 1919 could be protected until 2039 if a work for hire, or longer if the photographer is known and died late) | **provisional** |
| I008 (1) | `…City_of_Boston_Archives_-_9800-018-035.jpg` 4112×2908, SHA-1 72c60f9a… | author "Boston Elevated Railway Company", source City of Boston Archives (Preservica unit ca51521c…), date 1919-01, template PD-US-expired | same question: a company's record photo may never have been published; if unpublished, a work for hire created 1919 is protected until the end of 2039 | **provisional** |
| I005 (1) | `Boston_molasses_detail_map.png` 874×742, SHA-1 986a96b0… | author User:IMeowbot, own work, 2005-03-21, template PD-self | released into the public domain by its author | **cleared** (illustration; content unverified, labelled so) |

Outside the US, none of the four is assessed (terms depend on each country and on unknown
photographers' dates).

## What would resolve each provisional item

**Panorama (BPL, I001/I010/I015)** — any one of:
1. The BPL catalogue record (Digital Commonwealth / BPL Flickr page 4901555337) with its rights
   statement, e.g. "No known copyright restrictions" or a public-domain mark, and the collection
   and photographer it names.
2. Evidence the photograph was **published before 1931** — a 1919 newspaper, magazine or report
   that printed it (date and page).
3. Written confirmation from BPL (Rights and Reproductions) that it may be used in a published film.
Record whichever is found as a hand-written note on the I001/I010/I015 entries in `photos.json`
(the pipeline keeps it and shows it in the credits) and in this file.

**Elevated railway (City of Boston Archives, I008)** — any one of:
1. The City of Boston Archives Preservica record (unit ca51521c-1763-4194-bd92-16a44c6a46f5, item
   9800-018-035) with its rights/use statement.
2. Evidence of **publication before 1931** (e.g. in a Boston Elevated Railway report, a court
   record exhibit later published, or a newspaper).
3. Written permission from the City of Boston Archives.
Note: City ownership of a photograph does not by itself make it public domain (only US federal
government works are public domain by origin).

## Alternatives (only if these two cannot be cleared)

Only documented sources, and only already-published 1919 material:
* **The Boston Post's own bird's-eye photograph** (on the same front page, already cleared, already in
  the film at L33–34) can stand in for the panorama in L1, L35 and L54 — lower resolution (it is a
  part of a 1127 × 1435 scan).
* **The Boston Daily Globe front page of 16 Jan 1919** — Commons candidates were found during research
  (`TheBostonDailyGlobe-frontpage-1919-1-16.jpg`, 4118 × 6177, tagged public domain; and
  `Boston_Daily_Globe_Jan._16,_1919.png`). A newspaper page published in 1919 has the same clean US
  status as the Post. **Not yet checked or downloaded**: its record and checksum would need the same
  audit before use. A third copy (`Thebostonglobe_-_Jan16_1919_newspaper.jpg`) is tagged CC BY 2.0 on
  Commons, which is doubtful for a 1919 page; avoid it.
* For I008, a designed placeholder card (as for the tank and the wreckage) is the fallback.
Replacing an image is a visuals change: it re-opens the visuals gate and needs a re-render.

## Credits found during the audit (a release issue)

The film's credits sequence (`out/credits.hi.mp4`, 24 s, joined into both films) lists **one entry
per use: 12 entries** — the Post seven times, the panorama three times — instead of four distinct
images. The same repetition is in `reports/credits.md` and `out/credits.hi.md`. The text is in
English inside a Hindi film (titles and licences "as their sources state them", by design). The
wording itself is the corrected, approved wording, with the provisional notes.
Fix (not done): credits should list each distinct file once (`credits.py` groups by use, not by
file) → re-render the credits and re-join. A pipeline change; recommended before release.
