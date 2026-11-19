"""Legal visual sources behind one interface: search archives for images and footage, record the
licence and attribution each archive states, and download with polite rate limiting.

Providers (all return the same candidate dict):
  commons      Wikimedia Commons: images and video (WebM, Ogg). No key.
  loc          Library of Congress (loc.gov JSON API): photos, prints, maps. No key.
  openverse    Openverse (CC-licensed and public-domain images from many archives). No key.
  smithsonian  Smithsonian Open Access, CC0 items only. Key: SI_API_KEY (api.data.gov).
  europeana    Europeana, open-reuse items only. Key: EUROPEANA_API_KEY.

Keys come only from the environment (or the cloud proxy that injects them); they are never written
to a project file, a cache key or a log line.

Licences are read from what the archive states and normalised; nothing is guessed:
  free     public domain, CC0, CC BY, CC BY-SA: usable with attribution
  check    "no known restrictions" and similar: a person must clear it before use
  refuse   NC, ND, in copyright, all rights reserved, or no licence stated
"""
import hashlib
import html
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "cinematic-film/1.0 (+https://github.com/Moh4696/cinematic-skill)"
SECRET_PARAMS = {"api_key", "wskey", "key", "token", "access_token"}


# ------------------------------------------------------------------------------------ licences

def normalize_license(raw="", url=""):
    """{"code", "label", "version", "url", "policy"} from an archive's licence text and/or url."""
    text = f"{raw or ''} {url or ''}"
    s = text.lower()
    ver = re.search(r"(\d\.\d)", s)
    ver = ver.group(1) if ver else ""

    def out(code, label, policy):
        return {"code": code, "label": label + (f" {ver}" if ver and code.startswith("CC-BY") else ""),
                "version": ver, "url": url or "", "policy": policy, "raw": (raw or "").strip()}

    if not s.strip():
        return out("UNKNOWN", "no licence stated", "refuse")
    if "copyrighted free use" in s:
        return out("FREE-USE", "Copyrighted free use", "check")
    if re.search(r"by-nc|noncommercial|non-commercial|\bnc\b|/inc/|in copyright|all rights reserved|copyrighted", s):
        return out("RESTRICTED", "non-commercial or in copyright", "refuse")
    if re.search(r"by-nd|-nd\b|noderiv|no deriv|\bnd\b", s):
        return out("RESTRICTED", "no derivatives", "refuse")
    if re.search(r"cc0|publicdomain/zero|zero/1\.0", s):
        return out("CC0", "CC0", "free")
    if re.search(r"public domain|publicdomain/mark|\bpdm\b|^pd\b|\bpd-|vocab/noc-us|no copyright", s):
        return out("PD", "Public domain", "free")
    if re.search(r"no known (copyright )?restrictions|vocab/nkc|no known copyright", s):
        return out("NKR", "No known restrictions", "check")
    if re.search(r"by-sa|by_sa|attribution-sharealike|share ?alike", s):
        return out("CC-BY-SA", "CC BY-SA", "free")
    if re.search(r"\bcc[- ]?by\b|/licenses/by/|\bby\b \d\.\d|attribution", s) or s.strip() in ("by", "cc by"):
        return out("CC-BY", "CC BY", "free")
    return out("UNKNOWN", "licence not recognised", "refuse")


def attribution(c):
    """One credit line: "Title" by Creator, Licence (url), via Provider: page."""
    who = f" by {c['creator']}" if c.get("creator") else ""
    lic = c["license"]
    lic_txt = lic["label"] + (f" ({lic['url']})" if lic.get("url") else "")
    return f"\"{c.get('title') or 'Untitled'}\"{who}, {lic_txt}, via {PROVIDER_NAMES.get(c['provider'], c['provider'])}: {c.get('page_url', '')}"


def clean(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("value") or v.get("content") or ""
    return html.unescape(re.sub(r"<[^>]+>", "", str(v or ""))).strip()


def strip_secrets(url):
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k.lower() not in SECRET_PARAMS]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


# ----------------------------------------------------------------------------------------- http

