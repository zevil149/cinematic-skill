"""Tests for milestone 3.7: word-level caption timing and per-edition subtitles (SRT, WebVTT).

Offline (CINEMATIC_OFFLINE=1): the voice is the mock and every timing file is built here. The word
timing and subtitle tests need only the standard library; the edition tests need ffmpeg (narrate.py)
and the caption rendering tests need skia (the film job has both).
"""
import hashlib
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402
import editions  # noqa: E402
import subtitles as S  # noqa: E402
import voice  # noqa: E402
import wordtimes as WT  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
try:
    import numpy as np
    import skia  # noqa: F401
    HAVE_SKIA = True
except Exception:                          # pragma: no cover
    HAVE_SKIA = False

QUIET = dict(log=lambda *a: None)


def seg(i, caption, spoken, start, words_from="voice", per=0.4, gap=0.05):
    toks = re.findall(r"[^\s.,;:!?\"'()\[\]{}…।॥—–/\-]+", spoken)
    words, t = [], start
    for w in toks:
        words.append({"w": w, "start": round(t, 3), "end": round(t + per, 3)}); t += per + gap
    return {"id": i, "scene": "s1", "caption": caption, "vo": spoken, "start": start, "end": round(t, 3),
            "duration": round(t - start, 3), "words": words, "words_from": words_from}


