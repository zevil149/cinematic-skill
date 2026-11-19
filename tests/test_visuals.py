"""Tests for the visual engine's archive layer and asset matching (phase 2, stages 2.1 and 2.2).

No network: a fake opener answers with small synthetic responses shaped like each archive's API.
These are test fixtures, not real records; nothing here is presented as a real source.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import archives as A  # noqa: E402
import doclib as L  # noqa: E402
import visuals as V  # noqa: E402
from test_docpipe import add_research, fill_narration, fill_outline, make_project, quiet  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000


class Resp(io.BytesIO):
    def __init__(self, body, ctype="application/json"):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.headers = {"Content-Type": ctype}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code, retry_after=None):
    hdrs = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError(url, code, "Too Many Requests", hdrs, None)


class FakeNet:
    """Routes by host. A route is a callable(url) -> Resp, or an exception to raise."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(url)
        for key, fn in self.routes.items():
            if key in url:
                r = fn(url)
                if isinstance(r, Exception):
                    raise r
                return r
        raise urllib.error.URLError(f"no route for {url}")


class Clock:
    def __init__(self):
        self.t = 1_000_000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s); self.t += s


def commons_page(title, lic, url_lic="", w=3000, h=2000, mime="image/jpeg", desc="", artist="Someone"):
    return {"title": f"File:{title}", "index": 1, "imageinfo": [{
        "url": f"https://upload.wikimedia.org/x/{title}", "thumburl": f"https://upload.wikimedia.org/thumb/x/1920px-{title}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}", "width": w, "height": h, "mime": mime,
        "extmetadata": {"LicenseShortName": {"value": lic}, "LicenseUrl": {"value": url_lic},
                        "Artist": {"value": f"<a href='#'>{artist}</a>"}, "ImageDescription": {"value": desc}}}]}


COMMONS = {"query": {"pages": [
    commons_page("First flight 1903.jpg", "Public domain", desc="Wright first flight 1903"),
    commons_page("Flyer replica.jpg", "CC BY-NC 2.0", "https://creativecommons.org/licenses/by-nc/2.0/", desc="Wright first flight replica"),
    commons_page("Kitty Hawk dunes.jpg", "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0", w=600, h=400, desc="dunes"),
    commons_page("Glider test.webm", "Public domain", mime="video/webm", desc="Wright glider film"),
]}}
LOC_JSON = {"results": [{"id": "http://www.loc.gov/item/x1/", "url": "https://www.loc.gov/item/x1/", "title": "Wright first flight 1903",
                         "image_url": ["https://tile.loc.gov/x1/150px.jpg", "https://tile.loc.gov/x1/full.jpg#h=1800&w=2400"],
                         "item": {"rights_advisory": ["No known restrictions on publication."], "creator": "Daniels"}}]}
OPENVERSE = {"results": [{"id": "abc", "title": "Wright Flyer first flight 1903", "foreign_landing_url": "https://www.flickr.com/x",
                          "url": "https://live.staticflickr.com/x.jpg", "creator": "A Photographer", "license": "by-sa",
                          "license_version": "2.0", "license_url": "https://creativecommons.org/licenses/by-sa/2.0/",
                          "width": 2048, "height": 1365, "filetype": "jpg"}]}


class Licences(unittest.TestCase):
    def test_policies(self):
        free = ["Public domain", "PD-US", "CC0", "CC BY 4.0", "CC BY-SA 3.0", "pdm"]
        check = ["No known restrictions on publication.", "Copyrighted free use"]
        refuse = ["CC BY-NC 2.0", "cc by-nd 4.0", "All rights reserved", "", "some custom terms"]
        for s in free:
            self.assertEqual(A.normalize_license(s)["policy"], "free", s)
        for s in check:
            self.assertEqual(A.normalize_license(s)["policy"], "check", s)
        for s in refuse:
            self.assertEqual(A.normalize_license(s)["policy"], "refuse", s)
        self.assertEqual(A.normalize_license("", "http://rightsstatements.org/vocab/InC/1.0/")["policy"], "refuse")
        self.assertEqual(A.normalize_license("", "http://creativecommons.org/publicdomain/zero/1.0/")["code"], "CC0")
        self.assertEqual(A.normalize_license("CC BY-SA 4.0")["label"], "CC BY-SA 4.0")

    def test_attribution_and_secrets(self):
        c = A.candidate("commons", "File:X.jpg", "X", "https://commons.wikimedia.org/wiki/File:X.jpg", "https://u/x.jpg",
                        A.normalize_license("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0"), creator="<b>Jane</b>")
        self.assertIn('"X" by Jane, CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0), via Wikimedia Commons', c["attribution"])
        self.assertNotIn("SECRET", A.strip_secrets("https://api.si.edu/s?q=a&api_key=SECRET&wskey=SECRET2"))


