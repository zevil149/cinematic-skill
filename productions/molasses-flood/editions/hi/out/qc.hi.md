# Quality control: hi edition

**Complete**: 0 blocking error(s), 2 warning(s), 0 check(s) not made.

## Worth a look

- fonts: cond: system default (Inter): install one of ['DIN Condensed', 'Oswald', 'Bebas Neue'] (get_fonts.py or fonts/<role>.ttf pins a font; Devanagari always uses the bundled Noto Sans Devanagari)
- caption clearance: Card 'अदालत द्वारा नियुक्त ऑडिटर' at 349.5s, 89% under the caption; Card 'मालिकों की लापरवाही' at 349.5s, 100% under the caption; BigText 'लापरवाही' at 349.5s, 100% under the caption; BigText 'पतली दीवारें · लापरवाही (ऑडिटर' at 349.5s, 100% under the caption; BigText '21' at 349.5s, 100% under the caption; BigText 'लापरवाही' at 352.0s, 100% under the caption and 1 more

## Measurements

- Loudness: -15.0 LUFS integrated (made for -15.0), true peak -1.2 dBTP
- Narration: lowest share 12.5 dB over the music and effects, aligned at +5 ms; per line in qc.json

## Every check

| Check | Result | Note |
|---|---|---|
| film | ok | film.hi.mp4: 1920x1080, 30 fps, 380.02s |
| video codec | ok | h264 |
| audio stream | ok | aac |
| size | ok | 1920x1080 |
| frame rate | ok | 30 fps |
| duration | ok | 380.02s, the timeline 356.02s and 24.00s of credits |
| frames | ok | 11400 frames |
| sound and picture | ok | sound 380.02s, picture 380.00s |
| act order | ok | acts [1] |
| act renders | ok | 1 act(s) rendered |
| black frames | ok | 1 black span(s), none outside the fades or title cards |
| sound during lines | ok | sound under all 55 lines |
| narration | ok | every line's narration found in the film (lowest share 12.5 dB over the rest, aligned at +5 ms) |
| silence | ok | 1 silence(s), none outside the lead-in, pauses, title cards or tail |
| clipping | ok | true peak -1.2 dBTP |
| loudness | ok | -15.0 LUFS integrated, made for -15 (+0.0 LU) |
| subtitles srt | ok | subtitles.hi.srt |
| subtitles vtt | ok | subtitles.hi.vtt |
| SRT file | ok | 74 cues parsed |
| SRT cues | ok | 74 cues, times as in audio/subs.json |
| VTT file | ok | 74 cues parsed |
| VTT cues | ok | 74 cues, times as in audio/subs.json |
| subtitle sync | ok | every cue on its line |
| subtitle end | ok | the last cue ends inside the film |
| captioned film | ok | film.hi.captions.mp4: 11400 frames, clean |
| captions visible | ok | a caption on screen at 4.2s |
| text fit | ok | all text fits its card (24 BigText, 12 Card, 1 Counter); text of 11 PenMark, 2 Stamp is not measured |
| fonts | warning | cond: system default (Inter): install one of ['DIN Condensed', 'Oswald', 'Bebas Neue'] (get_fonts.py or fonts/<role>.ttf pins a font; Devanagari always uses the bundled Noto Sans Devanagari) |
| empty frames | ok | no still frame of bare board outside the fades and title cards |
| caption clearance | warning | Card 'अदालत द्वारा नियुक्त ऑडिटर' at 349.5s, 89% under the caption; Card 'मालिकों की लापरवाही' at 349.5s, 100% under the caption; BigText 'लापरवाही' at 349.5s, 100% under the caption; BigText 'पतली दीवारें · लापरवाही (ऑडिटर' at 349.5s, 100% under the caption; BigText '21' at 349.5s, 100% under the caption; BigText 'लापरवाही' at 352.0s, 100% under the caption and 1 more |
| rights | ok | 12 asset(s) used, each free as stated, your own as stated, or cleared |
| credits | ok | 13 credit line(s), 24.0s at the end |