def legacy_expected(sg):
    """The letter-share estimate exactly as captions.py computed it before milestone 3.7."""
    disp = sg["caption"].replace('"', "").split()
    lens = []
    for w in disp:
        letters = len(re.sub(r"[^A-Za-z]", "", w))
        if re.search(r"\d", w):
            letters = max(letters, 6 * len(re.sub(r"[^0-9]", "", w)) // 2 + 4)
        lens.append(max(1, letters))
    s = sum(lens); acc = 0; out = []
    for w, l in zip(disp, lens):
        out.append((w, sg["start"] + (sg["end"] - sg["start"]) * acc / s)); acc += l
    return out


class WordTiming(unittest.TestCase):
    def test_voice_words_numbers_and_punctuation(self):
        sg = seg(1, "On December 17th, 1903, a machine left the sand.",
                 "On December seventeenth, nineteen oh three, a machine left the sand.", 1.0)
        tw = WT.timed_words(sg)
        self.assertEqual([w for w, *_ in tw], sg["caption"].split())
        src = {w: s for w, _, _, s in tw}
        self.assertEqual(src["December"], "voice"); self.assertEqual(src["sand."], "voice")
        self.assertEqual(src["1903,"], "voice-approx"); self.assertEqual(src["17th,"], "voice-approx")
        y = next(x for x in tw if x[0] == "1903,")
        sp = {w["w"]: w for w in sg["words"]}
        self.assertEqual((y[1], y[2]), (sp["nineteen"]["start"], sp["three"]["end"]))   # spans the words it is read as
        self.assertEqual(next(x for x in tw if x[0] == "machine")[1], sp["machine"]["start"])
        starts = [a for _, a, _, _ in tw]
        self.assertEqual(starts, sorted(starts))

    def test_hindi_words_and_danda(self):
        sg = seg(2, "राइट बंधुओं का विमान रेत से ऊपर उठा।", "राइट बंधुओं का विमान रेत से ऊपर उठा।", 3.0)
        tw = WT.timed_words(sg)
        self.assertEqual([s for *_, s in tw], ["voice"] * 8)
        self.assertEqual([a for _, a, _, _ in tw], [w["start"] for w in sg["words"]])
        self.assertEqual(tw[-1][0], "उठा।")

    def test_estimated_and_legacy_timing_are_labelled_and_unchanged(self):
        sg = seg(3, "Twelve seconds.", "Twelve seconds.", 0.5, words_from="estimate")
        self.assertEqual({s for *_, s in WT.timed_words(sg)}, {"estimate"})
        self.assertEqual(WT.timing_of(sg), "estimate")
        legacy = {"id": 4, "caption": "In 1929 the market fell hard.", "vo": "In nineteen twenty-nine the market fell hard.",
                  "start": 2.0, "end": 6.0}
        self.assertIsNone(WT.timed_words(legacy))
        self.assertEqual(WT.timing_of(legacy), "legacy")
        self.assertEqual(WT.words_with_times(legacy), legacy_expected(legacy))           # the old estimate, exactly

    def test_shown_but_unspoken_words_are_held_not_invented(self):
        sg = seg(5, "Kitty Hawk (North Carolina) 1903", "Kitty Hawk 1903", 0.0)
        sg["words"][-1]["w"] = "1903"
        tw = WT.timed_words(sg)
        self.assertEqual(len(tw), 5)
        nc = [x for x in tw if x[0].startswith(("(North", "Carolina"))]
        self.assertTrue(all(x[3] == "voice-approx" for x in nc))
        self.assertTrue(all(x[1] == x[2] for x in nc))


def timing_of(*segs, total=None, lang=None):
    t = {"total_duration": total or segs[-1]["end"] + 3.0, "segments": list(segs)}
    if lang:
        t["lang"] = lang
    return t


class Cues(unittest.TestCase):
    def test_sentences_clauses_lines_and_reading_time(self):
        long = ("The engine coughed twice, the propeller caught, and the whole frame shook, "
                "then it rolled down the rail into a headwind of twenty-seven miles an hour.")
        t = timing_of(seg(1, "It flew. Twelve seconds.", "It flew. Twelve seconds.", 1.0, per=0.3),
                      seg(2, long, long, 6.0, per=0.32), seg(3, "Then silence.", "Then silence.", 20.0, per=0.3))
        cues = S.build_cues(t)
        self.assertEqual([c["lines"] for c in cues if c["line"] == 1], [["It flew. Twelve seconds."]])   # too short to split
        two = [c for c in cues if c["line"] == 2]
        self.assertGreater(len(two), 1)
        for c in cues:
            self.assertLessEqual(len(c["lines"]), S.MAX_LINES)
            self.assertTrue(all(len(x) <= S.MAX_LINE + 12 for x in c["lines"]), c["lines"])
            self.assertLessEqual(c["t1"] - c["t0"], S.MAX_DUR + 1e-6)
        self.assertTrue(two[0]["lines"][-1].endswith(","))                               # cut after a clause
        self.assertEqual(" ".join(" ".join(c["lines"]) for c in two), long)              # every word, in order
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["t1"], b["t0"] - S.GAP + 1e-6)                        # never overlapping
        last = cues[-1]
        self.assertGreaterEqual(last["t1"] - last["t0"], S.MIN_DUR - 1e-6)               # held long enough to read
        self.assertEqual([c["n"] for c in cues], list(range(1, len(cues) + 1)))

    def test_sentence_ends_split_a_line_and_tiny_tails_are_kept(self):
        t = timing_of(seg(1, "The plane rose from the sand at last. Nobody watching knew what it meant.",
                          "The plane rose from the sand at last. Nobody watching knew what it meant.", 0.0, per=0.3),
                      seg(2, "It flew for twelve seconds over the cold sand. Yes.", "It flew for twelve seconds over the cold sand. Yes.", 8.0))
        cues = S.build_cues(t)
        self.assertEqual([c["lines"] for c in cues if c["line"] == 1],
                         [["The plane rose from the sand at last."], ["Nobody watching knew what it meant."]])
        self.assertEqual(" ".join(cues[-1]["lines"]).split()[-1], "Yes.")              # not a cue of its own
        self.assertEqual(len([c for c in cues if c["line"] == 2]), 1)

    def test_tight_gaps_win_over_reading_time(self):
        t = timing_of(seg(1, "Go.", "Go.", 1.0, per=0.2), seg(2, "Now.", "Now.", 1.5, per=0.2))
        a, b = S.build_cues(t)
        self.assertLessEqual(a["t1"], b["t0"] - S.GAP + 1e-6)
        self.assertGreater(a["t1"], a["t0"])

    def test_formats(self):
        t = timing_of(seg(1, "बारह सेकंड, एक सौ बीस फ़ुट की उड़ान।", "बारह सेकंड, एक सौ बीस फ़ुट की उड़ान।", 61.25),
                      seg(2, "उस दिन किसी ने इसका अर्थ नहीं समझा।", "उस दिन किसी ने इसका अर्थ नहीं समझा।", 3725.5, words_from="estimate"))
        cues = S.build_cues(t)
        srt, vtt = S.to_srt(cues), S.to_vtt(cues, "hi", {"voice": 1, "estimate": 1})
        blocks = srt.strip().split("\n\n")
        self.assertEqual(len(blocks), 2)
        self.assertRegex(blocks[0], r"^1\n00:01:01,250 --> 00:01:0\d,\d{3}\nबारह सेकंड")
        self.assertRegex(blocks[1], r"^2\n01:02:05,500 --> 01:02:0\d,\d{3}\n")
        self.assertTrue(vtt.startswith("WEBVTT\n\nNOTE\nLanguage: hi. Word timing: 1 cue(s) estimate, 1 cue(s) voice."))
        self.assertRegex(vtt, r"\nL1-1\n00:01:01\.250 --> 00:01:0\d\.\d{3}\n")
        self.assertIn("उस दिन किसी ने इसका अर्थ नहीं समझा।", vtt)
        self.assertEqual([c["timing"] for c in cues], ["voice", "estimate"])

    def test_legacy_timing_still_gives_subtitles_marked_estimated(self):
        t = {"total_duration": 9.0, "segments": [{"id": 1, "scene": "a", "caption": "In 1929 the market fell.",
                                                     "vo": "In nineteen twenty-nine the market fell.", "start": 1.0, "end": 4.0}]}
        cues = S.build_cues(t)
        self.assertEqual(cues[0]["timing"], "estimate")
        self.assertEqual(cues[0]["t0"], 1.0)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class EditionSubtitles(unittest.TestCase):
    def voiced(self, tmp):
        import narrate
        from test_voice import NOLOG, two_editions
        proj, en, hi = two_editions(tmp)
        for ed in (en, hi):
            assert voice.synth(ed, **NOLOG).ok
            assert narrate.build(ed, retime=False, **QUIET).ok
        return proj, en, hi

    def sha(self, f):
        return hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()

    def test_each_edition_gets_its_own_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = self.voiced(tmp)
            keep = {f: self.sha(f) for ed in (en, hi) for f in (ed / "audio" / "timing.json", ed / "script.json",
                                                                ed / "03_script" / "narration.json", ed / "audio" / "narration.m4a")}
            for ed, code in ((en, "en"), (hi, "hi")):
                r = S.build(ed, **QUIET)
                self.assertTrue(r.ok, r.errors)
                subs = L.load(ed / "audio" / "subs.json")
                self.assertEqual((subs["lang"], subs["built_by"]), (code, "subtitles.py"))
                self.assertEqual(set(subs["files"]), {f"out/subtitles.{code}.srt", f"out/subtitles.{code}.vtt"})
                lines = {s["id"] for s in L.load(ed / "audio" / "timing.json")["segments"]}
                self.assertEqual({c["line"] for c in subs["cues"]}, lines)                 # every line has its cues
                self.assertTrue((ed / "out" / f"subtitles.{code}.srt").read_text(encoding="utf-8").startswith("1\n"))
            self.assertTrue(any("ऀ" <= ch <= "ॿ" for ch in (hi / "out" / "subtitles.hi.srt").read_text(encoding="utf-8")))
            self.assertFalse(any("ऀ" <= ch <= "ॿ" for ch in (en / "out" / "subtitles.en.srt").read_text(encoding="utf-8")))
            self.assertFalse((hi / "out" / "subtitles.en.srt").exists()); self.assertFalse((en / "out" / "subtitles.hi.srt").exists())
            self.assertEqual({f: self.sha(f) for f in keep}, keep)                              # narration, timing, script untouched
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)
            # cross-contamination is caught
            shutil.copyfile(en / "out" / "subtitles.en.srt", hi / "out" / "subtitles.en.srt")
            self.assertTrue(any("named for 'en'" in e for e in editions.check(proj, "hi").errors))
            (hi / "out" / "subtitles.en.srt").unlink()
            good = (hi / "out" / "subtitles.hi.srt").read_text(encoding="utf-8")
            (hi / "out" / "subtitles.hi.srt").write_text((en / "out" / "subtitles.en.srt").read_text(), encoding="utf-8")
            self.assertTrue(any("subtitles.hi.srt" in e and "Latin" in e for e in editions.check(proj, "hi").errors))
            (hi / "out" / "subtitles.hi.srt").write_text(good, encoding="utf-8")
            t = L.load(hi / "audio" / "timing.json"); t["lang"] = "en"; L.save(hi / "audio" / "timing.json", t)
            self.assertTrue(any("is the en voice" in e for e in S.build(hi, **QUIET).errors))

    def test_resume_protection_and_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = self.voiced(tmp)
            self.assertTrue(S.build(en, **QUIET).ok)
            srt = en / "out" / "subtitles.en.srt"
            h = self.sha(srt)
            self.assertTrue(any("up to date" in n for n in S.build(en, **QUIET).notes))
            self.assertEqual(self.sha(srt), h)
            srt.write_text(srt.read_text().replace("Twelve seconds.", "Twelve whole seconds."))   # your fix
            mine = self.sha(srt)
            r = S.build(en, **QUIET)
            self.assertTrue(any("is yours" in e for e in r.errors)); self.assertEqual(self.sha(srt), mine)
            r = S.build(en, force=True, **QUIET)
            self.assertTrue(r.ok, r.errors)
            self.assertEqual(self.sha(srt.with_name(srt.name + ".bak")), mine)
            self.assertNotEqual(self.sha(srt), mine)
            # a file subtitles.py never wrote is yours too
            vtt = hi / "out" / "subtitles.hi.vtt"
            vtt.parent.mkdir(parents=True, exist_ok=True); vtt.write_text("WEBVTT\n\nmine\n", encoding="utf-8")
            self.assertFalse(S.build(hi, **QUIET).ok)
            self.assertEqual(vtt.read_text(encoding="utf-8"), "WEBVTT\n\nmine\n")

    def test_estimated_lines_are_marked_in_both_formats(self):
        import narrate
        from test_narrate import recording
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = self.voiced(tmp)
            recording(hi / "audio" / "voice" / "manual" / voice.seg_name(2), 2.0)       # your own reading: no word times
            from test_voice import NOLOG
            self.assertTrue(voice.synth(hi, **NOLOG).ok)
            self.assertTrue(narrate.build(hi, retime=False, **QUIET).ok)
            self.assertTrue(S.build(hi, **QUIET).ok)
            subs = L.load(hi / "audio" / "subs.json")
            by_line = {c["line"]: c["timing"] for c in subs["cues"]}
            self.assertEqual(by_line[2], "estimate"); self.assertEqual(by_line[1], "voice")
            self.assertGreaterEqual(subs["timing_counts"]["estimate"], 1)
            self.assertIn("cue(s) estimate", (hi / "out" / "subtitles.hi.vtt").read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_SKIA, "needs skia-python and numpy")