class Http(unittest.TestCase):
    def test_pacing_cache_and_retry_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            n = {"k": 0}

            def flaky(url):
                n["k"] += 1
                return http_error(url, 429, 5) if n["k"] == 1 else Resp({"ok": True})
            net = FakeNet({"example.org": flaky})
            h = A.Http(state_path=pathlib.Path(tmp) / "s.json", cache_dir=pathlib.Path(tmp) / "c", opener=net,
                       sleep=clock.sleep, now=clock.now, log=lambda *a: None, min_interval=1.0)
            self.assertEqual(h.get_json("https://example.org/a?q=1"), {"ok": True})
            self.assertIn(5.0, clock.slept)                       # honoured Retry-After
            self.assertEqual(h.get_json("https://example.org/a?q=1"), {"ok": True})
            self.assertEqual(len(net.calls), 2)                   # second answer came from the cache

    def test_cooldown_is_remembered_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            net = FakeNet({"example.org": lambda u: http_error(u, 429, 600)})
            mk = lambda: A.Http(state_path=pathlib.Path(tmp) / "s.json", opener=net, sleep=clock.sleep, now=clock.now,
                                log=lambda *a: None, max_wait=60, cooldown=900)
            with self.assertRaises(A.RateLimited):
                mk().get_json("https://example.org/a", cache=False)
            self.assertEqual(len(net.calls), 1)                   # a long Retry-After: no retry storm
            with self.assertRaises(A.RateLimited):
                mk().get_json("https://example.org/b", cache=False)     # a new run, same project
            self.assertEqual(len(net.calls), 1)                   # cooling: not a single request
            clock.t += 1000
            with self.assertRaises(A.RateLimited):
                mk().get_json("https://example.org/c", cache=False)
            self.assertEqual(len(net.calls), 2)                   # cooldown over: one new try

    def test_download_resume_and_html_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = FakeNet({"img.org/ok": lambda u: Resp(JPEG, "image/jpeg"), "img.org/page": lambda u: Resp(b"<html>", "text/html")})
            h = A.Http(opener=net, sleep=lambda s: None, log=lambda *a: None)
            dst = pathlib.Path(tmp) / "a.jpg"
            h.download("https://img.org/ok.jpg", dst)
            h.download("https://img.org/ok.jpg", dst)
            self.assertEqual(len(net.calls), 1)                   # kept, not downloaded again
            with self.assertRaises(ValueError):
                h.download("https://img.org/page", pathlib.Path(tmp) / "b.jpg")
            self.assertFalse((pathlib.Path(tmp) / "b.jpg").exists())


