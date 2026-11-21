# Look review — Hindi edition (stills only; the look is NOT approved)

`docpipe.py run --until review`, 2026-11-21: **0 errors, 2 warnings** — strips 02 and 05 flagged
"near-uniform". Output in `07_review/hi/act_01/`: 57 stills (each line at its landing word, plus the
act's first and last frame) at 960×540, 9 camera strips, `sheet.jpg` (all stills), `review.md`
(the checklist, unticked) and `07_review/hi/review.json`. No film was rendered.
Looked at by the agent: `sheet.jpg`, the strips and the stills in `reviews/look/details.jpg`.

## What the stills show

**Layout.** One continuous evidence wall (dark board, "wall" look). Each line's hero sits roughly
centred; the board holds photos with red pins, the Post page with a torn-paper edge, designed cards,
and large typed Hindi numbers and phrases.

**Typography.** Typed text is Devanagari, light on dark, well shaped (conjuncts and nukta render:
"कमज़ोर निर्माण · तापमान · बड़ी खेप", "~35 मील/घंटा", "23,00,000 गैलन"). Card titles and the map label
are readable. The only non-Hindi words on screen are inside the archival images themselves (the Post
headline, the map's English street labels).

**Subtitles.** Not part of the review stills: the captions stage burns them in after the render
(clean style by default). Their timing and line limits were checked at the subtitles stage.

**Map (I005, line 18).** Shown as a pinned print with the red name bar
"चित्रण: 2005 पुनर्निर्माण, अंक असत्यापित"; the bar fits. No key, no pins, no route over it. Its
English labels and numbers 1–8 remain visible.

**Placeholders.** I003/I014 (tank) appear as a cream card with a red edge: "शीरे का टैंक, नॉर्थ एंड
(तस्वीर नहीं)"; I007 as "एलिवेटेड रेल के नीचे मलबा, 1919". They read clearly as cards, not photos.

**Transitions.** Whip moves between sections with motion blur (strips 01–09). Two of them (strips 02
and 05, the flagged ones) pass through several frames of empty board: about 0.6–1 s with nothing in
frame between "11 मृत" and the tank card (39.4–40.3 s), and between "इंजन 31" and the Post page
(197.8–199.7 s).

## Problems found (for your decision)

1. **Designed graphics are missing.** The starter draws photos, cards and typed text only. The
   script's visual directions — scale bars, map overlays, the wall cross-section, the tally from 11
   to 21, source cards, stamps ("विवादित", "शुरुआती सिद्धांत"), the evidence-wall thread — are not
   built. Many lines therefore show only a typed number held over several lines: "11 मृत" over lines
   4–6, "~35 मील/घंटा" over 20–23 (including the wave-height dispute lines 21–23), "इंजन 31" over
   29–32, "35" over 49–51. The title-card and source-card lines (5, 6) show "11 मृत".
2. **Text cut at the frame edge.** "कमज़ोर नि…" (line 17's typed text) is cut at the right edge in
   lines 26–28; "बड़ी खेप" at the left in 18–19; "50 फ़ुट?" half off the top in line 3 (faded);
   items half outside the frame in the closing pull-back (`probe_close`).
3. **Empty frames mid-move** in strips 02 and 05 (above).
4. **The Post page is small** in most stills (about a third of the frame height); its headline is
   readable but the columns the narration quotes (the explosion-theory column, the list of the dead,
   the Prohibition column) are not brought close or highlighted.
5. **Repetition.** The same Post page appears for 7 needs with the same framing; the panorama for 3.

Items 1, 3 and 4 need scene work in `06_film/act_01/scene.py` (the starter is meant to be edited);
item 2 needs repositioning there. None changes the approved script, timing or visuals.

## Checks and tests

* review stage: 0 errors, 2 warnings (strips 02, 05 near-uniform).
* test_review, test_gates, test_editions: all OK.
* The render, join, captions, QC and report stages wait for `approve look --lang hi`.

## Files committed

`07_review/hi/review.json`, `07_review/hi/act_01/review.md`, `sheet.jpg`, `strip_01–09.jpg`,
`reviews/look/details.jpg`, `reviews/look/strips_and_close.jpg`, this note. The 57 PNG stills
(37 MB) are ignored; the review stage rebuilds them.
