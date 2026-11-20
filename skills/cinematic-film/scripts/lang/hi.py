"""Hindi, written in Devanagari. Pace 135 words a minute (130-140 is the documentary range).

Spoken text: numbers, years, dates, money, percentages, decimals, ordinals and Devanagari digits
become Hindi words, and the edition's lexicon gives English names and places their Hindi
pronunciation:
  "17 दिसंबर 1903"   -> "सत्रह दिसंबर उन्नीस सौ तीन"
  "₹1,00,000"        -> "एक लाख रुपये"          (Indian grouping: हज़ार, लाख, करोड़, अरब)
  "$50,000"          -> "पचास हज़ार डॉलर"
  "45%"              -> "पैंतालीस प्रतिशत";  "3.5" -> "तीन दशमलव पाँच"
  "21वीं सदी"         -> "इक्कीसवीं सदी"
Timing: syllables (aksharas) at the edition's pace, never zero for a line with words.
Fact check: numbers in a Hindi line, as digits or words (with डेढ़, ढाई, साढ़े, सवा, पौने and the
usual spelling variants), are read as values and compared with the canonical English claims.

The number words follow standard Hindi; the native-speaker review of each Hindi script (an
approved gate before any paid voice) is where a regional preference would be corrected.
"""
import re
import unicodedata

from . import TOKEN, Language, apply_lexicon, register

# 0-99: Hindi has a distinct word for every number below a hundred
WORDS = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ "
         "दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
         "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस "
         "तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस "
         "चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास "
         "पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ "
         "साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर "
         "सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी "
         "अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी "
         "नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
assert len(WORDS) == 100
VARIANTS = {"छः": 6, "छ": 6, "इकत्तीस": 31, "उनचालीस": 39, "चौवालीस": 44, "चौंतालीस": 44, "सरसठ": 67,
            "उनासी": 79, "उन्नासी": 79, "इकानवे": 91, "बयानवे": 92, "निन्नानवे": 99, "सौ": 100}
SCALES = ((10 ** 9, "अरब"), (10 ** 7, "करोड़"), (10 ** 5, "लाख"), (1000, "हज़ार"), (100, "सौ"))
SCALE_WORDS = {"सौ": 100, "सैकड़ा": 100, "हज़ार": 1000, "लाख": 10 ** 5, "करोड़": 10 ** 7, "अरब": 10 ** 9}
FRACTIONS = {"डेढ़": 1.5, "ढाई": 2.5}               # whole numbers on their own
MODIFIERS = {"साढ़े": 0.5, "सवा": 0.25, "पौने": -0.25}   # added to the number that follows
CURRENCY = {"₹": ("रुपये", "रुपया"), "$": ("डॉलर", "डॉलर"), "€": ("यूरो", "यूरो"), "£": ("पाउंड", "पाउंड")}
ORDINAL_BASE = {1: "पहल", 2: "दूसर", 3: "तीसर", 4: "चौथ", 6: "छठ"}
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUKTA, CHANDRABINDU, ANUSVARA, VIRAMA = "़", "ँ", "ं", "्"
AKSHARAS_PER_WORD = 2.5            # average syllables in a Hindi word of narration, for timing
LATIN_LPS = 14.5                   # an allowed English term (NASA) is timed as English letters


def _norm(word):
    """Spelling-insensitive key: NFC, nukta dropped, chandrabindu as anusvara (पाँच = पांच)."""
    w = unicodedata.normalize("NFC", word)
    w = unicodedata.normalize("NFD", w).replace(NUKTA, "")
    return unicodedata.normalize("NFC", w).replace(CHANDRABINDU, ANUSVARA)


VALUE = {_norm(w): i for i, w in enumerate(WORDS)}
VALUE.update({_norm(w): v for w, v in VARIANTS.items()})
SCALE = {_norm(w): v for w, v in SCALE_WORDS.items()}
FRACTION = {_norm(w): v for w, v in FRACTIONS.items()}
MODIFIER = {_norm(w): v for w, v in MODIFIERS.items()}
ORDINAL_SUFFIX = re.compile(r"(वाँ|वां|वें|वीं|वी|वे)$")


