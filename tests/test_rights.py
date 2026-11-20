"""Tests for milestone 6.4: rights enforcement and on-screen credits (rights.py, credits.py,
finish.py render/join, qc.py).

  * only what the act scenes show, and what the mix used, is judged and credited
  * free licences as stated pass; a licence that needs clearing passes only with "cleared_by" and a
    note (recorded); a refused licence never passes; your own file needs the licence and credit you
    state; a scene showing a file with no rights record is blocked
  * a blocked asset stops the act render that would show it and blocks delivery
  * the closing credits are rendered in the edition's language and joined after the film; the
    film's length is the timeline plus the credits; QC and the delivery manifest carry the rights

Offline, on the tiny fixture. Needs skia-python, numpy and ffmpeg.
"""
import json
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

import doclib as L  # noqa: E402

try:
    import numpy as np
    import skia  # noqa: F401
    from PIL import Image
    HAVE = shutil.which("ffmpeg") is not None
except ImportError:                          # pragma: no cover
    HAVE = False

SIZE = "160x90"
QUIET = dict(log=lambda *a: None)


def with_photo(proj, entry, key="P1", act=1):
    """Put photo `key` on act `act`'s board, with `entry` as its photos.json record (None: no record)."""
    prep = proj / "assets" / "prep" / "photos"
    prep.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    Image.fromarray((rng.random((60, 80, 3)) * 255).astype(np.uint8)).save(prep / f"{key}.jpg")
    meta = L.load(prep / "meta.json", {}) if (prep / "meta.json").exists() else {}
    meta[key] = {"w": 80, "h": 60, "kind": "photo"}
    L.save(prep / "meta.json", meta)
    if entry is not None:
        pj = proj / "photos.json"
        data = L.load(pj, {"grade": "bw", "photos": []}) if pj.exists() else {"grade": "bw", "photos": []}
        data["photos"] = [e for e in data["photos"] if e.get("id") != key] + [{"id": key, **entry}]
        L.save(pj, data)
    sc = proj / "06_film" / f"act_{act:02d}" / "scene.py"
    src = sc.read_text()
    if f"Print({key!r}" not in src:
        sc.write_text(src.replace("    film.add(BigText(", f"    from engine import Print\n    film.add(Print({key!r}, -900, 300, 900, t_in=0.5))\n"
                                                         "    film.add(BigText(", 1))


def finish_all(proj):
    import finish
    import subtitles
    assert subtitles.build(proj, **QUIET).ok
    r = finish.render_acts(proj, SIZE, 2, **QUIET)
    j = finish.join(proj, **QUIET) if r.ok else None
    if j is not None and j.ok:
        L.save(proj / "captions.json", {"enabled": False}); finish.captions(proj, **QUIET)
    return r, j


CC_BY = {"commons": "File:Wright_First_Flight_1903Dec17.jpg", "what": "First flight", "credit": "John T. Daniels",
         "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0"}


@unittest.skipUnless(HAVE, "needs skia-python, numpy, Pillow and ffmpeg")
class Verdicts(unittest.TestCase):
    def verdict(self, entry, media="image", manifest=None):
        import rights
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            L.save(proj / "00_topic" / "topic.json", {"topic": "t"})
            if entry is not None:
                L.save(proj / "photos.json", {"photos": [{"id": "P1", **entry}]})
            if manifest is not None:
                L.save(proj / "05_visuals" / "assets.json", {"assets": {"P1": manifest}})
            return rights.verdict(rights.rp(proj), "P1", media)

    def test_the_documented_policy(self):
        self.assertTrue(self.verdict(CC_BY)["usable"])
        self.assertFalse(self.verdict({**CC_BY, "credit": ""})["usable"])                     # CC BY without an attribution
        nkr = {"url": "https://loc.gov/x", "license": "No known restrictions on publication", "credit": "LoC"}
        v = self.verdict(nkr)
        self.assertFalse(v["usable"]); self.assertIn("needs clearing", v["basis"])
        v = self.verdict({**nkr, "cleared_by": "A. Editor", "note": "LoC rights statement checked"})
        self.assertTrue(v["usable"]); self.assertEqual(v["cleared"]["cleared_by"], "A. Editor")
        nc = {"url": "https://x", "license": "CC BY-NC 4.0", "credit": "x", "cleared_by": "A. Editor", "note": "please"}
        self.assertFalse(self.verdict(nc)["usable"])                                            # refused: no override
        self.assertFalse(self.verdict({"file": "mine.jpg"})["usable"])                          # your own: state the rights
        v = self.verdict({"file": "mine.jpg", "license": "Own work", "credit": "Me"})
        self.assertTrue(v["usable"]); self.assertEqual(v["policy"], "own")
        v = self.verdict(None)
        self.assertFalse(v["usable"]); self.assertIn("no rights record", v["basis"])

    def test_the_visuals_manifest(self):
        free = {"need": "P1", "status": "ok", "what": "w", "license": {"label": "Public domain", "policy": "free"},
                "credit": "LoC", "provider": "loc", "attribution": "a"}
        v = self.verdict(None, manifest=free)
        self.assertTrue(v["usable"]); self.assertEqual(v["provider"], "Library of Congress")
        chk = dict(free, license={"label": "No known restrictions", "policy": "check"})
        self.assertFalse(self.verdict(None, manifest=chk)["usable"])
        self.assertTrue(self.verdict(None, manifest=dict(chk, cleared={"cleared_by": "B", "note": "n"}))["usable"])
        self.assertFalse(self.verdict(None, manifest=dict(free, status="fallback"))["usable"])
        # an entry you wrote in photos.json wins over the download, as visuals.py says
        v = self.verdict({"file": "mine.jpg"}, manifest=free)
        self.assertFalse(v["usable"]); self.assertIn("your own file needs", v["basis"])


