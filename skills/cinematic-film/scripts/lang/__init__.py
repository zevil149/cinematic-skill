"""Language plugins: everything the pipeline needs to know about a narration language.

  import lang
  en = lang.get("en"); hi = lang.get("hi")
  en.spoken_text("In 1903") -> "In nineteen oh three"
  hi.check_script("राइट बंधु NASA", allow={"NASA"}) -> [] (problems found)

A plugin sets the language's code and name, the writing systems its narration may use, its
default locale and pace, and the rules for spoken text, timing estimates and key words. Adding a
language is a new module here that calls register(); nothing else in the pipeline changes.

Writing-system checks keep editions apart: an English line with Devanagari in it, or a Hindi line
with Latin words that the edition's lexicon does not allow, is caught before any voice is made.
"""
import re
import unicodedata

_REGISTRY = {}
TOKEN = re.compile(r"[^\s.,;:!?\"'()\[\]{}…।॥—–/\-]+")


def register(cls):
    _REGISTRY[cls.code] = cls()
    return cls


def get(code):
    _load()
    if code not in _REGISTRY:
        raise KeyError(f"language {code!r} is not supported; supported: {', '.join(supported())}")
    return _REGISTRY[code]


def supported():
    _load()
    return sorted(_REGISTRY)


def for_paths(p, data=None):
    """The language for a project's paths (doclib.paths): the edition's language with its pace and
    lexicon; else the file's own tag; else English, exactly as a single-language project."""
    code = p["lang"] or (data or {}).get("lang") or "en"
    lg = get(code)
    if p.get("edition"):
        import json
        ed = p["proj"] / "edition.json"
        wpm = json.loads(ed.read_text()).get("wpm") if ed.exists() else None
        lex = json.loads(p["lexicon"].read_text()) if p["lexicon"].exists() else {}
        lg = lg.configure(wpm=wpm, lexicon=lex)
    return lg


def _load():
    # every built-in language, whichever was imported first (importing lang.hi alone registers only Hindi)
    from . import en, hi  # noqa: F401  (each module registers itself; repeat imports are free)


def script_of(ch):
    """The writing system of one character: 'Latin', 'Devanagari', other names, or None for
    digits, punctuation, spaces and symbols that every language may use."""
    cat = unicodedata.category(ch)
    if not (cat.startswith("L") or cat.startswith("M")):
        return "Devanagari" if "०" <= ch <= "९" else None       # Devanagari digits belong to it
    name = unicodedata.name(ch, "")
    return name.split(" ")[0].title() if name else None


def apply_lexicon(text, terms):
    """Replace each lexicon term with its spoken form, longest first, whole words only; Latin
    terms match in any letter case."""
    for term in sorted(terms, key=len, reverse=True):
        spoken = terms[term].get("spoken") if isinstance(terms[term], dict) else terms[term]
        if not spoken:
            continue
        pat = r"(?<![\wऀ-ॿ])" + re.escape(term) + r"(?![\wऀ-ॿ])"
        text = re.sub(pat, spoken, text, flags=re.IGNORECASE)
    return text


def lexicon_terms(lexicon):
    return (lexicon or {}).get("terms", {})


class Language:
    code = ""
    name = ""
    locale = ""
    scripts = ()                 # writing systems the narration may use
    wpm = 150                    # default pace, words a minute of speech (configurable per edition)
    stopwords = frozenset()
    lexicon = {}                 # an edition's lexicon.json: {"terms": {...}, "allow": [...]}

    def configure(self, wpm=None, lexicon=None):
        """This language with an edition's pace and lexicon (a copy; the registered one is unchanged)."""
        import copy
        c = copy.copy(self)
        if wpm:
            c.wpm = float(wpm)
        if lexicon is not None:
            c.lexicon = lexicon
        return c

    @property
    def wps(self):
        return self.wpm / 60.0

    # --- writing systems ------------------------------------------------------------------
    def check_script(self, text, allow=()):
        """Problems with the writing systems in text: words in a script this language does not
        use (unless listed in allow), and words that mix scripts."""
        allowed = {a.lower() for a in allow}
        problems = []
        for tok in TOKEN.findall(text or ""):
            found = {s for s in map(script_of, tok) if s}
            if not found:
                continue
            if len(found) > 1:
                problems.append(f"{tok!r} mixes {' and '.join(sorted(found))}")
            elif not found <= set(self.scripts) and tok.lower() not in allowed:
                problems.append(f"{tok!r} is {next(iter(found))}, not {self.name}")
        return problems

    def detect_share(self, text):
        """Share of letters in this language's own writing systems (0..1)."""
        letters = [s for s in map(script_of, text or "") if s]
        return sum(1 for s in letters if s in self.scripts) / len(letters) if letters else 1.0

    # --- speech ---------------------------------------------------------------------------
    def spoken_text(self, text):
        return text

    def spoken_warnings(self, spoken):
        return []

    def est_seconds(self, spoken):
        words = len(TOKEN.findall(spoken or ""))
        return words / self.wps

    def numbers_in(self, text):
        import doclib
        return doclib.numbers_in(text)

    def key_word(self, spoken):
        words = TOKEN.findall(spoken or "")
        for w in reversed(words):
            if w.lower() not in self.stopwords and len(w) > 2:
                return w
        return words[-1] if words else ""
