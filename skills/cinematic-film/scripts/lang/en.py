"""English: the rules the pipeline has always used (doclib and storyboard), unchanged, so English
output stays byte-identical. Pace 150 words a minute (145-155 is the documentary range)."""
import doclib as L
import storyboard

from . import Language, apply_lexicon, lexicon_terms, register


@register
class English(Language):
    code = "en"
    name = "English"
    locale = "en-US"
    scripts = ("Latin",)
    wpm = 150

    def spoken_text(self, text):
        terms = lexicon_terms(self.lexicon)
        return L.spoken_text(apply_lexicon(text, terms) if terms else text)

    def spoken_warnings(self, spoken):
        return L.spoken_warnings(spoken)

    def est_seconds(self, spoken):
        secs = L.est_seconds(spoken)
        return secs if self.wpm == English.wpm else secs * English.wpm / self.wpm   # an edition's own pace

    def numbers_in(self, text):
        return L.numbers_in(text)

    def key_word(self, spoken):
        return storyboard.key_word(spoken)
