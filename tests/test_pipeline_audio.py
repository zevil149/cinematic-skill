"""Tests for milestone 3.8: the phase 3 stages in docpipe (voice, narration, sound, subtitles), per
edition and for single-language projects: order, failures that stop the stages after them, resume,
gates, protected files and edition isolation.

Offline (CINEMATIC_OFFLINE=1): the voice is the mock provider (free, no sound engine); no network,
no paid call (a paid voice is configured only to check that it is refused). Needs ffmpeg and numpy
for the narration and the mix (the film job has both).
"""
import contextlib
import io
import os
import pathlib
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

import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import editions  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_docpipe import add_research, fill_narration, fill_outline, make_project, quiet  # noqa: E402
from test_editions import production, write_english, write_hindi  # noqa: E402
import narration  # noqa: E402
import outline  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False


def dp(proj, *, until=None, lang=None, confirm=False, only=None):
    """docpipe run, offline, with its printed report."""
    out = io.StringIO()
    docpipe.OPTS.update(offline=True, confirm_cost=confirm, max_cost=5.0)
    try:
        with contextlib.redirect_stdout(out):
            ok = docpipe.run(proj, until=until, only=only, lang=lang)
    finally:
        docpipe.OPTS.update(offline=False, confirm_cost=False)
    return ok, out.getvalue()


def status(proj):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        docpipe.status(proj)
    return out.getvalue()


def approve(proj, name, lang=None):
    quiet(docpipe.approve, proj, name, lang)


def use_mock(*eds):
    for ed in eds:
        c = L.load(ed / "voice.json"); c["provider"] = "mock"; L.save(ed / "voice.json", c)


def through_gates(tmp):
    """A two-edition production with its outline, scripts and visuals approved."""
    proj = production(tmp)
    dp(proj); approve(proj, "outline")
    write_english(proj)
    dp(proj); approve(proj, "script", "en")
    dp(proj, lang="hi")                                   # builds the shared beats; the Hindi skeleton blocks
    write_hindi(proj)
    dp(proj, lang="hi"); approve(proj, "script", "hi")
    ok, out = dp(proj, lang="all")
    assert "[visuals] passes its checks" in out, out
    approve(proj, "visuals")
    en, hi = editions.edition_dir(proj, "en"), editions.edition_dir(proj, "hi")
    use_mock(en, hi)
    return proj, en, hi


def no_api():
    return mock.patch.object(V.Http, "request", side_effect=AssertionError("docpipe sent an API request"))


