"""A tiny finished-film project for the phase 5 tests: two acts (or one) of about 14 seconds,
handmade timing with the act gap, simple act scenes, the scenegen root scene that renders one act,
board textures and a tone standing in for the mix. Optionally a Hindi edition folder.
Fast to render at a small size; nothing is downloaded."""
import contextlib
import io
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "cinematic-film" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doclib as L  # noqa: E402

LINES = {
    "en": [(1, "The engine coughed twice.", "The engine coughed twice."),
           (2, "Then the frame rolled down the rail.", "Then the frame rolled down the rail."),
           (3, "Twelve seconds later it was over.", "Twelve seconds later it was over."),
           (4, "Nobody watching knew what it meant.", "Nobody watching knew what it meant.")],
    "hi": [(1, "इंजन दो बार खाँसा।", "इंजन दो बार खाँसा।"),
           (2, "फिर ढाँचा पटरी पर लुढ़का।", "फिर ढाँचा पटरी पर लुढ़का।"),
           (3, "बारह सेकंड बाद सब ख़त्म था।", "बारह सेकंड बाद सब ख़त्म था।"),
           (4, "देखने वालों में कोई नहीं जानता था।", "देखने वालों में कोई नहीं जानता था।")],
}

ACT_SCENE = '''from engine import BigText, Film


def build_film(doc):
    film = Film(doc.duration)
    film.add(BigText({text!r}, 0, 0, 260, 0.2))
    film.cue("impact", {cue_t}, 0.5)
    film.cam(0.0, 0, -90, 0.42)
    film.cam(doc.duration, 0, -90, 0.5)
    return film
'''


def timing(code, acts):
    """Four lines; with two acts, a 2.5 s held silence before line 3 (the act 2 title card)."""
    segs, t = [], L.LEAD
    for i, (lid, cap, vo) in enumerate(LINES[code]):
        d = 1.6
        words, wt = [], t
        toks = vo.replace("।", " ").replace(".", " ").split()
        for w in toks:
            words.append({"w": w, "start": round(wt, 3), "end": round(wt + d / len(toks) * 0.9, 3)}); wt += d / len(toks)
        seg = {"id": lid, "scene": "T01", "caption": cap, "vo": vo, "start": round(t, 3), "end": round(t + d, 3),
               "duration": d, "words": words, "words_from": "voice"}
        if acts > 1:
            seg["act"] = 1 if lid <= 2 else 2
        segs.append(seg)
        gap = L.ACT_GAP if (acts > 1 and lid == 2) else L.GAP
        t = t + d + (gap if i < 3 else 0)
    return {"lang": code, "built_by": "narrate.py", "total_duration": round(t + L.TAIL, 3), "lead_in": L.LEAD,
            "tail_out": L.TAIL, "tempo": 1.0, "segments": segs}


def make(base, code="en", acts=2, edition=False, mix=True):
    """The project folder (an edition folder editions/<code> when edition=True)."""
    base = pathlib.Path(base)
    if edition:
        root = base / "doc"
        L.save(root / "00_topic" / "topic.json", {"topic": "test", "editions": [code], "default_edition": code})
        proj = root / "editions" / code
        L.save(proj / "edition.json", {"lang": code, "production": "../..", "beats": "shared"})
        L.save(proj / "lexicon.json", {"lang": code, "terms": {}, "allow": []})
    else:
        proj = base / "film"
    t = timing(code, acts)
    L.save(proj / "audio" / "timing.json", t)
    segs = t["segments"]
    import scenegen
    act_rows = []
    groups = [[1, 2], [3, 4]] if acts > 1 else [[1, 2, 3, 4]]
    for n, ids in enumerate(groups, 1):
        rel = f"06_film/act_{n:02d}/scene.py"
        first = next(s for s in segs if s["id"] == ids[0])
        t0 = first["start"] - (L.ACT_GAP if n > 1 else 0)
        last = next(s for s in segs if s["id"] == ids[-1])
        text = ("ACT ONE" if n == 1 else "ACT TWO") if code == "en" else ("पहला भाग" if n == 1 else "दूसरा भाग")
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(ACT_SCENE.format(text=text, cue_t=round(first["start"] + 0.3, 2)), encoding="utf-8")
        row = {"act": n, "scene": rel, "lines": ids, "sections": [f"s{n}"], "t0": round(t0, 2), "t1": round(last["end"] + L.TAIL, 2)}
        if n > 1:
            row["title_card"] = {"title": text, "label": f"ACT {n}", "t0": round(t0, 2), "t1": first["start"]}
        act_rows.append(row)
    L.save(proj / "06_film" / "acts.json", {"generated_by": "scenegen.py", "lang": code, "acts": act_rows})
    (proj / "scene.py").write_text(scenegen.render_root(act_rows), encoding="utf-8")
    L.save(proj / "script.json", {"lang": code, "takes": [{"take": "T01", "section": "s1",
                                                          "lines": [{"id": i, "text": c, "spoken": v} for i, c, v in LINES[code]]}]})
    import prep_assets
    (proj / "assets" / "prep").mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        prep_assets.textures(proj / "assets" / "prep")
    if mix:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={t['total_duration']}",
                        "-f", "lavfi", "-i", f"sine=frequency=330:duration={t['total_duration']}", "-filter_complex",
                        "[0][1]amerge=inputs=2,volume=0.2", "-ac", "2", "-c:a", "aac", "-b:a", "128k",
                        str(proj / "audio" / "mix.m4a")], check=True)
    return proj


def write_json(path, data):
    pathlib.Path(path).write_text(json.dumps(data))
