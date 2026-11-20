"""Shared helpers for the documentary pipeline (docpipe.py and its stage tools).

Standard library only, so every stage and its tests run before skia or ffmpeg are installed.

Project layout (one folder per stage; the existing film tools keep reading the project root):

  docpipe.json                 pipeline state: stage status, input hashes, approvals
  00_topic/topic.json          the brief: topic, angle, audience, length in minutes, look
  01_research/sources.json     every source: url or citation, publisher, date, accessed, tier
  01_research/claims.json      every fact the film may state, each tied to source ids
  01_research/research.md      generated report: claim status, weak and unsupported claims
  02_outline/outline.json      sections with purpose, period, claims and a time budget
  02_outline/outline.md        generated, for review
  03_script/narration.json     the narration: sections of lines, each citing claim ids
  03_script/script.md          generated, for review
  script.json                  exported for the film tools (make_beats.py, tts_say.py, ...)
  04_scenes/storyboard.json    one scene per line: timestamps, hero, camera move, images
  04_scenes/storyboard.md      generated, for review
  04_scenes/image_needs.json   every image the film needs, for the visual stage
"""
import datetime
import hashlib
import json
import pathlib
import re
import urllib.parse

# pacing shared with make_beats.py, split_takes.py and build_narration.py
LPS = 14.5          # letters per second of speech
GAP = 0.45          # silence after a line
TAKE_GAP = 1.0      # silence after the last line of a take
LEAD, TAIL = 0.9, 3.0
WPS = 2.5           # words per second, about 150 a minute, for budgets
WORDS_PER_LINE = 12
MAX_LINE_WORDS = 22

STAGE_DIRS = {"topic": "00_topic", "research": "01_research", "outline": "02_outline",
              "script": "03_script", "scenes": "04_scenes", "visuals": "05_visuals", "film": "06_film"}


# ---------------------------------------------------------------------------------------- files

def load(path, default=None):
    p = pathlib.Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError(str(p))
    return json.loads(p.read_text())


def save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(p)


def write_text(path, text):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


SHARED_STAGES = ("topic", "research", "outline", "visuals")       # one per production, in every edition
EDITION_STAGES = ("script", "scenes", "film")                      # one per language edition


def edition_info(proj):
    """For an edition folder (editions/<lang>/ with edition.json): its language, the production root
    it belongs to, and whether it keeps its own beats. None for a production root or a legacy project."""
    ep = pathlib.Path(proj) / "edition.json"
    if not ep.exists():
        return None
    e = json.loads(ep.read_text())
    return {"lang": e["lang"], "root": (pathlib.Path(proj) / e.get("production", "../..")).resolve(),
            "beats": e.get("beats", "shared"), "source": e.get("source", False)}


def paths(proj):
    """Every file the pipeline reads or writes, for a project folder.

    A legacy project (no editions) and a production root keep every stage folder in the project.
    An edition folder (editions/<lang>/) reads the shared stages (topic, research, outline, beats,
    visuals) from its production root and keeps its own script, scenes, film and audio."""
    proj = pathlib.Path(proj)
    ed = edition_info(proj)
    root = ed["root"] if ed else proj
    d = {k: (proj if (ed and k in EDITION_STAGES) else root) / v for k, v in STAGE_DIRS.items()}
    beats_dir = (proj if ed and ed["beats"] == "own" else root) / "03_beats"
    topic = d["topic"] / "topic.json"
    multi = ed is not None or bool(load(topic, {}).get("editions"))
    return {
        "proj": proj, "state": proj / "docpipe.json", **{k + "_dir": v for k, v in d.items()},
        "root": root, "lang": ed["lang"] if ed else None, "edition": ed, "multi": multi,
        "topic": topic,
        "sources": d["research"] / "sources.json", "claims": d["research"] / "claims.json",
        "research_md": d["research"] / "research.md",
        "outline": d["outline"] / "outline.json", "outline_md": d["outline"] / "outline.md",
        "narration": d["script"] / "narration.json", "script_md": d["script"] / "script.md",
        "script_json": proj / "script.json",
        "storyboard": d["scenes"] / "storyboard.json", "storyboard_md": d["scenes"] / "storyboard.md",
        # the images visuals.py fetches: per storyboard in a legacy project, per beat once a production has editions
        "image_needs": (beats_dir / "image_needs.json") if multi else d["scenes"] / "image_needs.json",
        "beats_dir": beats_dir, "beats": beats_dir / "beats.json", "beats_md": beats_dir / "beats.md",
        "lexicon": proj / "lexicon.json",
        "timing": proj / "audio" / "timing.json",
    }


