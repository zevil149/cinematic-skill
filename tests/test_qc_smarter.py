"""Tests for milestone 6.2: smarter quality control.

  * narration found by comparing audio/narration.m4a with the film's sound, line by line, over
    the voice's own speech frames: a voice missing under music (the audit's blind spot, where the
    old loudness test passed), a voice buried in the music, a line mixed much quieter than the
    others, and a line simply spoken quietly (which must not be flagged)
  * the film's integrated loudness measured against the mix's target
  * SRT and VTT parsed as cues, so a subtitle line that is only a number is text, not a cue count
  * text wider than its card, and measured text under the burned captions, from the scene geometry
  * checks that cannot be made are listed as not checked, never passed

Offline, on the tiny two-act fixture with a speech-like stand-in voice. Needs skia-python, numpy
and ffmpeg (the parser tests need nothing).
"""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402
import subtitles  # noqa: E402

try:
    import numpy as np
    import skia  # noqa: F401
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SIZE = "160x90"
QUIET = dict(log=lambda *a: None)


def finished(base, voice=None, captions=False, **kw):
    import finish
    import finish_fixture as F
    proj = F.make(base, voice=voice, **kw)
    assert subtitles.build(proj, log=lambda *a: None).ok
    assert finish.render_acts(proj, SIZE, 2, **QUIET).ok
    assert finish.join(proj, **QUIET).ok
    if not captions:
        L.save(proj / "captions.json", {"enabled": False})
    assert finish.captions(proj, **QUIET).ok
    return proj


def check(rep, name):
    return next((c for c in rep["checks"] if c["check"] == name), None)


