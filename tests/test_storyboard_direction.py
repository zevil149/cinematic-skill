"""Tests for 04_scenes/direction.json, the storyboard's hand-written direction (Phase 7 production):

  * a key-word override replaces the automatic landing word when it is a word of the spoken line,
    and is ignored with a warning otherwise (or for a line that is not in the script)
  * a designed graphic's on-screen label is carried into the storyboard and its review table, and
    a label in the wrong script for the edition is flagged
  * the overrides survive a rebuild, and the scenes stage reruns when direction.json changes

Offline, on the editions fixture.
"""
import os
import pathlib
import sys
import tempfile
import unittest

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import beats  # noqa: E402
import docpipe  # noqa: E402
import doclib as L  # noqa: E402
import storyboard  # noqa: E402
from test_editions import production, write_english, write_hindi  # noqa: E402


class Direction(unittest.TestCase):
    def test_overrides_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            write_english(proj)
            beats.build(proj, log=lambda *a: None)
            hi = write_hindi(proj)
            self.assertTrue(storyboard.build(hi).ok)
            sb = L.load(L.paths(hi)["storyboard"])["scenes"]
            first = sb[0]
            self.assertEqual(first["narration"], "राइट बंधुओं का विमान रेत से ऊपर उठा।")
            self.assertNotEqual(first["key_word"], "विमान")
            L.save(L.paths(hi)["direction"], {"key_words": {str(first["line"]): "विमान", str(sb[1]["line"]): "हवाई", "999": "x"},
                                              "graphics": {str(first["line"]): {"label": "चित्रण", "note": "designed"},
                                                           str(sb[1]["line"]): {"label": "Illustration"}}})
            r = storyboard.build(hi)
            sb = L.load(L.paths(hi)["storyboard"])["scenes"]
            self.assertEqual(sb[0]["key_word"], "विमान")
            self.assertEqual(sb[0]["graphic"], {"label": "चित्रण", "note": "designed"})
            self.assertTrue(any("'हवाई' (direction.json) is not a word" in w for w in r.warnings), r.warnings)
            self.assertTrue(any("line 999 is not in the script" in w for w in r.warnings), r.warnings)
            self.assertTrue(any("graphic label 'Illustration'" in w for w in r.warnings), r.warnings)
            self.assertIn("[illustrative, labelled on screen: चित्रण]", L.paths(hi)["storyboard_md"].read_text())
            storyboard.build(hi)                                                   # a rebuild keeps them
            self.assertEqual(L.load(L.paths(hi)["storyboard"])["scenes"][0]["key_word"], "विमान")

    def test_the_scenes_stage_follows_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = production(tmp)
            steps = {name: inputs for name, _, _, inputs, _ in docpipe.edition_steps(proj, ["en", "hi"])}
            hi_dir = L.paths(proj / "editions" / "hi")["direction"]
            self.assertIn(hi_dir, steps["scenes@hi"]())


if __name__ == "__main__":
    unittest.main()
