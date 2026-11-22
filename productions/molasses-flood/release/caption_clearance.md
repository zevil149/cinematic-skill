# Closing caption clearance (Phase 8, Task 2)

Status: **proposal only.** The scene, the film and the captions are unchanged; the fix exists as an
unapplied diff (`release/proposed_closing_fix.diff`). Measured without rendering, with the same
check QC uses (`layoutcheck.collisions` against the burned captions), on temporary copies of the scene.

## What happens now

* Last narration line (55, "शीरे की यह लहर याद दिलाती है कि … उसकी जाँच कितनी ज़रूरी है।"):
  344.80–353.02 s. Its two caption cues: **344.804–350.692** ("…जिस ढाँचे पर शहर भरोसा करता है,")
  and **350.772–352.992** ("उसकी जाँच कितनी ज़रूरी है।"). Wording and times are as approved.
* Closing camera (from `scene.py`): 345.10 s on the last hero (zoom 0.556) → 348.50 s mid-move
  (zoom 0.150) → **352.42 s whole board (zoom 0.0575)** → 356.02 s slight hold-out (0.0558).
* At 352.42 s the board fills **12–88 % of the frame width and 7–93 % of its height**. The
  caption band (the bottom 20 %, kept clear everywhere else in the film) starts at 80 %, so the
  board's bottom row sits under both captions.
* QC: 7 collisions — at 349.5 s the 1925 card (89 %), "मालिकों की लापरवाही", "लापरवाही", the SEC09 line
  "पतली दीवारें · लापरवाही (ऑडिटर…", "21"; at 352.0 s "लापरवाही" and "21" (100 % each).
* Cause: the motion-check change (`9082f27`) let the final frame use the caption band on the
  assumption that the captions were over; the last caption runs until 352.99 s.

## Proposed fix (smallest found)

Two lines of the closing camera, nothing else:
1. The whole-board frame keeps the caption band clear (height fit in 72 % instead of 86 %, the board
   shifted up by the band).
2. The mid-move key (348.5 s) is shifted up the same way.

No change to narration, caption wording or timing, items, visuals, soundtrack or any other shot.

| | Current | Proposed |
|---|---|---|
| Whole-board frame at 352.42 s | zoom 0.0575, board x 12–88 %, y 7–93 % | zoom 0.0482, board x 18–82 %, **y 8–80 %** |
| Final frame at 356.02 s | zoom 0.0558, y 8–92 % | zoom 0.0467, y 9–79 % |
| Mid-move key at 348.5 s | (27948, 21579), zoom 0.150 | (27948, 23788), zoom 0.150 |
| QC caption collisions | **7** | **1**: "21" at 349.5 s, 60 % under the caption, while the camera is still moving |
| Board size on screen | — | 16 % smaller (0.0482 / 0.0575) |

A first variant (only the final frame) left 2 collisions; the mid-move adjustment removes one more.
The remaining one is a transient during the move. If it must go too, the next smallest change is to
fade the line-54 "21" as the pull-back starts (a visual change, not proposed here).

## What applying it would take (not done)

Apply the diff → `docpipe.py run --lang hi --until review` (the look approval lapses because the
scene changed; the effects stage takes the scene as input, so effects and sound re-run too —
only the synthesised board/camera sounds can move, narration, music and loudness target do not)
→ look re-approval → render (~70 min) → join → captions → QC → report. The current
films stay as backups (`editions/hi/out/release_backup/`). If the release voice (Task 1) is done
first, do this in the same re-render.
