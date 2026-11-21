# Voice stage — Hindi edition (scratch voice)

`docpipe.py run --until voice`, 2026-11-21: **0 errors, 0 warnings**. `voice.py validate`: 55 ok.

* **Provider:** espeak-ng, voice `hi`, line mode, 135 wpm setting. Free and local: no API, no
  account, no cost (3,659 characters, $0). A **scratch voice only**: robotic, not for release.
* **Segments:** 55 of 55 made, one per approved line (`audio/voice/segments/L0001.wav` …), 22.05 kHz.
  Peak at most 0.97 (no clipping), RMS 0.078–0.114 (even levels).
* **Duration:** speech 340.1 s + scripted pauses 36.6 s + lead/tail 3.9 s ≈ **6:20.6**, against the
  storyboard estimate of 5:39.1 (the estimate assumed 135 words/min; espeak reads at about 129, and
  each line is on average 11 % longer than estimated; range 0.97× (line 28) to 1.56× (line 5)).
  Longest lines: 41 and 46 (9.8 s), 24 (9.2 s).
* **Pauses:** the 10 `gap_after` pauses of the approved script are not in the segments; they are
  placed between segments by the narration stage.
* **Word timing:** none from espeak (`words` empty on every segment). The narration stage estimates
  word times when it writes `audio/timing.json`; landing words (direction.json) are matched there.
  Every word time will be an estimate, not a measurement.
* **Not yet available at this stage:** `audio/timing.json` and `narration.m4a` (narration stage),
  so the storyboard is not re-timed yet and `rights.py check` cannot run ("timing.json" missing).

## Pronunciation (espeak phonemes, `espeak-ng -v hi -q -x`, for names and loanwords)

| Word | espeak | Note |
|---|---|---|
| कॉप्स (Copp's) | k'Ops | fine |
| डब्ल्यू (W.) | d.'Vblju: | fine |
| वेजर (Wedger) | v'e:J@3r | close |
| रेवियर (Revere) | r'e:vIj,@3r | the script's spelling; English "Revere" is closer to "रिवियर" |
| लेही (Lahey) | l'e:Hi | follows the Post's spelling; usually said "लेही"/"ले-ही" |
| प्यूरिटी (Purity) | p:j'u:*It.,i | fine |
| ऑडिटर, ख़तरा, ज़िंदगियाँ | 'Od.It.,@r, x'Vtr,a:, z'i~dg,Ija~ | nukta sounds kept |

espeak's Hindi is intelligible but flat, with English-name stress and number reading that a native
speaker should check. The native-speaker review (`voice.py review --by ...`) is required before any
paid Hindi voice; it was not needed for this free scratch voice and has not been done.

## Files

The WAV segments (15 MB) are not committed (generated audio; the stage remakes them from the
script). The manifest (`audio/voice/manifest.json`: text, spoken text, request and file hashes,
durations, levels) is committed as the stage record.