@unittest.skipUnless(HAVE, "needs ffmpeg and numpy")
class TwoEditions(unittest.TestCase):
    def test_both_editions_end_to_end_then_resume(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="all", until="scenegen")
            self.assertTrue(ok, out)
            self.assertFalse((en / "audio" / "voice" / "manifest.json").exists())   # --until scenegen stops before the voice
            ok, out = dp(proj, lang="all")
            self.assertTrue(ok, out)
            order = [k for k in ("voice@en", "narration@en", "sound@en", "subtitles@en",
                                 "voice@hi", "narration@hi", "sound@hi", "subtitles@hi")]
            pos = [out.index(f"[{k}]") for k in order]
            self.assertEqual(pos, sorted(pos))                                       # stage order kept
            self.assertLess(out.index("[scenegen@hi]"), out.index("[voice@en]"))
            for ed, code in ((en, "en"), (hi, "hi")):
                t = L.load(ed / "audio" / "timing.json")
                self.assertEqual((t["lang"], t["built_by"]), (code, "narrate.py"))
                rep = L.load(ed / "audio" / "mix_report.json")
                self.assertEqual(rep["lang"], code)
                self.assertLessEqual(abs(rep["lufs"] + 15.0), 1.0); self.assertEqual(rep["clipped_samples"], 0)
                self.assertTrue((ed / "audio" / "mix.m4a").exists() and (ed / "audio" / "narration.m4a").exists())
                self.assertTrue((ed / "out" / f"subtitles.{code}.srt").exists() and (ed / "out" / f"subtitles.{code}.vtt").exists())
                self.assertEqual(L.load(ed / "audio" / "subs.json")["lang"], code)
                self.assertEqual(L.load(ed / "04_scenes" / "storyboard.json")["timing"], "voice")   # re-timed by the voice
                self.assertEqual({a["timing"] for a in L.load(ed / "06_film" / "acts.json")["acts"]}, {"voice"})
            self.assertTrue(editions.check(proj, "en").ok and editions.check(proj, "hi").ok)
            self.assertNotEqual(L.load(en / "audio" / "timing.json")["total_duration"], L.load(hi / "audio" / "timing.json")["total_duration"])
            # resume: the run after a new voice re-checks the storyboard and scenes once; then all is up to date
            ok, out = dp(proj, lang="all")
            self.assertTrue(ok, out)
            for k in order + ["visuals", "script@hi"]:
                self.assertIn(f"[{k}] up to date", out)
            ok, out = dp(proj, lang="all")
            self.assertTrue(ok, out)
            self.assertNotIn("passes its checks", out)
            for k in ("scenes@en", "scenes@hi", "scenegen@en", "scenegen@hi", "visuals") + tuple(order):
                self.assertIn(f"[{k}] up to date", out)
            st = status(proj)
            for k in order:
                self.assertRegex(st, rf"{k}\s+done")
            self.assertRegex(st, r"visuals\s+done\s+\[gate\]")
            # one Hindi line changes: Hindi needs its script approved again; English stays done
            n = L.load(L.paths(hi)["narration"]); n["sections"][0]["lines"][0]["text"] = "विमान रेत से ऊपर उठा।"
            n["sections"][0]["lines"][0].pop("spoken", None); L.save(L.paths(hi)["narration"], n)
            ok, out = dp(proj, lang="all")
            self.assertFalse(ok)
            self.assertIn("script --lang hi", out)                                     # the gate is not skipped
            self.assertNotIn("[voice@hi]", out)
            self.assertRegex(status(proj), r"subtitles@en\s+done")

    def test_paid_voice_is_stopped_and_the_stages_after_it_wait(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k" * 24}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")) as net:
            proj, en, hi = through_gates(tmp)
            c = L.load(en / "voice.json")
            c.update(provider="elevenlabs", voice="21m00Tcm4TlvDq8ikWAM", model="eleven_multilingual_v2",
                     settings={"stability": 0.5})
            L.save(en / "voice.json", c)
            ok, out = dp(proj, lang="all")
            self.assertFalse(ok)
            self.assertIn("[voice@en] blocked", out); self.assertIn("--confirm-cost", out)
            for k in ("narration@en", "sound@en", "subtitles@en", "voice@hi"):
                self.assertNotIn(f"[{k}]", out)                                        # failures stop the stages after it
            self.assertFalse((en / "audio" / "voice" / "spend.json").exists())
            ok, out = dp(proj, lang="all", confirm=True)                               # confirmed: the real client is offline
            self.assertFalse(ok); self.assertIn("CINEMATIC_OFFLINE", out)
            net.assert_not_called()                                                    # nothing left this machine
            self.assertFalse((en / "audio" / "voice" / "spend.json").exists())
            self.assertRegex(status(proj), r"voice@en\s+blocked")
            use_mock(en)                                                               # back to a free voice: it resumes
            ok, out = dp(proj, lang="all")
            self.assertTrue(ok, out)
            self.assertIn("[subtitles@hi]", out)

    def test_hindi_paid_voice_needs_the_review_even_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp, no_api(), mock.patch.dict(os.environ, {"SARVAM_API_KEY": "s" * 24}):
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="en")
            self.assertTrue(ok, out)
            c = L.load(hi / "voice.json")
            c.update(provider="sarvam", voice="anushka", model="bulbul:v2", inr_per_usd=85.0, settings={"pace": 1.0})
            L.save(hi / "voice.json", c)
            ok, out = dp(proj, lang="hi", confirm=True)
            self.assertFalse(ok)
            self.assertIn("native-speaker review", out); self.assertIn("[voice@hi] blocked", out)
            self.assertFalse((hi / "audio" / "voice" / "spend.json").exists())
            self.assertFalse((hi / "audio" / "timing.json").exists())
            self.assertTrue((en / "audio" / "mix.m4a").exists())                      # English untouched

    def test_your_edits_stop_a_stage_and_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj, en, hi = through_gates(tmp)
            self.assertTrue(dp(proj, lang="all")[0])
            srt = hi / "out" / "subtitles.hi.srt"
            srt.write_text(srt.read_text(encoding="utf-8").replace("।", "।।", 1), encoding="utf-8")
            mine = srt.read_bytes()
            mix = en / "audio" / "mix.m4a"
            with open(mix, "ab") as f:
                f.write(b"\0")
            mixed = mix.read_bytes()
            ok, out = dp(proj, lang="all")
            self.assertFalse(ok)
            self.assertIn("[sound@en] blocked", out); self.assertIn("--force", out)
            self.assertEqual(mix.read_bytes(), mixed)
            ok, out = dp(proj, lang="hi")
            self.assertFalse(ok); self.assertIn("[subtitles@hi] blocked", out)
            self.assertEqual(srt.read_bytes(), mine)                                   # never replaced by the pipeline
            self.assertFalse(srt.with_name(srt.name + ".bak").exists())
            # the person decides: the tool's own --force keeps a .bak, then the pipeline resumes
            import cuesheet
            import subtitles
            self.assertTrue(quiet(subtitles.build, hi, True).ok)
            self.assertEqual(srt.with_name(srt.name + ".bak").read_bytes(), mine)
            self.assertTrue(cuesheet.mix(en, force=True, log=lambda *a: None).ok)
            ok, out = dp(proj, lang="all")
            self.assertTrue(ok, out)