class CaptionRendering(unittest.TestCase):
    def yellow(self, img):
        r, g, b, a = (img[..., k].astype(int) for k in range(4))
        return (r > 200) & (g > 160) & (b < 110) & (a > 200)

    def cols(self, mask):
        xs = np.where(mask.any(axis=0))[0]
        return (int(xs.min()), int(xs.max())) if len(xs) else None

    def test_highlight_follows_voice_words_in_hindi(self):
        from captions import Captions
        sg = seg(1, "राइट बंधुओं का विमान", "राइट बंधुओं का विमान", 1.0, per=0.5)
        cap = Captions("highlighter", 640, 360, timing_of(sg, lang="hi"))
        w = sg["words"]
        first = self.cols(self.yellow(cap.layer(w[0]["start"] + 0.3)))
        third = self.cols(self.yellow(cap.layer(w[2]["start"] + 0.3)))
        self.assertIsNotNone(first); self.assertIsNotNone(third)
        self.assertLess(first[1], third[0])                       # the swipe moved to the word being spoken
        # estimated times: shown whole, no swipe (unless asked for)
        est = seg(1, sg["caption"], sg["vo"], 1.0, words_from="estimate", per=0.5)
        self.assertFalse(self.yellow(Captions("highlighter", 640, 360, timing_of(est)).layer(1.8)).any())
        self.assertTrue(self.yellow(Captions("highlighter", 640, 360, timing_of(est), highlight="all").layer(1.8)).any())
        self.assertFalse(self.yellow(Captions("highlighter", 640, 360, timing_of(sg), highlight="none").layer(1.8)).any())

    def test_devanagari_and_mixed_text_are_shaped_in_every_style(self):
        import textshape
        from captions import Captions
        sg = seg(1, "राइट बंधुओं ने NASA से पहले उड़ान भरी।", "राइट बंधुओं ने नासा से पहले उड़ान भरी।", 0.5)
        real = textshape.shape
        with mock.patch.object(textshape, "shape", side_effect=real) as sh:
            for style in ("highlighter", "clean", "paper", "redbar"):
                img = Captions(style, 640, 360, timing_of(sg, lang="hi")).layer(1.2)
                self.assertIsNotNone(img, style)
                self.assertGreater(int((img[..., 3] > 0).sum()), 500, style)
            self.assertTrue(sh.called)                             # Devanagari went through HarfBuzz
        tw = WT.timed_words(sg)
        self.assertEqual(next(x for x in tw if x[0] == "NASA")[3], "voice-approx")   # shown in Latin, spoken in Hindi

    def test_legacy_chunks_are_unchanged(self):
        from captions import chunks_for
        legacy = {"total_duration": 9.0, "segments": [{"id": 1, "caption": "In 1929 the market fell hard, and fast.",
                                                       "vo": "x", "start": 1.0, "end": 5.0}]}
        ch = chunks_for(legacy, "highlighter")
        self.assertEqual([w for c in ch for w in c["words"]], legacy_expected(legacy["segments"][0]))
        self.assertEqual({c["timing"] for c in ch}, {"legacy"})


if __name__ == "__main__":
    unittest.main()
