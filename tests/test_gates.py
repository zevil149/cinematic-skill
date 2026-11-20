"""Tests for milestone 6.1: gate integrity and run durability.

  * a look approval that no longer matches the scenes (the audit's reproduced bypass) keeps the
    finishing stages waiting, under a full run and under run --only, in editions and single-language
    projects; a new review and approval lets them go on
  * run --only cannot skip an earlier gate that is unapproved, or approved for older files, or an
    earlier stage that never ran
  * docpipe.json is saved after every stage: a stage that is running shows "running" on disk, one
    that raises is "interrupted", the stages before it keep "done", and the next run resumes
  * render, join and caption passes stop, with their whole process group, past their time limit

Offline (CINEMATIC_OFFLINE=1): mock voices, designed cards. Needs skia-python, numpy and ffmpeg.
"""
import contextlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import finish  # noqa: E402

try:
    import numpy  # noqa: F401
    import skia  # noqa: F401
    from test_pipeline_audio import HAVE as HAVE_AUDIO, SingleLanguage, through_gates
    HAVE = HAVE_AUDIO and shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SMALL = dict(size="160x90", workers=2)
QUIET = dict(log=lambda *a: None)


def dp(proj, **kw):
    out = io.StringIO()
    docpipe.OPTS.update(offline=True, **SMALL)
    try:
        with contextlib.redirect_stdout(out):
            ok = docpipe.run(proj, **kw)
    finally:
        docpipe.OPTS.update(offline=False, size=finish.SIZE, workers=0)
    return ok, out.getvalue()


def approve(proj, name, lang=None):
    with contextlib.redirect_stdout(io.StringIO()):
        docpipe.approve(proj, name, lang)


def stages(proj):
    return docpipe.load_state(proj)["stages"]


def edit(f, text="\n# an edit after the look was approved\n"):
    f.write_text(f.read_text(encoding="utf-8") + text, encoding="utf-8")