def int_words(n):
    """A whole number in Hindi words, Indian scale: 1,20,000 -> एक लाख बीस हज़ार."""
    n = int(n)
    if n < 0:
        return "ऋण " + int_words(-n)
    if n < 100:
        return WORDS[n]
    for div, name in SCALES:
        if n >= div:
            head, rest = divmod(n, div)
            return int_words(head) + " " + name + (" " + int_words(rest) if rest else "")
    return WORDS[n]


def year_words(y):
    """Years as Hindi says them: 1903 -> उन्नीस सौ तीन, 1900 -> उन्नीस सौ, 2024 -> दो हज़ार चौबीस."""
    y = int(y)
    if 1100 <= y <= 1999:
        hi, lo = divmod(y, 100)
        return WORDS[hi] + " सौ" + (" " + WORDS[lo] if lo else "")
    return int_words(y)


def ordinal_words(n, suffix):
    """17 + वीं -> सत्रहवीं; 1 + वीं -> पहली; 4 + वें -> चौथे."""
    n = int(n)
    end = {"वाँ": "ा", "वां": "ा", "वें": "े", "वे": "े", "वीं": "ी", "वी": "ी"}[suffix]
    if n in ORDINAL_BASE:
        return ORDINAL_BASE[n] + end
    return int_words(n) + {"ा": "वाँ", "े": "वें", "ी": "वीं"}[end]


def decimal_words(s):
    whole, frac = s.replace(",", "").split(".")
    return int_words(int(whole)) + " दशमलव " + " ".join(WORDS[int(d)] for d in frac)


def amount_words(s):
    s = s.replace(",", "")
    return decimal_words(s) if "." in s else int_words(int(s))


def spoken_numbers(text):
    s = text.translate(DEVANAGARI_DIGITS)
    s = re.sub(r"([₹$€£])\s?(\d[\d,]*(?:\.\d+)?)(?:\s*(हज़ार|हजार|लाख|करोड़|करोड|अरब))?",
               lambda m: amount_words(m.group(2)) + (" " + m.group(3) if m.group(3) else "") + " "
               + CURRENCY[m.group(1)][1 if m.group(2) == "1" and not m.group(3) else 0], s)
    s = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: amount_words(m.group(1)) + " प्रतिशत", s)
    s = re.sub(r"(?<![\d,.])(\d+)\s?(वाँ|वां|वें|वीं|वी|वे)(?![ऀ-ॿ])", lambda m: ordinal_words(m.group(1), m.group(2)), s)
    s = re.sub(r"(?<![\d,.])(1[1-9]\d{2}|20\d{2})(?!\d|[,.]\d)", lambda m: year_words(m.group(1)), s)
    s = re.sub(r"\d+\.\d+", lambda m: decimal_words(m.group(0)), s)
    s = re.sub(r"\d{1,3}(?:,\d{2,3})+|\d+", lambda m: int_words(int(m.group(0).replace(",", ""))), s)
    return s


def aksharas(text):
    """Syllables of Devanagari text: each independent vowel, and each consonant that does not
    join the next one through a virama (क्ष is one)."""
    n, prev = 0, ""
    for ch in unicodedata.normalize("NFC", text):
        o = ord(ch)
        consonant = 0x0915 <= o <= 0x0939 or 0x0958 <= o <= 0x095F
        vowel = 0x0904 <= o <= 0x0914 or 0x0960 <= o <= 0x0961 or 0x0972 <= o <= 0x0977
        if (consonant and prev != VIRAMA) or vowel:
            n += 1
        if ch != NUKTA:
            prev = ch
    return n