@unittest.skipUnless(HAVE, "needs skia-python, numpy, Pillow and ffmpeg")
class Enforcement(unittest.TestCase):
    def test_an_uncleared_photo_blocks_its_act_and_the_delivery_until_cleared(self):
        import finish_fixture as F
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            nkr = {"url": "https://loc.gov/x", "what": "Hangar", "license": "No known restrictions", "credit": "LoC"}
            with_photo(proj, nkr, act=2)
            r, j = finish_all(proj)
            self.assertFalse(r.ok)
            self.assertTrue(any(e.startswith("act 2 is not rendered: it shows P1") for e in r.errors), r.errors)
            self.assertFalse((proj / "out" / "acts" / "act_02.mp4").exists())
            self.assertTrue((proj / "out" / "acts" / "act_01.mp4").exists())                    # the other act goes on
            rep = L.load(proj / "out" / "rights.en.json")
            self.assertEqual([(a["id"], a["usable"], a["acts"]) for a in rep["images"]], [("P1", False, [2])])
            # cleared, with a name and a note: rendered, credited, recorded, and QC says who cleared it
            with_photo(proj, {**nkr, "cleared_by": "A. Editor", "note": "LoC: no known restrictions, checked"}, act=2)
            r, j = finish_all(proj)
            self.assertTrue(r.ok and j.ok, (r.errors, j and j.errors))
            q = qc.build(proj, **QUIET)
            self.assertTrue(q.ok, q.errors)
            self.assertTrue(any(w.startswith("clearances: P1: cleared by A. Editor") for w in q.warnings), q.warnings)
            m = L.load(proj / "out" / "delivery.en.json")
            self.assertTrue(m["complete"])
            self.assertEqual(m["rights"]["assets"][0]["basis"], "cleared by A. Editor: LoC: no known restrictions, checked")
            self.assertIn("does not prove", m["rights"]["note"])
            # the clearance is withdrawn after delivery: QC blocks it again
            with_photo(proj, nkr, act=2)
            q = qc.build(proj, **QUIET)
            self.assertTrue(any(e.startswith("rights: image P1") for e in q.errors), q.errors)
            self.assertFalse(L.load(proj / "out" / "delivery.en.json")["complete"])

    def test_only_what_is_used_counts_and_audio_must_be_cleared(self):
        import rights
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp)
            with_photo(proj, CC_BY)
            data = L.load(proj / "photos.json")
            data["photos"].append({"id": "P9", "url": "https://x", "license": "CC BY-NC 4.0", "credit": "x"})   # listed, never shown
            L.save(proj / "photos.json", data)
            L.save(proj / "audio" / "mix_report.json", {"lang": "en", "target_lufs": -15, "assets": [
                {"id": "A1", "kind": "music", "title": "Theme", "creator": "C. Composer", "source": "own", "license": "CC BY 4.0",
                 "attribution": "Theme by C. Composer", "cleared_by": "audiolib", "override": False, "sha256": "x"},
                {"id": "A2", "kind": "sfx", "title": "Door", "creator": "", "source": "freesound", "license": "CC BY-NC 4.0",
                 "attribution": "", "cleared_by": "", "override": False, "sha256": "y"}]})
            r, rep = rights.check(proj)
            self.assertEqual([a["id"] for a in rep["images"]], ["P1"])                              # P9 is not used
            self.assertTrue(any("A2" in e and "not cleared" in e for e in r.errors), r.errors)
            self.assertFalse(any("A1" in e for e in r.errors))
            with mock.patch.object(rights, "used_in_scenes", return_value={"image": {}, "video": {}, "maps": 1, "unread": {}}):
                L.save(proj / "map.json", {"maps": [{"name": "us", "source": "https://cdn.example/states.json"}]})
                r, rep = rights.check(proj)
            self.assertTrue(any(w.startswith("map us: map.json records no licence") for w in r.warnings), r.warnings)