class Providers(unittest.TestCase):
    def setUp(self):
        self.net = FakeNet({"commons.wikimedia.org": lambda u: Resp(COMMONS), "www.loc.gov": lambda u: Resp(LOC_JSON),
                            "api.openverse.org": lambda u: Resp(OPENVERSE)})
        self.http = A.Http(opener=self.net, sleep=lambda s: None, log=lambda *a: None)

    def test_commons_images_and_video(self):
        imgs = A.Commons(self.http).search("Wright first flight")
        self.assertEqual([c["license"]["policy"] for c in imgs], ["free", "refuse", "free"])
        self.assertTrue(imgs[0]["media_url"].endswith("1920px-First flight 1903.jpg"))   # standard thumbnail, not the original
        self.assertEqual(imgs[0]["creator"], "Someone")
        vids = A.Commons(self.http).search("Wright glider", media="video")
        self.assertEqual([c["media"] for c in vids], ["video"])
        self.assertIn("filetype%3Avideo", self.net.calls[-1])

    def test_loc_and_openverse(self):
        loc = A.LOC(self.http).search("Wright")[0]
        self.assertEqual((loc["license"]["policy"], loc["width"], loc["media_url"]), ("check", 2400, "https://tile.loc.gov/x1/full.jpg"))
        ov = A.Openverse(self.http).search("Wright")[0]
        self.assertEqual(ov["license"]["label"], "CC BY-SA 2.0")
        self.assertIn("license=cc0%2Cpdm%2Cby%2Cby-sa", self.net.calls[-1])

    def test_keyed_providers_need_their_key(self):
        os.environ.pop("SI_API_KEY", None); os.environ.pop("EUROPEANA_API_KEY", None)
        self.assertFalse(A.Smithsonian(self.http).available())
        self.assertFalse(A.Europeana(self.http).available())
        os.environ["EUROPEANA_API_KEY"] = "test-key"
        try:
            seen = {}

            def eu(url):
                seen["url"] = url
                return Resp({"items": [{"id": "/1/x", "title": ["Flyer"], "guid": "https://www.europeana.eu/item/1/x",
                                        "edmIsShownBy": ["https://media.example/x.jpg"], "rights": ["http://creativecommons.org/publicdomain/mark/1.0/"]}]})
            net = FakeNet({"api.europeana.eu": eu})
            c = A.Europeana(A.Http(opener=net, sleep=lambda s: None)).search("Flyer")[0]
            self.assertEqual(c["license"]["code"], "PD")
            self.assertNotIn("test-key", seen["url"])            # the key travels in a header, not the url
        finally:
            os.environ.pop("EUROPEANA_API_KEY", None)


def project_with_needs(tmp):
    proj = make_project(tmp)
    add_research(proj)
    import narration
    import outline
    import storyboard
    quiet(outline.init, proj); fill_outline(proj)
    quiet(narration.init, proj); fill_narration(proj)
    n = L.load(L.paths(proj)["narration"])
    n["sections"][1]["lines"][1]["images"] = [{"what": "Wright glider film", "kind": "footage", "query": "Wright glider"}]
    L.save(L.paths(proj)["narration"], n)
    storyboard.build(proj)
    return proj


def fake_archives():
    return FakeNet({"commons.wikimedia.org": lambda u: Resp(COMMONS), "www.loc.gov": lambda u: Resp(LOC_JSON),
                    "api.openverse.org": lambda u: Resp(OPENVERSE), "upload.wikimedia.org": lambda u: Resp(JPEG, "image/jpeg"),
                    "live.staticflickr.com": lambda u: Resp(JPEG, "image/jpeg")})


