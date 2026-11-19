#!/usr/bin/env python3
"""Prepare archive film clips for the engine's Footage item: cut, scale and grade each clip into
a short run of JPEG frames, graded to the same look as the photos.

  python3 prep_footage.py --project my-film [--fps 12] [--max-seconds 20] [--force]

footage.json (visuals.py writes it; edit or add entries by hand):
  {"footage": [{"id": "I003", "file": "I003.webm", "clip_in": 4.0, "clip_dur": 8.0, "kind": "photo",
                "credit": "...", "license": "Public domain", "source": "https://..."}]}

Writes  assets/prep/footage/<id>/f00001.jpg ..., <id>/meta.json, assets/prep/footage/meta.json

Archive film runs at 12 to 18 frames a second, so 12 is the default: it reads as period film and
keeps memory small. Frames are at most 1280 px wide; a clip is at most --max-seconds long. The
engine holds only a couple of dozen frames at once, whatever the clip length. Sound is dropped.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prep_assets import grade  # noqa: E402


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def signature(src, entry, look, fps, max_seconds, width):
    """What the frames were made from: the clip's bytes and every setting. A replaced clip (a new
    pick in selection.json) or a new setting makes new frames."""
    h = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(json.dumps([entry.get("clip_in", 0), entry.get("clip_dur"), entry.get("kind", "photo"), look, fps, max_seconds, width]).encode())
    return h.hexdigest()[:20]


def prep_clip(proj, entry, look, fps=12, max_seconds=20.0, width=1280, force=False):
    src = proj / "assets" / "footage" / entry["file"]
    if not src.exists():
        return None, f"{entry['id']}: {src} not found"
    out = proj / "assets" / "prep" / "footage" / entry["id"]
    meta_p = out / "meta.json"
    sig = signature(src, entry, look, fps, max_seconds, width)
    if meta_p.exists() and not force and json.loads(meta_p.read_text()).get("signature") == sig:
        return json.loads(meta_p.read_text()), None
    total = probe_duration(src)
    start = float(entry.get("clip_in", 0.0))
    dur = min(float(entry.get("clip_dur") or max_seconds), max_seconds)
    if total and start >= total:
        return None, f"{entry['id']}: clip_in {start}s is past the end of the clip ({total:.1f}s)"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start}", "-t", f"{dur}", "-i", str(src), "-an",
           "-vf", f"fps={fps},scale='min({width},iw)':-2", "-q:v", "3", str(out / "f%05d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    frames = sorted(out.glob("f*.jpg"))
    if r.returncode != 0 or not frames:
        shutil.rmtree(out, ignore_errors=True)
        return None, f"{entry['id']}: ffmpeg could not read {src.name}: {r.stderr.strip()[-200:]}"
    kind = entry.get("kind", "photo")
    for f in frames:
        g = grade(Image.open(f).convert("RGB"), kind, look)
        g.save(f, quality=90)
    w, h = Image.open(frames[0]).size
    meta = {"w": w, "h": h, "frames": len(frames), "fps": fps, "duration": round(len(frames) / fps, 3),
            "source": entry["file"], "clip_in": start, "signature": sig}
    meta_p.write_text(json.dumps(meta, indent=1))
    return meta, None


def prep_all(proj, fps=12, max_seconds=20.0, force=False, look=None):
    proj = pathlib.Path(proj)
    fj = proj / "footage.json"
    if not fj.exists():
        print("no footage.json: nothing to prepare"); return {}, []
    spec = json.loads(fj.read_text())
    photos = proj / "photos.json"
    look = look or spec.get("grade") or (json.loads(photos.read_text()).get("grade") if photos.exists() else None) or "bw"
    metas, errors = {}, []
    for e in spec.get("footage", []):
        m, err = prep_clip(proj, e, look, fps, max_seconds, force=force)
        if err:
            errors.append(err); print(err)
        else:
            metas[e["id"]] = {k: m[k] for k in ("w", "h", "frames", "fps", "duration")}
            print(f"{e['id']}: {m['frames']} frames, {m['w']}x{m['h']}, {m['duration']}s ({look})")
    d = proj / "assets" / "prep" / "footage"; d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(metas, indent=1))
    return metas, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--max-seconds", type=float, default=20.0)
    ap.add_argument("--grade", default=None, help="bw, sepia or natural (default: footage.json, then photos.json)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    _, errors = prep_all(a.project, a.fps, a.max_seconds, a.force, a.grade)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