@unittest.skipUnless(HAVE, "needs skia-python, numpy, Pillow and ffmpeg")
class Credits(unittest.TestCase):
    def test_closing_credits_are_rendered_joined_and_checked(self):
        import credits
        import finish
        import finish_fixture as F
        import qc
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(tmp, acts=1)
            with_photo(proj, CC_BY)
            r, j = finish_all(proj)
            self.assertTrue(r.ok and j.ok, (r.errors, j and j.errors))
            st = L.load(proj / "out" / "finish.json")
            total = L.load(proj / "audio" / "timing.json")["total_duration"]
            cd = st["credits"]["duration"]
            self.assertGreaterEqual(cd, credits.MIN_SECS - 0.05)
            info = finish.probe(proj / "out" / "film.en.mp4")
            self.assertAlmostEqual(info["duration"], total + cd, delta=0.1)                       # the timeline, then the credits
            self.assertEqual((st["join"]["timeline"], st["join"]["credits"]), (round(total, 3), cd))
            # the credits frame shows text over the board; the film's end is untouched
            import subprocess
            def gray(t):
                out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(proj / "out" / "film.en.mp4"), "-frames:v", "1",
                                      "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True).stdout
                return np.frombuffer(out, np.uint8).astype(int)
            mid = gray(total + cd / 2)
            self.assertGreater(int((mid > 150).sum()), 20)                                        # light type on the dark board
            q = qc.build(proj, **QUIET)
            self.assertTrue(q.ok, q.errors)
            rep = L.load(proj / "out" / "qc.en.json")
            c = next(x for x in rep["checks"] if x["check"] == "credits")
            self.assertTrue(c["ok"]); self.assertIn("credit line(s)", c["message"])
            files = {f["kind"] for f in L.load(proj / "out" / "delivery.en.json")["files"]}
            self.assertTrue({"rights", "credits sequence"} <= files)
            # resume: nothing renders again
            stamp = (proj / "out" / "credits.en.mp4").stat().st_mtime_ns
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertTrue(any("credits: up to date" in n for n in r.notes), r.notes)
            self.assertEqual((proj / "out" / "credits.en.mp4").stat().st_mtime_ns, stamp)
            # credits off: no sequence, a warning, still deliverable
            L.save(proj / "credits.json", {"enabled": False})
            r = finish.render_acts(proj, SIZE, 2, **QUIET)
            self.assertTrue(any("turns the closing credits off" in w for w in r.warnings))
            self.assertTrue(finish.join(proj, **QUIET).ok)
            self.assertAlmostEqual(finish.probe(proj / "out" / "film.en.mp4")["duration"], total, delta=0.1)
            q = qc.build(proj, **QUIET)
            self.assertTrue(q.ok, q.errors)
            self.assertTrue(any(w.startswith("credits: credits.json turns") for w in q.warnings), q.warnings)

    def test_hindi_credits_and_nothing_to_credit(self):
        import credits
        import rights
        import finish_fixture as F
        with tempfile.TemporaryDirectory() as tmp:
            proj = F.make(pathlib.Path(tmp) / "a")
            _, rep = rights.check(proj)
            self.assertEqual(credits.lines_for(rep, "en"), [])                                    # designed type only: no credits
            proj = F.make(pathlib.Path(tmp) / "b", code="hi", edition=True)
            with_photo(proj, CC_BY)
            _, rep = rights.check(proj)
            lines = credits.lines_for(rep, "hi")
            self.assertEqual(lines[0], ("title", "आभार")); self.assertEqual(lines[1], ("head", "तस्वीरें और दस्तावेज़"))
            self.assertIn("John T. Daniels", lines[2][1]); self.assertIn("CC BY-SA 4.0", lines[2][1])
            film, dur = credits.build_film(lines, "wall")
            self.assertEqual(dur, credits.MIN_SECS)


if __name__ == "__main__":
    unittest.main()