@unittest.skipUnless(HAVE, "needs ffmpeg and numpy")
class SingleLanguage(unittest.TestCase):
    def project(self, tmp):
        proj = make_project(tmp)
        add_research(proj)
        quiet(outline.init, proj); fill_outline(proj)
        quiet(narration.init, proj); fill_narration(proj)
        dp(proj); approve(proj, "outline")
        dp(proj); approve(proj, "script")
        ok, out = dp(proj)
        assert "[visuals] passes its checks" in out, out
        approve(proj, "visuals")
        quiet(voice.init, proj, "mock")
        return proj

    def test_audio_stages_and_a_new_voice_never_reopen_the_visuals(self):
        with tempfile.TemporaryDirectory() as tmp, no_api():
            proj = self.project(tmp)
            ok, out = dp(proj)
            self.assertTrue(ok, out)
            for k in ("voice", "narration", "sound", "subtitles"):
                self.assertIn(f"[{k}]", out)
            self.assertEqual(L.load(proj / "audio" / "timing.json")["lang"], "en")
            self.assertTrue((proj / "out" / "subtitles.en.srt").exists() and (proj / "audio" / "mix.m4a").exists())
            self.assertEqual(L.load(proj / "04_scenes" / "image_needs.json")["timing"], "voice")
            for _ in range(2):
                ok, out = dp(proj)
                self.assertTrue(ok, out)
                self.assertNotIn("passes its checks", out)                         # the approved visuals stay approved
            for k in ("visuals", "voice", "narration", "sound", "subtitles", "scenes", "scenegen"):
                self.assertIn(f"[{k}] up to date", out)
            st = status(proj)
            self.assertRegex(st, r"visuals\s+done\s+\[gate\]"); self.assertRegex(st, r"subtitles\s+done")
            self.assertNotRegex(st, r"voice\s+planned"); self.assertRegex(st, r"render\s+planned")
            # a new image need still reopens the visuals gate
            n = L.load(proj / "03_script" / "narration.json")
            n["sections"][0]["lines"][0].setdefault("images", []).append({"what": "a second photo of the sand", "kind": "photo"})
            L.save(proj / "03_script" / "narration.json", n)
            ok, out = dp(proj)
            self.assertFalse(ok)
            self.assertIn("approve --project", out)

    def test_approvals_recorded_before_this_milestone_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp)
            p = L.paths(proj)
            state = docpipe.load_state(proj)
            old = L.hash_files(docpipe._inputs(p, "image_needs", "selection", "topic"))   # how 3.7 recorded it
            state["stages"]["visuals"].update(inputs=old, approved=old, status="done")
            L.save(p["state"], state)
            ok, out = dp(proj, until="scenegen")
            self.assertTrue(ok, out)
            self.assertIn("[visuals] up to date", out)
            st = docpipe.load_state(proj)["stages"]["visuals"]
            self.assertEqual(st["approved"], st["inputs"]); self.assertNotEqual(st["inputs"], old)

    def test_until_scenegen_is_the_old_stop_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp)
            ok, out = dp(proj, until="scenegen")
            self.assertTrue(ok, out)
            self.assertNotIn("[voice]", out)
            self.assertFalse((proj / "audio" / "voice" / "manifest.json").exists())
            ok, out = dp(proj, only="voice")
            self.assertTrue(ok, out)
            self.assertTrue((proj / "audio" / "voice" / "manifest.json").exists())
            self.assertFalse((proj / "audio" / "timing.json").exists())


if __name__ == "__main__":
    unittest.main()
