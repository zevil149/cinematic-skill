"""Tests for optional milestone 6.6 (its offline part): voice spending that cannot overrun.

  * a gateway timeout (504) is not retried, and it, a dropped connection or a server error that
    outlasts the retries is raised as "may be billed"
  * such a failure is written to the edition's spend log ("failed, may be billed") and counts
    against the budget; a refusal (4xx) is not billed and is not written
  * the production has a cumulative budget across every run and edition (topic.json
    "voice_budget_usd", default voice.DEFAULT_BUDGET): a run that would pass it sends nothing

Offline: the paid providers talk to a fake network (as in test_voice_api). The live provider test
and an offline word aligner, the rest of 6.6, need separate approval and are not here.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["CINEMATIC_OFFLINE"] = "1"     # tests never reach the network

import pathlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import doclib as L  # noqa: E402
import voice  # noqa: E402
import voices as V  # noqa: E402
from test_voice import NOLOG  # noqa: E402
from test_voice_api import KEYS, api_editions, configure, el_api, http, sv_api  # noqa: E402


class Retries(unittest.TestCase):
    def test_what_may_have_run_is_not_retried_and_says_so(self):
        api = el_api(script=[(504, {}, b"{}")])
        h = http(api)
        with self.assertRaises(V.ProviderError) as cm:
            h.request("POST", "https://api.example/x", {}, {"text": "a"}, service="the API")
        self.assertTrue(cm.exception.maybe_billed); self.assertEqual(len(api.calls), 1)          # 504: sent once
        api = el_api(script=[ConnectionResetError("reset")])
        with self.assertRaises(V.ProviderError) as cm:
            http(api).request("POST", "https://api.example/x", {}, {"text": "a"})
        self.assertTrue(cm.exception.maybe_billed)
        api = el_api(script=[(503, {}, b"{}")] * 4)
        with self.assertRaises(V.ProviderError) as cm:
            http(api).request("POST", "https://api.example/x", {}, {"text": "a"})
        self.assertTrue(cm.exception.maybe_billed); self.assertEqual(len(api.calls), 4)          # retried, then given up
        api = el_api(script=[(401, {}, b'{"detail": "bad key"}')])
        with self.assertRaises(V.ProviderError) as cm:
            http(api).request("POST", "https://api.example/x", {}, {"text": "a"})
        self.assertFalse(cm.exception.maybe_billed)                                               # refused: not billed


class Budget(unittest.TestCase):
    def test_failed_requests_that_may_be_billed_are_logged_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, _ = api_editions(tmp)
            cfg = configure(en, {"mode": "line"})
            api = el_api(script=[(504, {}, b"{}")])
            r = voice.synth(en, only={1}, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertFalse(r.ok)
            log = L.load(en / "audio" / "voice" / "spend.json")["requests"]
            self.assertEqual([(x["what"], x["status"]) for x in log], [("line 1", "failed, may be billed")])
            self.assertGreater(log[0]["usd"], 0)
            self.assertGreater(voice.production_budget(voice.vp(en))[1], 0)                       # counted
            api = el_api(script=[(401, {}, b'{"detail": "bad key"}')])
            voice.synth(en, only={2}, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertEqual(len(L.load(en / "audio" / "voice" / "spend.json")["requests"]), 1)   # a refusal is not billed

    def test_the_production_budget_holds_across_runs_and_editions(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, KEYS):
            proj, en, hi, cfg, hcfg = api_editions(tmp)
            t = L.load(L.paths(proj)["topic"]); t["voice_budget_usd"] = 0.05; L.save(L.paths(proj)["topic"], t)
            L.save(hi / "audio" / "voice" / "spend.json", {"lang": "hi", "requests": [
                {"provider": "sarvam", "chars": 100, "usd": 0.049, "what": "line 1"}]})        # the other edition spent most of it
            api = el_api()
            r = voice.synth(en, provider=V.ElevenLabs(cfg, http=http(api)), confirm=True, **NOLOG)
            self.assertTrue(any("over its budget of $0.05" in e and "nothing was sent" in e for e in r.errors), r.errors)
            self.assertEqual(api.calls, [])
            t["voice_budget_usd"] = 1000; L.save(L.paths(proj)["topic"], t)
            self.assertTrue(voice.synth(en, provider=V.ElevenLabs(cfg, http=http(el_api())), confirm=True, **NOLOG).ok)
            budget, total = voice.production_budget(voice.vp(en))
            self.assertEqual(budget, 1000); self.assertGreater(total, 0.049)
            t.pop("voice_budget_usd"); L.save(L.paths(proj)["topic"], t)
            self.assertEqual(voice.production_budget(voice.vp(hi))[0], voice.DEFAULT_BUDGET)
            _ = sv_api, hcfg


if __name__ == "__main__":
    unittest.main()
