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

## Credits that need a hand correction

`05_visuals/credits.md` is generated from Commons. Two lines read badly:
* the Post: "by not specified" — should credit **The Boston Post, 16 January 1919**;
* the map: credit is "User:IMeowbot" — suitable, but say it is a 2005 reconstruction.

## Decisions for you

1. **The tank photo (I003, I014):** keep the designed card, or accept the weakly sourced,
   low-resolution photo with its caveats.
2. **Wreckage (I007):** keep the card, or let the script's image need be changed later (a script
   change re-opens the script gate) so City of Boston Archives -031 can be used.
3. **Publication basis of the BPL panorama and the City of Boston Archives photo:** accept
   Commons' PD-US-expired, or confirm with the institutions first.
4. **The map:** accept a labelled 2005 reconstruction with English labels, or use a designed map.
5. **Credits:** correct the two lines above before the credits are made.
6. Then, if you agree: `docpipe.py approve --project productions/molasses-flood visuals`.
