"""Credits list each distinct asset once (Phase 8): the same file shown in several scenes is one
credit line on screen (credits.lines_for) and one entry in credits.md (report.credits_md); distinct
assets keep their own lines, in first-use order, with their full attribution. Offline."""
import os
import pathlib
import sys
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))

import credits  # noqa: E402
import report  # noqa: E402


def img(i, what, credit, lic, src):
    return {"id": i, "what": what, "credit": credit, "license": lic, "source": src, "usable": True,
            "attribution": f"{what}, {credit}, {lic}: {src}", "provider": "Wikimedia Commons", "cleared": None}


class Dedupe(unittest.TestCase):
    def setUp(self):
        p = img("I002", "Front page", "The Daily, 1 May 1919", "Public domain in the US (published 1919)", "https://x/page")
        q = img("I001", "Panorama", "A Library", "Public domain (not verified)", "https://x/pano")
        self.rep = {"images": [q, p, dict(p, id="I004"), dict(q, id="I010"), dict(p, id="I006")], "footage": [], "audio": [],
                    "maps": [], "narration": {"text": "espeak (hi)"}}

    def test_on_screen_lines(self):
        lines = credits.lines_for(self.rep, "hi")
        body = [t for k, t in lines if k == "line"]
        self.assertEqual(body, [credits.entry_text(self.rep["images"][0]), credits.entry_text(self.rep["images"][1]), "espeak (hi)"])
        self.assertIn("Public domain (not verified)", body[0])                     # the attribution is kept whole

    def test_credits_md(self):
        md = report.credits_md([("hi", self.rep)])
        self.assertEqual(md.count("- Front page:"), 1); self.assertEqual(md.count("- Panorama:"), 1)
        self.assertLess(md.index("- Panorama:"), md.index("- Front page:"))       # first-use order
        self.assertIn("Public domain (not verified)", md)


if __name__ == "__main__":
    unittest.main()
