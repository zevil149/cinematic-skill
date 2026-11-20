"""Tests for milestone 6.5: the final report, credits and validators (report.py, docpipe report,
visuals acknowledgement).

  * the report gathers each edition's status, script and claims (with claim-to-line warnings in
    English and numbers only otherwise), images and automatic picks, sound, QC and delivery, and
    the claim -> source -> line -> scene -> image trail, with what none of it proves
  * it is complete only when every edition in the run is; otherwise the stage fails and says why
  * the same records make the same report (no clock), and its fingerprint follows its inputs
  * automatic image picks must be looked at (chosen or acknowledged) before the visuals approval
  * credits.md and out/credits.<lang>.md list what the films use, with full attributions

Offline: a two-edition production through its gates (mock voices), with finished-film records
written by hand where rendering would only slow the test (the end-to-end run renders for real).
"""
import contextlib
import io
import os
import pathlib
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
import report  # noqa: E402
import visuals  # noqa: E402

try:
    from test_pipeline_audio import HAVE, through_gates
except ImportError:                          # pragma: no cover
    HAVE = False


def finished_records(ed, code, complete=True):
    """What render, join and QC leave behind, written directly."""
    out = ed / "out"
    L.save(out / f"qc.{code}.json", {"lang": code, "complete": complete, "errors": [] if complete else ["duration: short"],
                                     "warnings": [], "not_checked": [], "measurements": {"loudness": {"integrated_lufs": -15.0}}})
    L.save(out / f"delivery.{code}.json", {"lang": code, "complete": complete, "film": {"duration": 12.0}, "files": []})
    L.save(ed / "audio" / "mix_report.json", {"lang": code, "duration": 12.0, "lufs": -15.0, "target_lufs": -15.0,
                                             "true_peak_dbtp": -1.6, "ceiling_dbtp": -1.5, "clipped_samples": 0,
                                             "voice_over_music_db": 17.0})
    t = L.load(L.paths(ed)["timing"], {}) if L.paths(ed)["timing"].exists() else {}
    L.save(L.paths(ed)["timing"], {**t, "lang": code, "total_duration": 12.0, "segments": t.get("segments", [])})
    L.save(out / f"rights.{code}.json", {"lang": code, "usable": True, "images": [
        {"id": "I001", "media": "image", "usable": True, "what": "First flight", "credit": "John T. Daniels",
         "license": "Public domain", "source": "https://www.loc.gov/item/x", "attribution": "\"First flight\" by John T. Daniels, Public domain",
         "basis": "free licence as the archive states it (Public domain)", "cleared": None}],
        "footage": [], "audio": [], "maps": [], "narration": {"text": "mock (en-us)"}})


