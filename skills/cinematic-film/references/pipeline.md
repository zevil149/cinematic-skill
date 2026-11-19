# The documentary pipeline

For documentaries of 5, 10, 20 or 30 minutes, `docpipe.py` runs the work as stages, each in its own folder, each checked before the next starts. It is the same method as the rest of this skill; the pipeline adds a research store that every line must cite, length budgets, a storyboard, and resume.

You (the agent) do the research and the writing. The tools scaffold the files, check them, and refuse to move on while a check fails. Nothing is generated that has not been researched.

## Stages

| Stage | Folder | Tool | Done when |
| --- | --- | --- | --- |
| topic | `00_topic/` | `docpipe.py new` | topic and length are set |
| research | `01_research/` | `research.py` | every claim has a source; `research.md` written |
| outline | `02_outline/` | `outline.py` | every section written, budget adds up. **Gate** |
| script | `03_script/` | `narration.py` | every line passes the fact check; `script.json` exported. **Gate** |
| scenes | `04_scenes/` | `storyboard.py` | storyboard, camera moves and image list written |

After `scenes`, carry on with the film tools as in SKILL.md (images, scratch voice, assets, scene, look test, draft, final voice, sound, finish). Later phases will add those as stages.

```bash
python3 scripts/docpipe.py new my-doc --topic "The 1919 Boston molasses flood" --minutes 10
python3 scripts/research.py add-source --project my-doc --url https://... --title "..." --publisher "..." --type archive
python3 scripts/research.py add-claim --project my-doc --text "..." --source S1 --source S2
python3 scripts/docpipe.py run --project my-doc        # writes the outline skeleton, stops at its TODOs
python3 scripts/docpipe.py approve --project my-doc outline
python3 scripts/docpipe.py run --project my-doc        # narration skeleton, then the fact check
python3 scripts/narration.py spoken --project my-doc   # numbers and dates as words
python3 scripts/docpipe.py approve --project my-doc script
python3 scripts/docpipe.py run --project my-doc        # storyboard
python3 scripts/docpipe.py status --project my-doc
```

`run` skips every stage whose inputs have not changed, so run it as often as you like; an interrupted job resumes at the first stage that is out of date. Editing a file reopens its stage and every stage after it, and an approval lapses when its stage's files change.

## Research

- One source per entry in `01_research/sources.json`: a url (with the date you read it) or, for print, a title with an author or publisher. `research.py add-source` fills the id and accessed date.
- One claim per fact the film may state, in `claims.json`, citing source ids. Put the supporting sentence in `quote` when you have it: it is what you check the line against later.
- **Tiers.** 1 is primary or institutional (archives, museums, government, universities, journals). 2 is secondary (books, reputable news, reference works). 3 is leads only (Wikipedia, wikis, social media, blogs). A tier 3 source is never enough on its own.
- **Status.** A claim with a number or date needs a tier 1 source or two independent tier 2 sources, or it is `single-source`. Mark a claim `disputed` when sources disagree; the narration must then hedge it. A claim with no valid source is `unsupported` and no line may cite it.
- Never fill a gap with a guess. If the sources do not say it, the film does not say it.

## Outline

`outline.py init` sizes the skeleton from the length: about 150 words a minute, a cold open, one bridge, chapters (5 at 5 min, 8 at 10, 14 at 20, 21 at 30), a turn and a close. 20 and 30 minute films are split into 3 or 4 acts. `outline.py plan --minutes 20` prints the budget.

Write each section's `title`, `purpose` (what the viewer learns or feels), `period` (a year, for the chronology check), `beats` and `claims`. Move time between sections freely; the total must stay within 10% of the length.

## Script

`narration.json` holds the lines: `text`, `claims`, `visual` (the direction), `hero`, `typed`, optional `images` and `gap_after`. Line ids are global and never reused. The check:

- a line cites at least one claim, unless it is `"kind": "framing"` (a line that states no fact: a question, a transition, a reflection)
- every number in the text appears in a cited claim (so "59 seconds" cannot slip in against a claim that says 12)
- a disputed claim is hedged, and weak or single-source claims are flagged for the review
- 4 to 22 words a line, a hero, a visual direction, and each section within 25% of its word budget

`narration.py spoken` writes each line's `spoken` text: "December 17th, 1903" becomes "December seventeenth, nineteen oh three", "$50,000" becomes "fifty thousand dollars". Fix names the voice will stumble on by hand. Export writes `script.json` for the film tools, with each claim and its source urls in `fact_notes`, and never replaces a `script.json` it did not write.

## Storyboard

`storyboard.py` gives every line a scene: start and end time, narration, hero and visual, typed text, the key word to time the hit on (`doc.W(line, "word")`), a suggested camera move, and the images it needs. Times are estimates until `audio/timing.json` exists; run it again after each voice. `04_scenes/image_needs.json` lists every image with a search query, for `fetch_commons.py`.

## Long films

A 20 or 30 minute film is too big for one board and one review. Build, probe and draft it one act at a time, and look at each act's draft before starting the next.
