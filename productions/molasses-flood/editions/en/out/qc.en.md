# Quality control: en edition

**Complete**: 0 blocking error(s), 1 warning(s), 0 check(s) not made.

## Worth a look

- fonts: cond: system default (Inter): install one of ['DIN Condensed', 'Oswald', 'Bebas Neue'] (get_fonts.py or fonts/<role>.ttf pins a font; Devanagari always uses the bundled Noto Sans Devanagari)

## Measurements

- Loudness: -15.0 LUFS integrated (made for -15.0), true peak -2.0 dBTP
- Narration: lowest share 13.4 dB over the music and effects, aligned at +5 ms; per line in qc.json

## Every check

| Check | Result | Note |
|---|---|---|
| film | ok | film.en.mp4: 1920x1080, 30 fps, 296.99s |
| video codec | ok | h264 |
| audio stream | ok | aac |
| size | ok | 1920x1080 |
| frame rate | ok | 30 fps |
| duration | ok | 296.99s, the timeline 287.69s and 9.30s of credits |
| frames | ok | 8909 frames |
| sound and picture | ok | sound 296.99s, picture 296.97s |
| act order | ok | acts [1] |
| act renders | ok | 1 act(s) rendered |
| black frames | ok | 1 black span(s), none outside the fades or title cards |
| sound during lines | ok | sound under all 55 lines |
| narration | ok | every line's narration found in the film (lowest share 13.4 dB over the rest, aligned at +5 ms) |
| silence | ok | 1 silence(s), none outside the lead-in, pauses, title cards or tail |
| clipping | ok | true peak -2.0 dBTP |
| loudness | ok | -15.0 LUFS integrated, made for -15 (+0.0 LU) |
| subtitles srt | ok | subtitles.en.srt |
| subtitles vtt | ok | subtitles.en.vtt |
| SRT file | ok | 77 cues parsed |
| SRT cues | ok | 77 cues, times as in audio/subs.json |
| VTT file | ok | 77 cues parsed |
| VTT cues | ok | 77 cues, times as in audio/subs.json |
| subtitle sync | ok | every cue on its line |
| subtitle end | ok | the last cue ends inside the film |
| captioned film | ok | film.en.captions.mp4: 8909 frames, clean |
| captions visible | ok | a caption on screen at 3.8s |
| text fit | ok | all text fits its card (24 BigText, 13 Card, 1 Counter); text of 14 PenMark, 2 Stamp is not measured |
| fonts | warning | cond: system default (Inter): install one of ['DIN Condensed', 'Oswald', 'Bebas Neue'] (get_fonts.py or fonts/<role>.ttf pins a font; Devanagari always uses the bundled Noto Sans Devanagari) |
| empty frames | ok | no still frame of bare board outside the fades and title cards |
| caption clearance | ok | no measured text under the captions at 118 caption(s) |
| rights | ok | 8 asset(s) used, each free as stated, your own as stated, or cleared |
| credits | ok | 3 credit line(s), 9.3s at the end |