@unittest.skipUnless(HAVE, "needs ffmpeg and numpy")
class Report(unittest.TestCase):
    def test_incomplete_then_complete_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            r = report.build(proj, **{"log": lambda *a: None})
            self.assertFalse(r.ok)
            self.assertTrue(any(e.startswith("en: not complete (no finished film yet)") for e in r.errors), r.errors)
            md = (proj / "reports" / "final_report.md").read_text()
            self.assertIn("## en edition: NOT complete", md); self.assertIn("## What this report does not prove", md)
            for code, ed in (("en", en), ("hi", hi)):
                finished_records(ed, code)
            r = report.build(proj)
            self.assertTrue(r.ok, r.errors)
            first = {f: (proj / "reports" / f).read_bytes() for f in ("final_report.md", "credits.md", "report.json")}
            self.assertEqual(report.build(proj).ok, True)
            self.assertEqual({f: (proj / "reports" / f).read_bytes() for f in first}, first)          # same records, same report
            data = L.load(proj / "reports" / "report.json")
            self.assertEqual(data["editions"]["hi"]["script"]["claim_check"], "numbers only (the claims are written in English)")
            self.assertEqual(data["editions"]["en"]["script"]["claim_check"], "words and numbers")
            trace = {t["claim"]: t for t in data["trace"]}
            used = [t for t in trace.values() if t["editions"]["en"]["lines"]]
            self.assertTrue(used)
            self.assertTrue(all(t["sources"] and t["editions"]["en"]["scenes"] for t in used))
            self.assertIn("I001 (usable)", " ".join(i for t in used for i in t["editions"]["en"]["images"]))
            cr = (proj / "reports" / "credits.md").read_text()
            self.assertIn('"First flight" by John T. Daniels, Public domain', cr); self.assertIn("https://www.loc.gov/item/x", cr)
            self.assertTrue((en / "out" / "credits.en.md").exists() and (hi / "out" / "credits.hi.md").exists())
            # an edition's QC turns incomplete: the report says so and fails
            finished_records(hi, "hi", complete=False)
            r = report.build(proj)
            self.assertTrue(any(e.startswith("hi: not complete (QC is not complete)") for e in r.errors), r.errors)
            # the fingerprint follows the inputs, not the report's own files
            h = report.fingerprint(proj, ["en", "hi"])
            self.assertEqual(h, report.fingerprint(proj, ["en", "hi"]))
            c = L.load(L.paths(proj)["claims"]); c["claims"][0]["notes"] = "rechecked"; L.save(L.paths(proj)["claims"], c)
            self.assertNotEqual(h, report.fingerprint(proj, ["en", "hi"]))

    def test_the_mix_is_judged_as_the_mix_stage_judged_it(self):
        import cuesheet
        with tempfile.TemporaryDirectory() as tmp:
            ed = pathlib.Path(tmp)
            L.save(ed / "audio" / "timing.json", {"total_duration": 12.0, "segments": []})
            base = {"duration": 12.0, "lufs": -15.0, "target_lufs": -15.0, "ceiling_dbtp": -1.5, "clipped_samples": 0}
            L.save(ed / "audio" / "mix_report.json", {**base, "true_peak_dbtp": -1.5 + cuesheet.TP_TOL - 0.2})   # CI measured -1.3
            self.assertEqual(report.audio_part(ed)["problems"], [])
            L.save(ed / "audio" / "mix_report.json", {**base, "true_peak_dbtp": -1.5 + cuesheet.TP_TOL + 0.1})
            self.assertTrue(any("over the" in x for x in report.audio_part(ed)["problems"]))
            L.save(ed / "audio" / "mix_report.json", {**base, "true_peak_dbtp": -2.0, "lufs": -15.0 - cuesheet.LOUDNESS_TOL - 0.1})
            self.assertTrue(any("LUFS" in x for x in report.audio_part(ed)["problems"]))

    def test_claim_to_line_warnings(self):
        self.assertLess(report.claim_match("The machine left the sand.", "The first flight lasted twelve seconds")[0], report.OVERLAP_WARN)
        share, extra = report.claim_match("The first flight lasted twelve seconds in 1903.", "The first flight lasted twelve seconds.")
        self.assertGreater(share, 0.9); self.assertEqual(extra, [1903])
        with tempfile.TemporaryDirectory() as tmp:
            proj, en, hi = through_gates(tmp)
            n = L.paths(en)["narration"]
            data = L.load(n)
            ln = next(x for s in data["sections"] for x in s["lines"] if x.get("claims"))
            ln["text"] = "Bananas are yellow and grow in bunches."                               # cites a claim it does not state
            L.save(n, data)
            notes = report.script_part(proj, "en", en)["notes"]
            self.assertTrue(any(x.startswith(f"line {ln['id']}: shares little with") for x in notes), notes)


@unittest.skipUnless(HAVE, "needs ffmpeg and numpy")
class Acknowledgement(unittest.TestCase):
    def test_automatic_picks_are_looked_at_before_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            L.save(proj / "00_topic" / "topic.json", {"topic": "t"})
            L.save(proj / "05_visuals" / "assets.json", {"assets": {
                "I001": {"need": "I001", "status": "ok", "auto": True, "what": "First flight", "license": {"label": "Public domain"}},
                "I002": {"need": "I002", "status": "ok", "auto": False, "what": "Chosen", "license": {"label": "CC0"}},
                "I003": {"need": "I003", "status": "fallback", "auto": False, "what": "Card", "fallback": {"reason": "x"}}}})
            self.assertEqual([n for n, _, _ in visuals.auto_picks(proj)], ["I001"])
            visuals.acknowledge(proj, ["I001"], log=lambda *a: None)
            self.assertEqual(visuals.auto_picks(proj), [])
            self.assertEqual(L.load(proj / "05_visuals" / "selection.json")["acknowledged"], ["I001"])
            with self.assertRaises(SystemExit):
                visuals.acknowledge(proj, ["I999"], log=lambda *a: None)

    def test_the_visuals_gate_refuses_unacknowledged_picks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp) / "doc"
            import test_editions as TE
            proj = TE.production(tmp)
            with mock.patch.object(visuals, "auto_picks", return_value=[("I001", "First flight", "Public domain")]):
                with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                    docpipe.approve(proj, "visuals")
            self.assertIn("visuals.py acknowledge", str(cm.exception)); self.assertIn("I001: First flight (Public domain)", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