class Rules(unittest.TestCase):
    """The decisions themselves, on hand-made states (no rendering)."""

    def test_the_look_must_be_approved_for_the_current_review(self):
        st = {"stages": {"review@en": {"status": "done", "approved": "abc"}}}
        self.assertIsNone(docpipe.look_problem(st, "review@en", "abc", "P", " --lang en"))
        self.assertIn("no longer matches", docpipe.look_problem(st, "review@en", "xyz", "P", " --lang en"))
        st["stages"]["review@en"] = {"status": "awaiting approval"}
        self.assertIn("approve --project P look --lang en", docpipe.look_problem(st, "review@en", "abc", "P", " --lang en"))
        st["stages"]["review@en"] = {"status": "running", "approved": "abc"}               # interrupted while it was made again
        self.assertIsNotNone(docpipe.look_problem(st, "review@en", "abc", "P"))
        self.assertIsNotNone(docpipe.look_problem({"stages": {}}, "review@en", "abc", "P"))

    def test_only_needs_what_a_full_run_would_have_needed(self):
        st = {"stages": {"outline": {"status": "done", "approved": "o1"}, "scenes": {"status": "partial"},
                         "visuals": {"status": "done", "approved": "v-old"}, "voice": {"status": "blocked"},
                         "review": {"status": "awaiting approval"}}}
        now = {"outline": "o1", "visuals": "v-new"}
        got = docpipe.upstream_problems(st, [("outline", True), ("scenes", False), ("visuals", True), ("voice", False),
                                             ("narration", False), ("review", "look")], now.get)
        self.assertEqual(len(got), 3, got)
        self.assertTrue(any(g.startswith("visuals is not approved") for g in got))
        self.assertTrue(any(g.startswith("voice has not run successfully (blocked)") for g in got))
        self.assertTrue(any(g.startswith("narration has not run successfully (not run)") for g in got))
        self.assertFalse(any(g.startswith(("outline", "scenes", "review")) for g in got))  # partial runs; the look is the finishing stages' own check

    def test_time_limits_scale_with_the_film_and_can_be_set(self):
        with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: ""}):
            hd = finish.time_limit(60, "1920x1080")
            self.assertEqual(hd, finish.BASE_LIMIT + 60 * finish.PER_FILM_SECOND)
            self.assertEqual(finish.time_limit(60, "3840x2160"), finish.BASE_LIMIT + 4 * 60 * finish.PER_FILM_SECOND)
            self.assertEqual(finish.time_limit(60, "160x90"), hd)                              # never less than 1080p's
            self.assertLess(finish.time_limit(60, "1920x1080", share=0.2), hd)
        for bad in ("abc", "0", "-3"):
            with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: bad}):
                self.assertEqual(finish.time_limit(1, "1920x1080"), finish.BASE_LIMIT + finish.PER_FILM_SECOND)
        with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: "42"}):
            self.assertEqual(finish.time_limit(600, "3840x2160"), 42.0)

    @unittest.skipUnless(os.name == "posix", "process groups")
    def test_a_hung_pass_is_stopped_with_everything_it_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidf = pathlib.Path(tmp) / "child.pid"
            t0 = time.time()
            res, hung = finish.run_bounded(["bash", "-c", f"sleep 60 & echo $! > {pidf}; wait"], 1.0)
            self.assertTrue(hung); self.assertLess(time.time() - t0, 20)
            pid = int(pidf.read_text())
            for _ in range(50):                                                              # the grandchild is gone too
                st = pathlib.Path(f"/proc/{pid}/status")
                if not st.exists() or "\nState:\tZ" in st.read_text():
                    break
                time.sleep(0.1)
            else:
                self.fail("the background child of a stopped pass is still running")
            res, hung = finish.run_bounded([sys.executable, "-c", "print('fine')"], 30)
            self.assertFalse(hung); self.assertEqual((res.returncode, res.stdout.strip()), (0, "fine"))


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class LookGate(unittest.TestCase):
    def test_a_lapsed_look_approval_holds_the_finishing_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            ok, out = dp(proj, lang="en", until="review")
            self.assertIn("[review@en] passes its checks", out)
            approve(proj, "look", "en")
            ok, out = dp(proj, lang="en", until="render")
            self.assertTrue(ok, out)
            act = en / "out" / "acts" / "act_01.mp4"
            stamp = act.stat().st_mtime_ns
            # the audit's bypass: the scene changes after the approval, then --only render
            edit(en / "06_film" / "act_01" / "scene.py")
            for stage in ("render", "join", "captions", "qc"):
                ok, out = dp(proj, lang="en", only=stage)
                self.assertFalse(ok)
                self.assertIn(f"[{stage}@en] waits for the look of the en edition", out)
                self.assertIn("no longer matches its scenes, timing or assets", out)
                self.assertEqual(stages(proj)[f"{stage}@en"]["status"], "waiting for the look")
            self.assertEqual(act.stat().st_mtime_ns, stamp)                                # nothing was rendered
            # a full run makes the review again and waits for it; the old approval does not count
            ok, out = dp(proj, lang="en", until="render")
            self.assertFalse(ok)
            self.assertIn("[review@en] passes its checks", out); self.assertIn("[render@en] waits for the look", out)
            self.assertEqual(act.stat().st_mtime_ns, stamp)
            # a new approval: --only render now renders the changed act
            approve(proj, "look", "en")
            ok, out = dp(proj, lang="en", only="render")
            self.assertTrue(ok, out)
            self.assertNotEqual(act.stat().st_mtime_ns, stamp)
            self.assertEqual(stages(proj)["render@en"]["status"], "done")
            # the other edition was never approved and never rendered
            self.assertFalse((hi / "out" / "acts").exists())

    def test_single_language_projects_hold_the_same_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = SingleLanguage.project(None, tmp)
            ok, out = dp(proj, until="review")
            self.assertIn("[review] passes its checks", out)
            approve(proj, "look")
            edit(proj / "scene.py") if not (proj / "06_film" / "act_01" / "scene.py").exists() \
                else edit(proj / "06_film" / "act_01" / "scene.py")
            ok, out = dp(proj, only="render")
            self.assertFalse(ok)
            self.assertIn("[render] waits for the look: the look approved for it no longer matches", out)
            self.assertFalse((proj / "out" / "acts").exists())


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class OnlyGate(unittest.TestCase):
    def test_only_cannot_skip_an_unapproved_or_changed_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            manifest = en / "audio" / "voice" / "manifest.json"
            ok, out = dp(proj, lang="en", only="narration")                                 # the voice never ran
            self.assertFalse(ok)
            self.assertIn("[narration@en] cannot run on its own yet", out)
            self.assertIn("voice@en has not run successfully (not run)", out)
            # the script changes after its approval: --only voice must not read it
            n = L.paths(en)["narration"]
            data = L.load(n)
            data["sections"][0]["lines"][0]["text"] += " Indeed."
            L.save(n, data)
            ok, out = dp(proj, lang="en", only="voice")
            self.assertFalse(ok)
            self.assertIn("script@en is not approved for its current files", out)
            self.assertFalse(manifest.exists())
            # through the normal route: the script is checked and approved again, then --only works
            ok, out = dp(proj, lang="en", until="scenegen")
            self.assertIn("[script@en] passes its checks", out)
            approve(proj, "script", "en")
            ok, out = dp(proj, lang="en", until="scenegen")
            self.assertTrue(ok, out)
            ok, out = dp(proj, lang="en", only="voice")
            self.assertTrue(ok, out)
            self.assertTrue(manifest.exists())

    def test_only_in_a_single_language_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = SingleLanguage.project(None, tmp)
            st = docpipe.load_state(proj)
            st["stages"]["visuals"]["approved"] = "an approval for other files"
            L.save(L.paths(proj)["state"], st)
            ok, out = dp(proj, only="voice")
            self.assertFalse(ok)
            self.assertIn("visuals is not approved for its current files", out)
            self.assertFalse((proj / "audio" / "voice" / "manifest.json").exists())


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class Durability(unittest.TestCase):
    def test_state_is_saved_after_every_stage_and_a_crash_resumes(self):
        import narrate
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            self.assertTrue(dp(proj, lang="en", until="scenegen")[0])
            seen = {}

            def crash(*a, **k):                                                              # what is on disk mid-run
                seen.update(stages(proj))
                raise KeyboardInterrupt
            with mock.patch.object(narrate, "build", side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    dp(proj, lang="en", until="subtitles")
            self.assertEqual(seen["voice@en"]["status"], "done")                             # saved when it finished
            self.assertEqual(seen["narration@en"]["status"], "running")                      # a killed run leaves this
            after = stages(proj)
            self.assertEqual(after["narration@en"]["status"], "interrupted")
            self.assertIn("KeyboardInterrupt", after["narration@en"]["errors"][0])
            self.assertEqual(after["voice@en"]["status"], "done")
            manifest = en / "audio" / "voice" / "manifest.json"
            stamp = manifest.stat().st_mtime_ns
            ok, out = dp(proj, lang="en", until="subtitles")
            self.assertTrue(ok, out)
            self.assertIn("[voice@en] up to date", out)                                     # nothing made twice
            self.assertEqual(manifest.stat().st_mtime_ns, stamp)
            self.assertEqual(stages(proj)["narration@en"]["status"], "done")

    def test_a_stage_interrupted_while_approved_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            st = docpipe.load_state(proj)
            st["stages"]["visuals"]["status"] = "running"                                  # as a killed run leaves it
            L.save(L.paths(proj)["state"], st)
            ok, out = dp(proj, lang="en", only="assets")
            self.assertFalse(ok); self.assertIn("visuals is not approved for its current files", out)
            ok, out = dp(proj, lang="en", until="assets")                                    # a full run checks it again
            self.assertTrue(ok, out)
            self.assertEqual(stages(proj)["visuals"]["status"], "done")                      # its approval still holds


@unittest.skipUnless(HAVE, "needs skia-python, numpy and ffmpeg")
class TimeLimits(unittest.TestCase):
    def test_render_join_and_captions_stop_when_hung(self):
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            p = finish.fp(proj)
            with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: "0.01"}):
                r = finish.render_acts(proj, "160x90", 2, **QUIET)
            self.assertFalse(r.ok)
            stopped = [e for e in r.errors if "did not finish in 0s and was stopped" in e]
            self.assertEqual([e.split(":")[0] for e in stopped], ["act 1", "act 2"], r.errors)
            self.assertTrue(any("not complete" in e for e in r.errors))                     # the stage fails as a whole
            self.assertEqual(list(p["acts_dir"].glob("*.mp4")), [])                          # no partial file, nothing recorded
            self.assertEqual(finish.load_state(p).get("acts", {}), {})
            time.sleep(0.5)
            ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
            self.assertNotIn(str(p["acts_dir"]), ps)                                         # no worker left rendering
            self.assertTrue(finish.render_acts(proj, "160x90", 2, **QUIET).ok)               # without the limit: rendered
            with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: "0.01"}):
                r = finish.join(proj, **QUIET)
            self.assertTrue(any("the join did not finish" in e for e in r.errors), r.errors)
            self.assertFalse(p["film"].exists()); self.assertEqual(list(p["out"].glob("*.joining.mp4")), [])
            self.assertTrue(finish.join(proj, **QUIET).ok)
            with mock.patch.dict(os.environ, {finish.TIMEOUT_ENV: "0.01"}):
                r = finish.captions(proj, **QUIET)
            self.assertTrue(any("burning the captions did not finish" in e for e in r.errors), r.errors)
            self.assertFalse(p["captioned"].exists()); self.assertEqual(list(p["out"].glob("*.burning.mp4")), [])
            self.assertTrue(finish.captions(proj, **QUIET).ok)


if __name__ == "__main__":
    unittest.main()