class Offline(Exception):
    """No network: --offline, or CINEMATIC_OFFLINE=1 in the environment (the test suites set it)."""


class RateLimited(Exception):
    def __init__(self, host, until):
        super().__init__(f"{host} is rate-limiting us; cooling down until {time.strftime('%H:%M:%S', time.localtime(until))}")
        self.host, self.until = host, until


class Http:
    """Polite HTTP: a minimum gap between requests to each host, Retry-After honoured, a cooldown
    remembered across runs (state file) once a host keeps refusing, and a disk cache for searches.
    A host that is cooling down gets no request at all until the cooldown ends."""

    def __init__(self, state_path=None, cache_dir=None, min_interval=1.0, max_tries=4, max_wait=60.0,
                 cooldown=900.0, cache_ttl=7 * 86400, opener=None, sleep=time.sleep, now=time.time, log=print):
        self.state_path = pathlib.Path(state_path) if state_path else None
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else None
        self.min_interval, self.max_tries, self.max_wait, self.cooldown = min_interval, max_tries, max_wait, cooldown
        self.cache_ttl = cache_ttl
        self.opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
        if opener is None and os.environ.get("CINEMATIC_OFFLINE") == "1":
            self.opener = self._offline
        self.sleep, self.now, self.log = sleep, now, log
        self.last = {}
        self.requests = 0
        self.state = json.loads(self.state_path.read_text()) if self.state_path and self.state_path.exists() else {"cooling": {}}

    @staticmethod
    def _offline(req, timeout):
        raise Offline("CINEMATIC_OFFLINE=1: no network requests")

    def _save_state(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.state, indent=1))

    def cooling(self, host):
        until = self.state["cooling"].get(host, 0)
        return until if until > self.now() else 0

    def _pace(self, host):
        wait = self.last.get(host, -1e9) + self.min_interval - self.now()
        if wait > 0:
            self.sleep(wait)
        self.last[host] = self.now()

    def _request(self, url, headers=None, timeout=60):
        host = urllib.parse.urlsplit(url).hostname or ""
        until = self.cooling(host)
        if until:
            raise RateLimited(host, until)
        for attempt in range(self.max_tries):
            self._pace(host)
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            try:
                self.requests += 1
                return self.opener(req, timeout)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 503):
                    raise
                ra = (e.headers.get("Retry-After", "") if e.headers else "") or ""
                wait = float(ra) if ra.strip().isdigit() else 2.0 * 2 ** attempt
                if wait > self.max_wait or attempt == self.max_tries - 1:
                    until = self.now() + max(wait, self.cooldown)
                    self.state["cooling"][host] = until
                    self._save_state()
                    raise RateLimited(host, until)
                self.log(f"  {host} asked us to wait ({e.code}); waiting {wait:.0f}s")
                self.sleep(wait)

    def get_json(self, url, headers=None, cache=True):
        key = hashlib.sha256(strip_secrets(url).encode()).hexdigest()[:24]
        cp = self.cache_dir / f"{key}.json" if (self.cache_dir and cache) else None
        if cp and cp.exists():
            d = json.loads(cp.read_text())
            if self.now() - d.get("at", 0) < self.cache_ttl:
                return d["data"]
        with self._request(url, headers) as r:
            data = json.loads(r.read())
        if cp:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps({"at": self.now(), "url": strip_secrets(url), "data": data}))
        return data

    def download(self, url, dst, headers=None, max_bytes=400 * 2 ** 20):
        """Download to dst through dst.part; an existing dst is kept (resume across runs)."""
        dst = pathlib.Path(dst)
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")
        with self._request(url, headers, timeout=180) as r:
            ctype = (r.headers.get("Content-Type", "") if getattr(r, "headers", None) else "") or ""
            if ctype.startswith("text/html"):
                raise ValueError(f"{strip_secrets(url)} returned a web page, not media")
            with open(part, "wb") as f:
                n = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > max_bytes:
                        raise ValueError(f"{strip_secrets(url)} is larger than {max_bytes >> 20} MB")
                    f.write(chunk)
        if part.stat().st_size == 0:
            part.unlink()
            raise ValueError(f"{strip_secrets(url)} returned nothing")
        part.replace(dst)
        return dst