class Parsing(unittest.TestCase):
    def test_numbers_in_the_text_are_text(self):
        cues = [{"n": 1, "t0": 1.0, "t1": 2.5, "lines": ["The year was", "1903"]},
                {"n": 2, "t0": 3.0, "t1": 4.25, "lines": ["12"]},
                {"n": 3, "t0": 3600 + 61.5, "t1": 3600 + 62.0, "lines": ["after an hour"]}]
        got, probs = subtitles.parse_srt(subtitles.to_srt(cues))
        self.assertEqual(probs, [])
        self.assertEqual([(c["n"], c["t0"], c["t1"], c["lines"]) for c in got],
                         [(1, 1.0, 2.5, ["The year was", "1903"]), (2, 3.0, 4.25, ["12"]), (3, 3661.5, 3662.0, ["after an hour"])])
        crlf = "﻿" + subtitles.to_srt(cues).replace("\n", "\r\n")                       # Windows line ends and a BOM
        self.assertEqual(len(subtitles.parse_srt(crlf)[0]), 3)

    def test_malformed_srt_is_reported_block_by_block(self):
        bad = ("1\n00:00:01,000 --> 00:00:02,000\nfine\n\n"
               "2\n00:00:03,000 --> 00:00:02,500\nbackwards\n\n"
               "3\nno timing here\n\n"
               "x\n00:00:05,000 --> 00:00:06,000\nbad number\n\n"
               "5\n00:00:07,000 --> 00:00:08,000\n")
        got, probs = subtitles.parse_srt(bad)
        self.assertEqual(len(got), 4)
        self.assertTrue(any("block 2: ends at or before it starts" in p for p in probs))
        self.assertTrue(any("block 3: no timing line" in p for p in probs))
        self.assertTrue(any("block 4: the line before the timing is not a cue number" in p for p in probs))
        self.assertTrue(any("block 5: no text" in p for p in probs))

    def test_vtt_with_its_header_notes_and_ids(self):
        cues = [{"n": 1, "line": 3, "t0": 0.5, "t1": 1.5, "lines": ["1903"], "timing": "voice", "cps": 5}]
        got, probs = subtitles.parse_vtt(subtitles.to_vtt(cues, "en", {"voice": 1}))
        self.assertEqual(probs, []); self.assertEqual((got[0]["id"], got[0]["lines"]), ("L3-1", ["1903"]))
        self.assertIn("does not start with WEBVTT", subtitles.parse_vtt("00:00:01.000 --> 00:00:02.000\nhi\n")[1][0])


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Narration(unittest.TestCase):
    def test_a_voice_missing_under_music_is_found(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, voice={"drop": (3,), "bed_db": -32.0})
            r = qc.build(proj, **QUIET)
            rep = L.load(proj / "out" / "qc.en.json")
            self.assertTrue(check(rep, "sound during lines")["ok"])                          # the old test hears the music and passes
            self.assertFalse(r.ok)
            self.assertTrue(any(e.startswith("narration: line(s) 3:") for e in r.errors), r.errors)
            lines = {x["line"]: x for x in rep["measurements"]["narration"]["lines"]}
            self.assertLess(lines[3]["nrr_db"], -10)
            self.assertTrue(all(lines[i]["nrr_db"] > 3 for i in (1, 2, 4)), lines)
            self.assertFalse(L.load(proj / "out" / "delivery.en.json")["complete"])

    def test_buried_and_quiet_lines_warn_and_quiet_speech_does_not(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(pathlib.Path(tmp) / "a", voice={"bed_db": -50.0, "line_level": {2: -14.0}})
            r = qc.build(proj, **QUIET)                                                        # line 2 spoken softly, mixed as spoken
            self.assertTrue(r.ok, r.errors); self.assertEqual([w for w in r.warnings if not w.startswith("fonts:")], [])
            m = L.load(proj / "out" / "qc.en.json")["measurements"]["narration"]
            self.assertLess(abs(m["lag_ms"]), 30)
            proj = finished(pathlib.Path(tmp) / "b", voice={"bed_db": -40.0, "line_gain": {2: -18.0}, "bed_boost": {4: 22.0}})
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)                                                    # warnings, not errors
            self.assertTrue(any(w.startswith("narration level: line(s) 2") for w in r.warnings), r.warnings)
            mask = next(w for w in r.warnings if w.startswith("narration masking:"))
            self.assertRegex(mask, r"\b4 \(-\d+\.\d dB\)")                                 # the bed swells under line 4

    def test_without_a_narration_track_it_says_so(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp)                                                               # the tone as the mix, no narration.m4a
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            rep = L.load(proj / "out" / "qc.en.json")
            self.assertIsNone(check(rep, "narration")["ok"])
            self.assertIn("narration", rep["not_checked"]); self.assertIn("loudness", rep["not_checked"])
            self.assertIn("caption clearance", rep["not_checked"])                             # captions are off here
            self.assertIn("## Not checked", (proj / "out" / "qc.en.md").read_text())


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Loudness(unittest.TestCase):
    def test_the_film_is_measured_against_the_mix_target(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp, voice={})
            rep_f = proj / "audio" / "mix_report.json"
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            lo = L.load(proj / "out" / "qc.en.json")["measurements"]["loudness"]
            self.assertAlmostEqual(lo["integrated_lufs"], lo["target_lufs"], delta=1.0)
            target = lo["target_lufs"]
            L.save(rep_f, {**L.load(rep_f), "target_lufs": target + 1.5})
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok); self.assertTrue(any(w.startswith("loudness drift") for w in r.warnings), r.warnings)
            L.save(rep_f, {**L.load(rep_f), "target_lufs": target + 5})
            r = qc.build(proj, **QUIET)
            self.assertTrue(any(e.startswith("loudness: the film measures") for e in r.errors), r.errors)


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class SubtitleFiles(unittest.TestCase):
    def test_a_numbered_line_is_not_a_cue_and_a_broken_file_blocks(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = finished(tmp)
            subs_f, srt = proj / "audio" / "subs.json", proj / "out" / "subtitles.en.srt"
            subs = L.load(subs_f)
            subs["cues"][0]["lines"] = ["The year", "1903"]                                  # the old count read "1903" as a cue
            data = subtitles.to_srt(subs["cues"]).encode()
            srt.write_bytes(data)
            subs["files"]["out/subtitles.en.srt"] = subtitles.sha_bytes(data)
            L.save(subs_f, subs)
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertTrue(check(L.load(proj / "out" / "qc.en.json"), "SRT cues")["ok"])
            srt.write_text(srt.read_text().replace("00:00:", "00-00-", 1))                   # a cue loses its timing
            r = qc.build(proj, **QUIET)
            self.assertTrue(any(e.startswith("SRT file: subtitles.en.srt is malformed") for e in r.errors), r.errors)


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Layout(unittest.TestCase):
    def test_overflow_and_caption_collisions_from_geometry(self):
        import engine as E
        import layoutcheck as LC
        from captions import Captions
        f = E.Film(8, look="wall")
        # beyond what fitting (6.3: wrap, then down to 55%) can do: one endless word, and fourteen lines
        f.add(E.Card(0, -3000, 2700, 1650, 0.0, title="ATITLEOFONEWORDFARTOOLONGFORANYCARDATALL", lines=["short"]))
        f.add(E.Card(5000, -3000, 2700, 1650, 0.0, title="FITS", lines=[f"line {i}" for i in range(14)]))
        f.add(E.Card(9000, -3000, 2700, 1650, 0.0, title="FITS", lines=["fine"]))
        low = f.add(E.Parallax(E.BigText("UNDER THE CAPTION", 0, 1800, 260, 0.0, grunge=False), depth=1.08))
        f.add(E.BigText("ABOVE IT", 0, -200, 260, 0.0, grunge=False))
        f.cam(0, 0, 0, 0.5); f.cam(8, 0, 0, 0.5)
        res = E.Res(960 / 3840.0)
        over = LC.overflows(f, res)
        self.assertEqual(sorted((o["text"][:6], o["what"]) for o in over),
                         [("ATITLE", "title wider than the card"), ("FITS", "text runs below the card")])
        boxes = {text: b for _, text, b in LC.screen_text(f, res, 4.0, 960, 540)}
        self.assertGreater(boxes["UNDER THE CAPTION"][3], 470); self.assertLess(boxes["ABOVE IT"][3], 300)
        timing = {"total_duration": 8.0, "segments": [{"id": 1, "caption": "A caption is on screen now.", "vo": "x",
                                                       "start": 2.0, "end": 6.0}]}
        cap = Captions("clean", 960, 540, timing)
        hits = LC.collisions([(0, 9, f)], cap, 960, 540, lambda _: res)
        self.assertEqual([h["text"] for h in hits], ["UNDER THE CAPTION"])
        f.items.remove(low)
        self.assertEqual(LC.collisions([(0, 9, f)], cap, 960, 540, lambda _: res), [])
        self.assertEqual(LC.census([(0, 9, f)]), {"Card": 3, "BigText": 1})

    def test_the_boxes_are_where_the_text_is_drawn(self):
        import engine as E
        import layoutcheck as LC
        f = E.Film(6, look="wall")
        f.items = [it for it in f.items if type(it).__name__ != "Board"]
        f.add(E.BigText("TWELVE SECONDS", 300, 900, 330, 0.0, grunge=False, shadow=False))
        f.add(E.Card(-1200, -300, 2700, 1650, 0.0, title="A TITLE", lines=["one line"], rot=4, rgb=(0, 0, 0), text_rgb=(255, 255, 0)))
        f.cam(0, 0, 0, 0.5, 3); f.cam(6, 0, 0, 0.5, 3)
        r = E.Renderer(f, 960, 540)
        boxes = LC.screen_text(f, r.res, 3.0, 960, 540)
        img = r.draw_world(3.0).astype(int)
        for mask, texts in (((img[..., 0] > 200) & (img[..., 1] > 200) & (img[..., 2] > 200), ["TWELVE SECONDS"]),
                            ((img[..., 0] > 200) & (img[..., 1] > 200) & (img[..., 2] < 80), ["A TITLE", "one line"])):
            ys, xs = np.nonzero(mask)
            got = (xs.min(), ys.min(), xs.max(), ys.max())
            want = [b for _, t, b in boxes if t in texts]
            want = (min(b[0] for b in want), min(b[1] for b in want), max(b[2] for b in want), max(b[3] for b in want))
            for g, w in zip(got, want):
                self.assertLess(abs(g - w), 12, (texts, got, want))                          # within the handheld wobble

    def test_qc_reports_overflow_in_a_real_scene(self):
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            import finish_fixture as F
            proj = F.make(tmp)
            sc = proj / "06_film" / "act_01" / "scene.py"
            sc.write_text(sc.read_text().replace(
                "    film.add(BigText(", "    from engine import Card\n    film.add(Card(0, 900, 2700, 1650, 0.2, title='ATITLEOFONEWORDFARTOOLONGFORANYCARDATALL'))\n"
                "    film.add(BigText(", 1))
            import finish
            assert subtitles.build(proj, **QUIET).ok
            assert finish.render_acts(proj, SIZE, 2, **QUIET).ok and finish.join(proj, **QUIET).ok
            assert finish.captions(proj, **QUIET).ok
            r = qc.build(proj, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertTrue(any(w.startswith("text fit: Card at 0.2s: title wider than the card") for w in r.warnings), r.warnings)


if __name__ == "__main__":
    unittest.main()
