"""Word times for captions and subtitles, from timing.json. Standard library only.

timed_words(seg) matches a line's displayed words to the spoken words narrate.py timed, and labels
each: "voice" (the voice's own time for that word), "voice-approx" (a displayed word read as other
words, such as a year, placed on the voice's times) or "estimate" (the language's timing rules).
words_with_times(seg) gives (word, start) pairs; a timing file without words falls back to each
line's letter share, exactly as before.
"""
import difflib
import re

DEVANAGARI = re.compile(r"[ऀ-ॿ꣠-ꣿ᳐-᳿]")


def needs_shaping(text):
    return bool(text) and DEVANAGARI.search(text) is not None


PUNCT = re.compile(r"[\s.,;:!?\"'()\[\]{}…।॥—–/\-‘’“”]+")


def norm(w):
    return PUNCT.sub("", w.lower())


def spoken_weight(w):
    """How long a displayed word is when spoken, roughly: its letters; numbers are read long."""
    n = norm(w)
    digits = len(re.sub(r"[^0-9]", "", n))
    return max(1, len(n), 6 * digits // 2 + 4 if digits else 0)


def share(disp, spoken):
    """[(first, last)] spoken-word indexes for each displayed word, cutting the spoken words where
    their letters best match each displayed word's expected spoken length."""
    n, m = len(disp), len(spoken)
    if m < n:                                   # fewer spoken words than shown: neighbours share one
        return [(k * m // n, k * m // n) for k in range(n)]
    dw = [spoken_weight(w) for w in disp]
    sw = [max(1, len(norm(w))) for w in spoken]
    total_d, total_s = float(sum(dw)), float(sum(sw))
    edges = [0]
    for s_ in sw:
        edges.append(edges[-1] + s_)
    cuts, acc = [0], 0.0
    for k in range(n - 1):
        acc += dw[k]
        target = acc / total_d * total_s
        lo, hi = cuts[-1] + 1, m - (n - 1 - k)          # leave at least one spoken word for each displayed one
        best = min(range(lo, hi + 1), key=lambda j: abs(edges[j] - target))
        cuts.append(best)
    cuts.append(m)
    return [(cuts[k], cuts[k + 1] - 1) for k in range(n)]


def timed_words(seg):
    """[(word as displayed, start, end, source)] from the line's recorded word times, or None when
    it has none. source: "voice" (the voice's time for this very word), "voice-approx" (a displayed
    word matched to differently spoken words, e.g. 1903 read as three words) or "estimate"."""
    words = seg.get("words")
    if not words:
        return None
    base = "voice" if seg.get("words_from") == "voice" else "estimate"
    approx = "voice-approx" if base == "voice" else "estimate"
    disp = seg["caption"].replace('"', "").split()
    sp = [norm(w["w"]) for w in words]
    out = []
    ops = difflib.SequenceMatcher(None, [norm(w) for w in disp], sp, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                w = words[j1 + k]
                out.append((disp[i1 + k], w["start"], w["end"], base))
        elif tag == "replace":                   # shown one way, read another (17th, 1903): share the spoken words
            for k, (a, b) in enumerate(share(disp[i1:i2], [w["w"] for w in words[j1:j2]])):
                out.append((disp[i1 + k], words[j1 + a]["start"], words[j1 + b]["end"], approx))
        elif tag == "delete":                    # shown but not spoken: held with the next spoken word
            t = words[j1]["start"] if j1 < len(words) else words[-1]["end"]
            for k in range(i2 - i1):
                out.append((disp[i1 + k], t, t, approx))
        # "insert": spoken but not shown (a word the lexicon added): nothing to display
    last = seg["start"]
    fixed = []
    for w, a, b, src in out:
        a = max(a, last); b = max(b, a); last = a
        fixed.append((w, a, b, src))
    return fixed


def timing_of(seg):
    """How a line's word times were made: voice, estimate, or legacy (a timing file without words)."""
    if not seg.get("words"):
        return "legacy"
    return "voice" if seg.get("words_from") == "voice" else "estimate"


def words_with_times(seg):
    """[(word as displayed, start time)] for one line: display text, spoken-text timing."""
    tw = timed_words(seg)
    if tw is not None:
        return [(w, a) for w, a, _, _ in tw]
    disp = seg["caption"].replace('"', "").split()
    lens = []
    for w in disp:
        letters = len(re.sub(r"[^A-Za-z]", "", w))
        if not letters and needs_shaping(w):       # Hindi: by syllables
            from lang.hi import aksharas
            letters = 2 * aksharas(w)
        if re.search(r"\d", w):                      # 1929 is long when spoken ("nineteen twenty-nine")
            letters = max(letters, 6 * len(re.sub(r"[^0-9]", "", w)) // 2 + 4)
        lens.append(max(1, letters))
    s = sum(lens); acc = 0; out = []
    dur = seg["end"] - seg["start"]
    for w, l in zip(disp, lens):
        out.append((w, seg["start"] + dur * acc / s)); acc += l
    return out