def hash_files(files):
    h = hashlib.sha256()
    for f in files:
        f = pathlib.Path(f)
        h.update(str(f.name).encode())
        h.update(f.read_bytes() if f.exists() else b"<missing>")
    return h.hexdigest()[:16]


def today():
    return datetime.date.today().isoformat()


def slug(s, n=32):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:n] or "section"


class Result:
    """What a stage check found. Errors block the pipeline; warnings are for the review."""

    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)

    @property
    def ok(self):
        return not self.errors

    def extend(self, other):
        self.errors += other.errors; self.warnings += other.warnings; self.notes += other.notes

    def report(self, title):
        out = [title]
        out += [f"  ERROR  {e}" for e in self.errors]
        out += [f"  warn   {w}" for w in self.warnings]
        out += [f"  note   {n}" for n in self.notes]
        if not (self.errors or self.warnings):
            out.append("  ok")
        return "\n".join(out)


# ------------------------------------------------------------------------------ length presets

def length_plan(minutes):
    """Section budget for a documentary of `minutes`. Presets 5, 10, 20 and 30; any length in
    between works the same way. Shape (references/story.md): cold open, one bridge back in time,
    chapters strictly forward, a turn, a close that pays off the cold open."""
    minutes = float(minutes)
    if not 1 <= minutes <= 60:
        raise ValueError("minutes must be between 1 and 60")
    total = minutes * 60
    chapters = max(3, round(minutes * 0.65 + 1.5))          # 5 -> 5, 10 -> 8, 20 -> 14, 30 -> 21
    acts = 1 if minutes <= 10 else (3 if minutes <= 20 else 4)
    cold = min(60.0, max(15.0, total * 0.05))
    bridge = max(8.0, min(20.0, total * 0.01))
    close = min(75.0, max(15.0, total * 0.05))
    turn = total * 0.10
    chapter = (total - cold - bridge - close - turn) / chapters
    secs = [("cold_open", "Cold open", cold, 0), ("bridge", "Bridge", bridge, 1)]
    for c in range(chapters):
        act = 1 + c * acts // chapters
        secs.append(("chapter", f"Chapter {c + 1}", chapter, act))
    secs += [("turn", "The turn", turn, acts), ("close", "Close", close, acts)]
    out = []
    for n, (kind, label, s, act) in enumerate(secs, 1):
        words = round(s * WPS)
        out.append({"id": f"SEC{n:02d}", "kind": kind, "act": act, "label": label,
                    "target_seconds": round(s, 1), "target_words": words,
                    "target_lines": max(1, round(words / WORDS_PER_LINE))})
    return {"minutes": minutes, "total_seconds": total, "words": round(total * WPS),
            "chapters": chapters, "acts": acts, "sections": out}


# ------------------------------------------------------------------------------ numbers to words

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))


def int_words(n):
    n = int(n)
    if n < 0:
        return "minus " + int_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" and " + int_words(n % 100) if n % 100 else "")
    for div, name in SCALES:
        if n >= div:
            head, rest = divmod(n, div)
            s = int_words(head) + " " + name
            if rest:
                s += (" and " if rest < 100 else " ") + int_words(rest)
            return s