# ------------------------------------------------------------------------------------ providers

def candidate(provider, pid, title, page_url, media_url, license, media="image", **kw):
    c = {"provider": provider, "id": f"{provider}:{pid}", "title": clean(title)[:200], "page_url": page_url,
         "media_url": media_url, "media": media, "license": license, "creator": clean(kw.pop("creator", ""))[:120],
         "width": kw.pop("width", None), "height": kw.pop("height", None), "mime": kw.pop("mime", ""),
         "date": clean(kw.pop("date", ""))[:40], "description": clean(kw.pop("description", ""))[:300]}
    c.update(kw)
    c["attribution"] = attribution(c)
    return c


class Provider:
    name = ""
    key_env = None
    media = ("image",)

    def __init__(self, http):
        self.http = http

    @property
    def key(self):
        return os.environ.get(self.key_env, "") if self.key_env else ""

    def available(self):
        return not self.key_env or bool(self.key)

    def search(self, query, media="image", limit=8):
        raise NotImplementedError


class Commons(Provider):
    name = "commons"
    media = ("image", "video")
    API = "https://commons.wikimedia.org/w/api.php"
    WIDTH = 1920            # a standard thumbnail size, and all a 1080p film can show

    def search(self, query, media="image", limit=8):
        ft = "filetype:video" if media == "video" else "filetype:bitmap"
        params = dict(action="query", generator="search", gsrsearch=f"{query} {ft}", gsrnamespace=6, gsrlimit=limit,
                      prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=self.WIDTH, format="json", formatversion=2)
        d = self.http.get_json(self.API + "?" + urllib.parse.urlencode(params))
        out = []
        for p in sorted((d.get("query") or {}).get("pages", []), key=lambda p: p.get("index", 0)):
            ii = (p.get("imageinfo") or [{}])[0]
            md = ii.get("extmetadata", {})
            mime = ii.get("mime", "")
            is_video = mime.startswith("video/") or mime in ("application/ogg",)
            if (media == "video") != is_video:
                continue
            lic = normalize_license(clean(md.get("LicenseShortName")) or clean(md.get("UsageTerms")), clean(md.get("LicenseUrl")))
            url = ii.get("url", "")
            if not is_video and ii.get("thumburl") and (ii.get("width") or 0) > self.WIDTH:
                url = ii["thumburl"]
            out.append(candidate("commons", p.get("title", "").replace(" ", "_"), p.get("title", "").removeprefix("File:"),
                                 ii.get("descriptionurl", ""), url, lic, "video" if is_video else "image",
                                 creator=md.get("Artist") or md.get("Credit"), width=ii.get("width"), height=ii.get("height"),
                                 mime=mime, date=md.get("DateTimeOriginal") or md.get("DateTime"),
                                 description=md.get("ImageDescription"), duration=ii.get("duration")))
        return out


class LOC(Provider):
    name = "loc"
    API = "https://www.loc.gov/photos/"

    def search(self, query, media="image", limit=8):
        if media != "image":
            return []
        d = self.http.get_json(self.API + "?" + urllib.parse.urlencode({"q": query, "fo": "json", "c": limit}))
        out = []
        for r in d.get("results", []):
            urls = [u for u in r.get("image_url", []) if u]
            if not urls:
                continue
            best = urls[-1]
            w = h = None
            m = re.search(r"#h=(\d+)&w=(\d+)", best)
            if m:
                h, w = int(m.group(1)), int(m.group(2))
            best = best.split("#")[0]
            if best.startswith("//"):
                best = "https:" + best
            item = r.get("item") or {}
            rights = item.get("rights_advisory") or r.get("rights_advisory") or item.get("rights") or r.get("rights") or ""
            lic = normalize_license(clean(rights))
            out.append(candidate("loc", r.get("id", best), r.get("title"), r.get("url") or r.get("id", ""), best, lic,
                                 creator=item.get("creator") or (r.get("contributor") or [""])[0], width=w, height=h,
                                 date=r.get("date", ""), description=r.get("description")))
        return out


