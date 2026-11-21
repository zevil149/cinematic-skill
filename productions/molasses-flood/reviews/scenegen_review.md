# Scene starters (scenegen) — Hindi edition

`docpipe.py run --until scenegen`, 2026-11-21: **0 errors, 1 warning** ("3 of 15 visuals are
designed cards until their images arrive": I003, I014, I007, placeholders by the producer's choice).

* One act, 55 lines, 0:00.9–5:39.1 (estimated until a voice exists): `editions/hi/06_film/act_01/scene.py`,
  `06_film/acts.json`, and the root `editions/hi/scene.py` that renders it. The edition now links the
  production's `photos.json` (symlink), so the corrected credits are what it reads.
* Carried over unchanged from the approved storyboard and visuals: every line, its landing word
  (direction.json), typed text and image ids. Claim links stay in the script and storyboard (the
  scene table does not repeat them).

## Edits to the generated starter (the starter is meant to be edited; scenegen keeps them)

| Line | Need | Generated | Edited | Why |
|---|---|---|---|---|
| 7, 53 | I003, I014 | card titled "THE NORTH END MOLASSES TANK BEFORE THE DISASTER" | "शीरे का टैंक, नॉर्थ एंड (तस्वीर नहीं)" | Hindi on screen; says plainly that there is no photograph |
| 25 | I007 | card titled "WRECKAGE UNDER THE ELEVATED TRACKS, 1919" | "एलिवेटेड रेल के नीचे मलबा, 1919" | Hindi on screen |
| 18 | I005 (map) | no label | name bar "चित्रण: 2005 पुनर्निर्माण, अंक असत्यापित" | the map is a 2005 reconstruction; its numbers 1–8 have no key in the image and the Commons list (7 places for 8 numbers) does not say which is which, so no key is drawn and no place is asserted |

All 20 texts the starter draws (typed text, card titles, the map label) are in Devanagari.

## Open for the look review (after a voice exists)

1. **Designed graphics are not in the starter.** The scale bars, map overlays (flooded area, route,
   arrows), wall cross-section, tallies and stamps described in the script's visual directions are
   custom engine work. Each must carry its on-screen label from `04_scenes/direction.json` when built.
2. **The map's English labels** ("Charles River", "Commercial St.", ...) remain visible; the Hindi
   label says it is an unverified reconstruction. Framing it tighter, or a designed Hindi map, is a
   choice for the look review.
3. **Label fit**: the map label's length in the name bar is not yet seen (no render was authorised).
4. `rights.py check` for the edition runs once the voice timing exists.
