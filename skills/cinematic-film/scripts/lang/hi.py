"""Hindi, written in Devanagari. Pace 135 words a minute (130-140 is the documentary range).

Milestone 3.0 gives Hindi its writing-system rules, a word-based timing estimate and key words.
Numbers, dates and currency spoken as Hindi words, and syllable-based timing, arrive in 3.1;
until then digits in a Hindi line are flagged rather than read out in English."""
from . import Language, register


@register
class Hindi(Language):
    code = "hi"
    name = "Hindi"
    locale = "hi-IN"
    scripts = ("Devanagari",)
    wpm = 135
    stopwords = frozenset("और का की के को में से पर है हैं था थी थे यह वह एक भी तो ही ने लिए".split())

    def spoken_text(self, text):
        return text            # Hindi number and date words arrive in milestone 3.1

    def spoken_warnings(self, spoken):
        import re
        w = []
        if re.search(r"[0-9०-९]", spoken or ""):
            w.append("digits in Hindi spoken text; write the number as Hindi words (automatic in milestone 3.1)")
        return w
