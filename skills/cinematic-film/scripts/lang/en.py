"""English: the rules the pipeline has always used (doclib and storyboard), unchanged, so English
output stays byte-identical. Pace 150 words a minute (145-155 is the documentary range)."""
import doclib as L
import storyboard

from . import Language, register


@register
class English(Language):
    code = "en"
    name = "English"
    locale = "en-US"
    scripts = ("Latin",)
    wpm = 150

    def spoken_text(self, text):
        return L.spoken_text(text)

    def spoken_warnings(self, spoken):
        return L.spoken_warnings(spoken)

    def est_seconds(self, spoken):
        return L.est_seconds(spoken)

    def key_word(self, spoken):
        return storyboard.key_word(spoken)