def year_words(y):
    y = int(y)
    if 2000 <= y <= 2009:
        return "two thousand" + (" and " + ONES[y - 2000] if y > 2000 else "")
    hi, lo = divmod(y, 100)
    if lo == 0:
        return int_words(hi) + " hundred"
    if lo < 10:
        return int_words(hi) + " oh " + ONES[lo]
    return int_words(hi) + " " + int_words(lo)


_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
        "nine": "ninth", "twelve": "twelfth"}


def ordinal_words(n):
    w = int_words(n)
    m = re.match(r"(.*?)([a-z]+)$", w)
    head, last = m.group(1), m.group(2)
    if last in _ORD:
        last = _ORD[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return head + last


def _plural(w):
    return w[:-1] + "ies" if w.endswith("y") else w + "s"


def _num(s):
    return s.replace(",", "")


def _decimal_words(s):
    whole, frac = _num(s).split(".")
    return int_words(int(whole)) + " point " + " ".join(ONES[int(d)] for d in frac)


def _amount(s):
    return _decimal_words(s) if "." in s else int_words(int(_num(s)))


def spoken_text(text):
    """The line as a voice should read it: numbers, years, dates, money and percentages in words.
    'December 17th, 1903' -> 'December seventeenth, nineteen oh three'; '$50,000' -> 'fifty
    thousand dollars'. What it cannot settle (abbreviations, symbols) spoken_warnings() flags."""
    s = text
    s = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)(?:\s*(million|billion|trillion|thousand))?",
               lambda m: _amount(m.group(1)) + (" " + m.group(2) if m.group(2) else "") + " dollars", s)
    s = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: _amount(m.group(1)) + " percent", s)
    s = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: ordinal_words(m.group(1)), s)
    s = re.sub(r"\b(1[0-9]|20)00s\b", lambda m: int_words(m.group(1)) + " hundreds", s)
    s = re.sub(r"\b((?:1[0-9]|20)[0-9]0)s\b", lambda m: _plural(year_words(m.group(1))), s)
    s = re.sub(r"(?<![\d,.$])\b(1[1-9][0-9]{2}|20[0-9]{2})\b(?!\d|[,.]\d)", lambda m: year_words(m.group(1)), s)
    s = re.sub(r"\b\d+\.\d+\b", lambda m: _decimal_words(m.group(0)), s)
    s = re.sub(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", lambda m: int_words(int(_num(m.group(0)))), s)
    return s


def spoken_warnings(spoken):
    w = []
    if re.search(r"\d", spoken):
        w.append("digits left in the spoken text; write them as words")
    abbr = re.findall(r"\b(?:[A-Z]\.){2,}|\b[A-Z]{2,}\b", spoken)
    if abbr:
        w.append(f"abbreviations {sorted(set(abbr))} may be misread; spell them as they are said")
    if re.search(r"[&@#/°]", spoken):
        w.append("symbols in the spoken text; write them as words")
    return w


# ------------------------------------------------------------------------ numbers in facts

_WORDNUM = {w: i for i, w in enumerate(ONES)}
_WORDNUM.update({w: 10 * i for i, w in enumerate(TENS) if w != "_"})


def numbers_in(text):
    """Every number a sentence states, as values: digits ('1,200', '12', '1903', '17th') and
    number words ('twelve', 'one hundred and twenty'). 0 and 1 in words are ignored: 'one man'
    is rarely a statistic."""
    vals = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        t = _num(m.group(0)).rstrip(".")
        try:
            vals.add(float(t))
        except ValueError:
            pass
    toks = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    total = cur = None
    scales = {"hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}

    def flush():
        nonlocal total, cur
        if cur is not None or total is not None:
            v = (total or 0) + (cur or 0)
            if v > 1:
                vals.add(float(v))
        total = cur = None

    for t in toks:
        if t in _WORDNUM:
            cur = (cur or 0) + _WORDNUM[t]
        elif t in scales and (cur is not None or total is not None):
            if scales[t] == 100:
                cur = (cur or 1) * 100
            else:
                total = (total or 0) + (cur or 1) * scales[t]; cur = None
        elif t == "and" and (cur is not None or total is not None):
            continue
        else:
            flush()
    flush()
    return vals


# ------------------------------------------------------------------------------- source tiers

TIER1_SUFFIXES = (".gov", ".mil", ".edu", ".gov.uk", ".ac.uk", ".gc.ca", ".gov.au", ".edu.au", ".gouv.fr")
TIER1_DOMAINS = {
    "loc.gov", "archives.gov", "si.edu", "nps.gov", "nasa.gov", "doi.org", "jstor.org",
    "nationalarchives.gov.uk", "bl.uk", "britishmuseum.org", "europeana.eu", "bnf.fr", "nla.gov.au",
    "metmuseum.org", "rijksmuseum.nl", "un.org", "who.int", "worldbank.org", "nature.com",
    "science.org", "ncbi.nlm.nih.gov", "oup.com", "cambridge.org", "springer.com",
}
TIER3_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "wikiwand.com", "fandom.com", "reddit.com", "quora.com",
    "youtube.com", "youtu.be", "medium.com", "blogspot.com", "wordpress.com", "tiktok.com", "x.com",
    "twitter.com", "facebook.com", "instagram.com", "pinterest.com", "answers.com", "ancient-origins.net",
}
TIER_TYPES = {"archive": 1, "government": 1, "academic": 1, "museum": 1, "primary": 1,
              "book": 2, "news": 2, "reference": 2, "other": 2, "wiki": 3, "social": 3, "blog": 3}
TIER_NAMES = {1: "primary or institutional", 2: "secondary", 3: "leads only"}


def host(url):
    h = urllib.parse.urlparse(url or "").hostname or ""
    return h[4:] if h.startswith("www.") else h


def domain(url):
    """Registrable domain, near enough to tell independent sources apart."""
    parts = host(url).split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "ac", "gov", "org", "com", "edu", "gouv"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def source_tier(src):
    if src.get("tier") in (1, 2, 3):
        return src["tier"]
    h = host(src.get("url", ""))
    if h:
        if any(h == d or h.endswith("." + d) for d in TIER3_DOMAINS):
            return 3
        if any(h == d or h.endswith("." + d) for d in TIER1_DOMAINS) or h.endswith(TIER1_SUFFIXES):
            return 1
    return TIER_TYPES.get(src.get("type", "other"), 2)


def source_key(src):
    """Two sources from the same site (or the same book) are not independent."""
    if src.get("url"):
        return domain(src["url"])
    return (src.get("publisher") or src.get("title") or src.get("id", "")).lower()


HEDGES = re.compile(r"\b(about|around|roughly|nearly|reported(ly)?|said|says|claimed|according|estimated|"
                    r"believed|may|might|perhaps|probably|commonly cited|legend|some say|disputed)\b", re.I)


def claim_status(claim, sources_by_id):
    """'supported', 'single-source' (a number or date from one independent source), 'weak'
    (leads only, e.g. Wikipedia), 'disputed' (marked so), or 'unsupported' (no valid source)."""
    srcs = [sources_by_id[s] for s in claim.get("sources", []) if s in sources_by_id]
    if not srcs:
        return "unsupported"
    if claim.get("disputed"):
        return "disputed"
    if all(source_tier(s) == 3 for s in srcs):
        return "weak"
    good = {source_key(s) for s in srcs if source_tier(s) < 3}
    if numbers_in(claim.get("text", "")) and len(good) < 2 and not any(source_tier(s) == 1 for s in srcs):
        return "single-source"
    return "supported"


def mmss(s):
    s = max(0.0, float(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:04.1f}" if h else f"{int(m)}:{sec:04.1f}"


def est_seconds(spoken):
    return len(re.sub(r"[^A-Za-z]", "", spoken)) / LPS
