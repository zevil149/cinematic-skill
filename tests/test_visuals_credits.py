"""visuals.py credits.md follows an entry written by hand in photos.json that shadows a download
(Phase 7): the film credits that entry (rights.py), so credits.md must say the same, and a download
with no such entry keeps the archive's attribution. Offline."""
import os
import pathlib
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))

import doclib as L  # noqa: E402
import visuals  # noqa: E402


class Credits(unittest.TestCase):
    def test_hand_written_entries_are_credited(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            L.save(proj / "00_topic" / "topic.json", {"topic": "t"})
            lic = {"label": "Public domain", "policy": "free", "url": ""}
            base = {"status": "ok", "license": lic, "what": "Front page", "kind": "paper", "media": "image"}
            L.save(proj / "05_visuals" / "assets.json", {"assets": {
                "I001": {**base, "need": "I001", "file": "I001.jpg", "attribution": "\"x.jpg\" by not specified, Public domain", "shadowed": True},
                "I002": {**base, "need": "I002", "file": "I002.jpg", "attribution": "\"y.jpg\" by Someone, Public domain"},
                "I004": {**base, "need": "I004", "file": "I004.jpg", "attribution": "archive wording"},   # entry added after the fetch
                "I003": {"need": "I003", "status": "deferred", "what": "Front page", "fallback": {"reason": "rate limit"}}}})
            L.save(proj / "photos.json", {"photos": [
                {"id": "I001", "file": "I001.jpg", "credit": "The Daily, 1 May 1919", "license": "Public domain in the US (published 1919)",
                 "attribution": "Front page of The Daily, 1 May 1919. Public domain in the US (published 1919)."},
                {"id": "I002", "file": "I002.jpg", "credit": "ignored", "generated_by": "visuals.py", "attribution": "generated"},
                {"id": "I004", "file": "I004.jpg", "attribution": "Written after the download"}]})
            visuals.check(proj)
            md = (proj / "05_visuals" / "credits.md").read_text()
            self.assertIn("- I001: Front page of The Daily, 1 May 1919. Public domain in the US (published 1919). (as written in photos.json)", md)
            self.assertNotIn("not specified", md)
            self.assertIn("- I002: \"y.jpg\" by Someone, Public domain", md)
            self.assertIn("- I003: Front page", md.split("## Shown as designed cards")[1])
            self.assertIn("- I004: Written after the download (as written in photos.json)", md)


if __name__ == "__main__":
    unittest.main()
