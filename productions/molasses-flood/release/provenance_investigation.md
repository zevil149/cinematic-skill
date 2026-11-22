# Provenance investigation — the two provisional images (Phase 9)

Status after this investigation: **both still provisional.** One lead strengthened, one ruled out,
nothing confirmed. No asset was substituted.

Only verifiable records were used: the full Wikimedia Commons file pages and upload histories, read
through the Commons API on 2026-11-22 (saved in `release/evidence/commons_record_*.json`), and the
Boston Daily Globe front page of 16 January 1919 on Commons. The holding institutions' own pages
(BPL / Digital Commonwealth / Flickr, City of Boston Archives / Preservica) are not reachable from
this environment.

## 1. BPL panorama (`BostonMolassesDisaster.jpg`; film needs I001, I010, I015)

**New, from the Commons page (a transcription of the BPL record, not seen at BPL):**
* File name **77103**; title "Panorama of the Molasses Disaster site"
* Creator/Contributor: **"Globe Newspaper Co. (creator)"**
* Date created 1919-01-15; genre "Photographic prints; Aerial views"
* Notes: **"Verso of print stamped Boston Globe."**
* Location: **Boston Public Library, Print Department**
* Rights: **"No known restrictions"**
* Source: Flickr, `boston_public_library/4901555337`

**Upload history:** first uploaded 2005 (from English Wikipedia), replaced by larger versions in 2007,
2010, 2014 (desaturated) and **2017 ("even more detailed view")**. The 2017 uploader names no source
for the larger scan, so the exact provenance of the pixels the film uses (the current version) is not
documented. The description text it carries ("exploded", "eight foot wave") is not used by the film.

**Check made:** if the Globe printed this photograph in 1919, that would prove publication before 1931.
The Globe's front page of 16 January 1919 (Commons `TheBostonDailyGlobe-frontpage-1919-1-16.jpg`,
4118 × 6177) carries a large photograph "General view of the explosion, looking north across North
End Park". Compared side by side (`release/evidence/panorama_vs_globe_front_1919-01-16.jpg`): **a
different photograph** (the BPL panorama looks down from the elevated railway; the Globe's front-page
view is taken lower, with a utility pole in the foreground). So this page does not prove it. The
Globe's inside pages of that day, or later issues, may — not checked (not available here).

**Reading:** a Boston Globe press print, credited to the Globe Newspaper Co., with BPL stating "No known
restrictions" — consistent with a newspaper photograph of 1919, but publication is still unproven.
**Attribution corrected** in `photos.json` (I001, I010, I015): creator Globe Newspaper Co. (per the BPL
record), Boston Public Library, Print Department, with the BPL rights statement quoted and the
provisional note kept.

**Evidence still needed (any one):** the BPL catalogue record itself showing the rights statement (and,
ideally, a public-domain mark); a Globe issue that printed this photograph (date, page); or written
permission from BPL Rights and Reproductions.

## 2. Elevated-railway photograph (City of Boston Archives 9800-018-035; film need I008)

**From the Commons page:** uploaded 2024-02-24 by Daderot "from City of Boston Archives" (Preservica
unit ca51521c-1763-4194-bd92-16a44c6a46f5), author "Boston Elevated Railway Company", date 1919-01,
template PD-US-expired; **cropped 2025-08-20** (3 % vertically, black edges removed) — the film uses
the cropped current version. **No rights statement from the Archives is transcribed** on the page.

**Reading:** nothing new about rights. A company record photograph held by a city archive; City
ownership does not make it public domain; publication before 1931 is unproven.

**Evidence still needed (any one):** the Preservica record's rights/use statement; proof of publication
before 1931 (a company report, a court exhibit later published, a newspaper); or written permission from
the City of Boston Archives.

## 3. Replacement options (prepared, NOT applied)

Only already-published 1919 material, documented on Commons:

| Need | Uses in the film | Option | Status of the option |
|---|---|---|---|
| I001, I010, I015 (panorama) | L1–2 hook, L35–36 rescue, L54 close | **Boston Daily Globe front page, 16 Jan 1919**, its front-page photograph (and headline) | PD-US (published 1919); Commons record: author "The Boston Daily Globe", source given as a Times article; 4118 × 6177; SHA-1 bc1bf017…; **not yet audited as a film asset**; halftone newspaper print, so coarser than the panorama |
| same | same | **The Boston Post's own bird's-eye photograph** (front page, 16 Jan 1919) | already in the film and cleared; part of a 1127 × 1435 scan (lower resolution) |
| I008 (railway) | L26 | **designed placeholder card** "एलिवेटेड रेल का ढाँचा" (as for the tank and the wreckage) | always available; no photograph |

Any replacement changes the visuals: it re-opens the visuals gate, then assets, scenes, look approval
and a re-render. A decision is needed before that (see the Phase 9 report).