def numbers_in(text):
    """Every number a Hindi sentence states, as values: digits in either script (Indian or
    Western grouping) and number words, including fractions. A lone एक (also "a") is ignored."""
    vals = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", (text or "").translate(DEVANAGARI_DIGITS)):
        try:
            vals.add(float(m.group(0).replace(",", "").rstrip(".")))
        except ValueError:
            pass
    total = cur = None
    frac = 0.0
    decimals = None

    def flush():
        nonlocal total, cur, frac, decimals
        if cur is not None or total is not None:
            v = (total or 0) + (cur or 0)
            if decimals:
                v += float("0." + decimals)
            if v > 1 or decimals:
                vals.add(float(v))
        total = cur = None
        frac, decimals = 0.0, None

    for tok in TOKEN.findall(text or ""):
        w = _norm(tok)
        base = ORDINAL_SUFFIX.sub("", w)
        if decimals is not None and w in VALUE and VALUE[w] < 10:
            decimals += str(VALUE[w]); continue
        if w in MODIFIER:
            flush(); frac = MODIFIER[w]; continue
        if w == _norm("दशमलव") and (cur is not None or total is not None):
            decimals = ""; continue
        if w in FRACTION:
            cur = (cur or 0) + FRACTION[w]
        elif w in VALUE and w not in SCALE:
            if cur is not None and cur % 1 == 0 and cur < 100 and VALUE[w] < 100:
                flush()                                       # two small numbers in a row are two numbers
            cur = (cur or 0) + VALUE[w] + frac; frac = 0.0
        elif w in SCALE and (cur is not None or total is not None or w == _norm("सौ")):
            mult = SCALE[w]
            if mult == 100:
                cur = (cur if cur is not None else 1) * 100
            else:
                total = (total or 0) + (cur if cur is not None else 1) * mult; cur = None
        elif base != w and base in VALUE and VALUE[base] > 1:
            flush(); vals.add(float(VALUE[base]))             # an ordinal word: सत्रहवीं is 17
        else:
            flush()
    flush()
    return vals


@register
class Hindi(Language):
    code = "hi"
    name = "Hindi"
    locale = "hi-IN"
    scripts = ("Devanagari",)
    wpm = 135
    stopwords = frozenset(_norm(w) for w in (
        "और का की के को में से पर है हैं था थी थे यह वह ये वे एक भी तो ही ने लिए तक हुआ हुई हुए गया गई गए "
        "रहा रही रहे कर करके कि जो जब तब अब नहीं न कोई कुछ इस उस इन उन अपने अपना अपनी साथ बाद पहले फिर "
        "भी हो होता होती होते सकता सकती सकते दिया दी दिए लिया ली लिए मैं हम आप तुम उनके उसके इसके उनकी उसकी "
        "इसकी उनका उसका इसका मेरा मेरी मेरे हमारा हमारी हमारे वहाँ यहाँ").split())

    def spoken_text(self, text):
        return spoken_numbers(apply_lexicon(text, (self.lexicon or {}).get("terms", {})))

    def spoken_warnings(self, spoken):
        w = []
        if re.search(r"[0-9०-९]", spoken or ""):
            w.append("digits left in the Hindi spoken text; write them as Hindi words")
        latin = sorted({t for t in TOKEN.findall(spoken or "") if re.search(r"[A-Za-z]", t)})
        if latin:
            w.append(f"Latin words {latin} in the spoken text: give each a Hindi pronunciation in lexicon.json")
        if re.search(r"[&@#/°]", spoken or ""):
            w.append("symbols in the spoken text; write them as words")
        return w

    def est_seconds(self, spoken):
        s = spoken_numbers(spoken or "")
        if not s.strip():
            return 0.0
        latin = len(re.findall(r"[A-Za-z]", s))
        secs = aksharas(s) / (self.wps * AKSHARAS_PER_WORD) + latin / LATIN_LPS
        return max(secs, 0.3)                         # any line with words takes time to say

    def key_word(self, spoken):
        words = TOKEN.findall(spoken or "")
        for w in reversed(words):
            if _norm(w) not in self.stopwords and aksharas(w) + len(re.findall(r"[A-Za-z]", w)) >= 2:
                return w
        return words[-1] if words else ""

    def numbers_in(self, text):
        return numbers_in(text)