class Matching(unittest.TestCase):
    def test_search_select_fetch_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project_with_needs(tmp)
            net = fake_archives()
            http = V.make_http(proj); http.opener = net; http.sleep = lambda s: None; http.log = lambda *a: None
            r = V.run(proj, http=http, providers=["commons", "loc", "openverse"], log=lambda *a: None)
            self.assertTrue(r.ok, r.errors)
            p = V.vpaths(proj)
            man = L.load(p["assets"])["assets"]
            self.assertEqual(len(man), 10)
            ok = [a for a in man.values() if a["status"] == "ok"]
            self.assertTrue(ok)
            self.assertTrue(all(a["license"]["policy"] == "free" for a in ok))
            self.assertTrue(all("NC" not in a["license"]["label"] for a in ok))
            video = [a for a in man.values() if a["media"] == "video"]
            self.assertEqual(video[0]["status"], "ok")
            self.assertTrue((p["proj"] / "assets" / "footage" / video[0]["file"]).exists())
            photos = L.load(p["photos_json"])["photos"]
            self.assertTrue(all(e["generated_by"] == "visuals.py" and e["license_ok"] for e in photos))
            self.assertFalse(any(e["file"].endswith(".webm") for e in photos))     # footage stays out of photos.json
            self.assertEqual(len(L.load(p["footage_json"])["footage"]), 1)
            self.assertIn("via Wikimedia Commons", p["credits_md"].read_text())
            # searches are cached: a second run asks the archives nothing new
            before = len(net.calls)
            V.run(proj, http=http, providers=["commons", "loc", "openverse"], log=lambda *a: None)
            self.assertEqual(len(net.calls), before)

    def test_check_licence_needs_clearing_and_selection_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project_with_needs(tmp)
            http = V.make_http(proj); http.opener = fake_archives(); http.sleep = lambda s: None; http.log = lambda *a: None
            V.search(proj, http, ["loc"], log=lambda *a: None)
            picks = V.select(proj)
            self.assertTrue(all("fallback" in pk for pk in picks.values()))     # LOC "no known restrictions" is never auto-used
            p = V.vpaths(proj)
            cid = L.load(p["candidates"])["needs"]["I001"]["candidates"][0]["id"]
            L.save(p["selection"], {"I001": cid, "I002": {"candidate": cid, "cleared_by": "Z", "note": "LOC rights page checked"},
                                    "I004": "fallback"})
            picks = V.select(proj)
            self.assertIn("needs clearing", picks["I001"]["fallback"])
            self.assertEqual(picks["I002"]["candidate"]["id"], cid)
            self.assertIn("no free candidate", picks["I005"]["fallback"])
            self.assertEqual(picks["I004"], {"fallback": "chosen in selection.json"})

    def test_rate_limit_defers_with_fallback_and_never_spams(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project_with_needs(tmp)
            net = FakeNet({"commons.wikimedia.org": lambda u: http_error(u, 429, 600)})
            http = V.make_http(proj); http.opener = net; http.sleep = lambda s: None; http.log = lambda *a: None
            r = V.run(proj, http=http, providers=["commons"], log=lambda *a: None)
            self.assertTrue(r.ok)
            self.assertEqual(len(net.calls), 1)                   # one refusal, then the host is left alone
            man = L.load(V.vpaths(proj)["assets"])["assets"]
            self.assertTrue(all(a["status"] == "fallback" and a["fallback"]["type"] == "card" for a in man.values()))
            self.assertTrue(any("rate-limiting" in a["fallback"]["reason"] for a in man.values()))

    def test_offline_and_failed_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project_with_needs(tmp)
            r = V.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            self.assertTrue(r.ok)
            net = FakeNet({"commons.wikimedia.org": lambda u: Resp(COMMONS), "upload.wikimedia.org": lambda u: Resp(b"<html>", "text/html")})
            http = V.make_http(proj); http.opener = net; http.sleep = lambda s: None; http.log = lambda *a: None
            V.run(proj, http=http, providers=["commons"], log=lambda *a: None)
            man = L.load(V.vpaths(proj)["assets"])["assets"]
            self.assertTrue(any("download failed" in a.get("fallback", {}).get("reason", "") for a in man.values()))
            self.assertFalse(list((V.vpaths(proj)["proj"] / "assets" / "photos").glob("*.part")))

    def test_own_files_need_rights_and_user_entries_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = project_with_needs(tmp)
            p = V.vpaths(proj)
            (p["proj"] / "assets" / "photos" / "mine.jpg").write_bytes(JPEG)
            nb = L.load(p["image_needs"])
            nb["images"][0].update(kind="own", file="mine.jpg")
            nb["images"][2].update(kind="own", file="mine.jpg", license="Taken by the author, all rights held", credit="Z")
            L.save(p["image_needs"], nb)
            L.save(p["photos_json"], {"grade": "bw", "photos": [{"id": "I005", "file": "hand.jpg", "kind": "photo"}]})
            V.run(proj, offline=True, providers=["commons"], log=lambda *a: None)
            man = L.load(p["assets"])["assets"]
            self.assertEqual(man["I001"]["status"], "fallback")
            self.assertEqual(man["I003"]["status"], "own")
            photos = {e["id"]: e for e in L.load(p["photos_json"])["photos"]}
            self.assertEqual(photos["I005"], {"id": "I005", "file": "hand.jpg", "kind": "photo"})
            self.assertEqual(photos["I003"]["license"], "Taken by the author, all rights held")


if __name__ == "__main__":
    unittest.main()