class Openverse(Provider):
    name = "openverse"
    API = "https://api.openverse.org/v1/images/"

    def search(self, query, media="image", limit=8):
        if media != "image":
            return []
        d = self.http.get_json(self.API + "?" + urllib.parse.urlencode(
            {"q": query, "page_size": limit, "license": "cc0,pdm,by,by-sa", "mature": "false"}))
        out = []
        for r in d.get("results", []):
            raw = f"{r.get('license', '')} {r.get('license_version', '')}".strip()
            lic = normalize_license("cc " + raw if r.get("license") not in ("cc0", "pdm") else raw, r.get("license_url", ""))
            out.append(candidate("openverse", r.get("id"), r.get("title"), r.get("foreign_landing_url", ""), r.get("url", ""), lic,
                                 creator=r.get("creator"), width=r.get("width"), height=r.get("height"),
                                 mime=f"image/{r.get('filetype')}" if r.get("filetype") else "", source=r.get("source", "")))
        return out


class Smithsonian(Provider):
    name = "smithsonian"
    key_env = "SI_API_KEY"
    API = "https://api.si.edu/openaccess/api/v1.0/search"

    def search(self, query, media="image", limit=8):
        if media != "image":
            return []
        q = urllib.parse.urlencode({"q": f"{query} AND online_media_type:Images", "rows": limit, "api_key": self.key})
        d = self.http.get_json(f"{self.API}?{q}")
        out = []
        for r in (d.get("response") or {}).get("rows", []):
            dn = (r.get("content") or {}).get("descriptiveNonRepeating", {})
            for m in ((dn.get("online_media") or {}).get("media") or [])[:1]:
                access = ((m.get("usage") or {}).get("access") or (dn.get("metadata_usage") or {}).get("access") or "")
                lic = normalize_license(access)
                url = next((x.get("url") for x in m.get("resources", []) if "High-resolution JPEG" in x.get("label", "")), m.get("content", ""))
                names = ((r.get("content") or {}).get("freetext") or {}).get("name", [])
                out.append(candidate("smithsonian", r.get("id"), clean(dn.get("title")), dn.get("record_link", ""), url, lic,
                                     creator=names[0].get("content", "") if names else "", source=dn.get("data_source", "")))
        return out


class Europeana(Provider):
    name = "europeana"
    key_env = "EUROPEANA_API_KEY"
    media = ("image", "video")
    API = "https://api.europeana.eu/record/v2/search.json"

    def search(self, query, media="image", limit=8):
        q = urllib.parse.urlencode({"query": query, "reusability": "open", "media": "true", "rows": limit,
                                    "qf": "TYPE:VIDEO" if media == "video" else "TYPE:IMAGE", "profile": "rich"})
        d = self.http.get_json(f"{self.API}?{q}", headers={"X-Api-Key": self.key})
        out = []
        for r in d.get("items", []):
            shown = (r.get("edmIsShownBy") or [""])[0]
            if not shown:
                continue
            lic = normalize_license("", (r.get("rights") or [""])[0])
            out.append(candidate("europeana", r.get("id"), (r.get("title") or [""])[0], r.get("guid", ""), shown, lic, media,
                                 creator=(r.get("dcCreator") or [""])[0], date=(r.get("year") or [""])[0],
                                 source=(r.get("dataProvider") or [""])[0]))
        return out


PROVIDERS = {p.name: p for p in (Commons, LOC, Openverse, Smithsonian, Europeana)}
PROVIDER_NAMES = {"commons": "Wikimedia Commons", "loc": "Library of Congress", "openverse": "Openverse",
                  "smithsonian": "Smithsonian Open Access", "europeana": "Europeana", "own": "the project's own files"}
DEFAULT_ORDER = ["commons", "loc", "openverse", "smithsonian", "europeana"]
