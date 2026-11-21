# Look refinement — Hindi edition (scene work; the look is NOT approved)

Authorised by the producer after the look review (`look_review.md`, commit f7a6357). Only the act's
scene changed: `editions/hi/06_film/act_01/scene.py` now has its own `build_film` (the generated
LINES table is kept; the starter is meant to be edited, and scenegen keeps the edit). Nothing else
was changed: script, claims, research, outline, beats, storyboard, landing words, timing,
subtitles, cue sheet, mix, visuals, `photos.json` and credits are as approved.

Stills regenerated with the stage's own command (`review.py`): **57 stills, 9 strips, 0 flags**
(before: 2 near-uniform strips). Before/after pairs: `reviews/look/before_after_1.jpg`, `_2`, `_3`.

## The findings, and what was done

| # | Finding (look review) | Now |
|---|---|---|
| 1 | Designed graphics missing; typed numbers held over unrelated lines | Built, each with an on-screen Hindi tag: title card (L5, "शीर्षक · चित्रण"); two source cards (L6); 1915 with "सिटी ऑफ़ बोस्टन के विवरण के अनुसार" (L8); 50 ft scale bar (L9, "चित्रण · अनुमानित पैमाना"); City card and red thread to the Post's gallons line (L11); drips under the tank card (L13, "चित्रण · 'बताया जाता है'"); date card (L15); three cause cards revealed on their words (L16–17, the approved typed words); Hindi tags for the map's own labels (L18–19); "~35 मील/घंटा" with "अनुमान · सिटी ऑफ़ बोस्टन" (L20); wave-height comparison bars (L21–23, "चित्रण · अनुमानित पैमाना · माप नहीं"); direction cards and arrows for Copp's Hill and the harbour (L27–28, "चित्रण · अनुमानित दिशा"); 11 → 21 tally with source captions (L37–39); "यह हुआ कैसे?" with threads (L40); "शुरुआती सिद्धांत" stamp (L43, "संपादकीय चिह्न"); wall cross-section (L44–45, "चित्रण · पैमाने पर नहीं · 'दीवारें बहुत पतली' (शहर का विवरण)"); 1925 auditor card (L46, "चित्रण · शहर के विवरण के अनुसार"); "विवादित" stamp (L3, "संपादकीय चिह्न"). Each typed word now appears only with its own line. |
| 2 | Text cut at the frame edge, closing pull-back cut | Every shot is framed with the engine's safe area (10 % sides, 8 % top, 20 % bottom kept for captions) on the line's whole hero, steered clear of neighbours; sections spaced so neighbours are out of frame; typed text and stamps never placed on the newspaper; the closing shot frames the whole board inside the safe area before the narration ends. |
| 3 | Empty board mid-move (strips 02, 05) | Section changes are a wide move that keeps the last and the next hero in frame; each section's first item lands before the camera arrives. All 9 strips pass (0 near-uniform). |
| 4 | The Post small, quoted columns not brought close | Close-ups of the actual columns the narration quotes, with red pen marks drawn over (not into) the page: headline and "11 DEAD, 50 HURT" (L4), the deck's "2,300,000 Gallons" (L10) and "100 Men, Women and Children" (L24), KNOWN DEAD with George Lahey ringed (L29–30, "इंजन 31" as a label bar), UNIDENTIFIED DEAD with the Revere Rubber line underlined (L31–32), the bird's-eye photo with "NORTH END PARK PLAYGROUND" ringed (L33–34), "INTERNAL EXPLOSION WAS CAUSE, SAYS STATE CHEMIST" ringed (L41–43), "35 STATES ON DRY LAW LIST" and the headline ringed side by side (L49–50), the lead paragraph underlined (L52). |
| 5 | Same framing for repeated assets | The 7 Post copies are each framed on a different part of the page; the 3 panorama copies at different sizes and tilts. |
| 6 | Placeholders | Tank (L7, L53) and wreckage (L25) remain designed cards with "प्लेसहोल्डर · कोई सत्यापित तस्वीर नहीं" under them. No photograph was made or reused in their place. |

## Integrity of what is drawn

* Every word on screen is the script's own (typed text, phrases from the narration), a source name
  and date already in the research records, or a label from `direction.json`. No new fact.
* The newspaper is never redrawn or retyped: close-ups are camera framing of the scan; marks
  (underlines, rings) and labels sit over it, stamps beside it.
* The map: only Hindi renderings of its own printed labels (Commercial St., Charter St., North End
  Beach (playground)); no route, no flooded area, no key for its numbers 1–8 (unverified). Its label
  bar still says "चित्रण: 2005 पुनर्निर्माण, अंक असत्यापित".
* The wave-height bars compare two stated figures (the Post's 50 ft; the City of Boston's 50 ft
  tank) and show "later estimates: lower" without a number; tagged as not a measurement.

## Known limits

* **Close-up sharpness:** the Post scan is 1127 × 1435; headlines and subheads read well, body
  columns (the explosion column, the lead paragraph, the lists) are soft at 1080p. The narration
  carries their words; the pen marks show where.
* **Some close-ups crop the page edges** (a document close-up); no typed text or graphic is cut.
* **Effects are out of date.** The effects track is made from the scene's own cues (board sounds),
  so `effects@hi` is now marked out of date; the mix (`sound@hi`) uses the old effects. They were not
  re-run (audio was to be preserved); re-running them changes only the synthesised board sounds,
  not narration, music bed or loudness target. Needs your authorisation before the render.
* `docpipe.py status` still shows the look-review stage's record from its first run; the stills in
  `07_review/hi/` are the regenerated ones (`review.json` records them). Approving the look checks
  the current inputs.

## Checks and tests

review.py: 57 stills, 9 strips, 0 flags. rights.py check: ok, 12 images used, 0 not usable.
Tests: test_review, test_gates, test_scenegen, test_rights, test_editions, test_title_cards,
test_composition, test_engine_visual, test_lang_hi: all OK.
