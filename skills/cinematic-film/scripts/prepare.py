#!/usr/bin/env python3
"""The production's assets, prepared for the engine: board textures, graded photos, footage frames
and map data. The docpipe stage `assets` runs this after the visuals are approved; it works on
its own too.

  python3 prepare.py --project P [--force] [--download-maps] [--offline]

It wraps the existing tools (their own command lines are unchanged):
  textures   prep_assets.textures: the boards behind the looks, made once
  photos     photos.json -> assets/prep/photos/<id>.jpg and meta.json, graded with prep_assets.grade
  footage    footage.json -> assets/prep/footage/<id>/ frames (prep_footage: cached by signature)
  maps       map.json -> assets/prep/map_<name>.json (make_map.build)

In a production with editions it prepares the shared assets at the production root, once, for
every edition (each edition links assets/).

Resume and protection: a photo or map is made again only when what it is made from changed (the
source file, crop, kind, grade; the map spec and its boundary data). assets/prep/prepared.json
records the hash of every file written here; a prepared file you edited, or one this tool did not
record making, is kept, and --force replaces it keeping a .bak. Originals (assets/photos,
assets/footage, photos.json, footage.json, map.json) are only read.

Downloads: a map whose boundary data is a URL not yet in assets/data/ is downloaded only with
--download-maps (public-domain boundary data, cached after one download), never offline
(--offline or CINEMATIC_OFFLINE=1). A local file or cached data needs no network.

A photo or clip that is missing or cannot be read is a warning and the stage is "partial": the film
shows a designed card there until it is fixed. Without numpy and Pillow (or ffmpeg for footage)
nothing can be prepared, which is also partial, not a failure.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doclib as L  # noqa: E402

BUILT_BY = "prepare.py"


def ap_paths(proj):
    root = pathlib.Path(L.paths(proj)["root"])
    prep = root / "assets" / "prep"
    return {"root": root, "prep": prep, "photos_json": root / "photos.json", "footage_json": root / "footage.json",
            "map_json": root / "map.json", "photos_src": root / "assets" / "photos", "footage_src": root / "assets" / "footage",
            "photos_out": prep / "photos", "manifest": prep / "prepared.json", "data": root / "assets" / "data"}


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_obj(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def offline(flag=False):
    return flag or os.environ.get("CINEMATIC_OFFLINE") == "1"


def fingerprint(proj):
    """What the stage depends on, cheaply: the specs, the size and time of every source file they
    name, and what was prepared. Used by docpipe to decide whether to run again."""
    p = ap_paths(proj)
    parts = []
    for f in (p["photos_json"], p["footage_json"], p["map_json"], p["manifest"], p["photos_out"] / "meta.json",
              p["prep"] / "footage" / "meta.json"):
        parts.append([f.name, f.read_bytes().hex() if f.exists() else None])

    def stat(f):
        try:
            s = f.stat()
            return [str(f), s.st_size, s.st_mtime_ns]
        except OSError:
            return [str(f), None]
    spec = L.load(p["photos_json"], {}) if p["photos_json"].exists() else {}
    for ph in spec.get("photos", []):
        if ph.get("file"):
            parts.append(stat(p["photos_src"] / ph["file"]))
        parts.append(stat(p["photos_out"] / f"{ph.get('id')}.jpg"))
    fspec = L.load(p["footage_json"], {}) if p["footage_json"].exists() else {}
    for e in fspec.get("footage", []):
        parts.append(stat(p["footage_src"] / e.get("file", "")))
    mspec = L.load(p["map_json"], {}) if p["map_json"].exists() else {}
    for m in mspec.get("maps", []):
        parts.append(stat(p["prep"] / f"map_{m.get('name')}.json"))
        for src in (m.get("source"), (m.get("neighbors") or {}).get("source")):
            if src:
                parts.append(stat(source_path(p, src)))
    return sha_obj(parts)[:16]


def source_path(p, src):
    """Where a map's boundary data is on disk: a local file, or the download cache for a URL."""
    if str(src).startswith(("http://", "https://")):
        return p["data"] / pathlib.Path(str(src).split("?")[0]).name
    f = pathlib.Path(src)
    return f if f.is_absolute() else p["root"] / f


class Protected:
    """Files this tool writes into assets/prep, with the hash of what it wrote."""

    def __init__(self, p, force, r):
        self.p, self.force, self.r = p, force, r
        self.m = L.load(p["manifest"], {"built_by": BUILT_BY, "files": {}})
        self.m.setdefault("files", {})

    def rel(self, f):
        return str(pathlib.Path(f).relative_to(self.p["prep"]))

    def entry(self, f):
        return self.m["files"].get(self.rel(f), {})

    def current(self, f, sig):
        """True when f is the one made from sig and unchanged since."""
        e = self.entry(f)
        return f.exists() and e.get("sig") == sig and e.get("sha") == sha_file(f)

    def may_write(self, f, what):
        """False (and a warning) when f is yours: edited since it was made, or never recorded."""
        if not f.exists():
            return True
        e = self.entry(f)
        if e.get("sha") == sha_file(f):
            return True
        if not self.force:
            why = "was changed after it was prepared" if e else "was not prepared by this tool"
            self.r.warn(f"{what}: {self.rel(f)} {why}; it is yours and kept (--force replaces it, keeping a .bak)")
            return False
        shutil.copyfile(f, f.with_name(f.name + ".bak"))
        self.r.note(f"{what}: your {f.name} kept as {f.name}.bak")
        return True

    def record(self, f, sig):
        self.m["files"][self.rel(f)] = {"sig": sig, "sha": sha_file(f)}

    def save(self):
        L.save(self.p["manifest"], self.m)


def prep_photos(p, guard, r, prep_assets, Image):
    spec = L.load(p["photos_json"])
    look = spec.get("grade", "bw")
    out = p["photos_out"]
    out.mkdir(parents=True, exist_ok=True)
    meta, made, kept = {}, 0, 0
    for ph in spec.get("photos", []):
        pid = ph.get("id")
        src = p["photos_src"] / ph["file"] if ph.get("file") else None
        dst = out / f"{pid}.jpg"
        if not src or not src.exists():
            r.warn(f"photo {pid}: {ph.get('file') or 'no file yet'} is not in assets/photos; a designed card shows instead")
            r.partial = True
            continue
        sig = sha_obj([sha_file(src), ph.get("crop"), ph.get("kind", "photo"), look, prep_assets.MAX_SIDE])
        if not guard.current(dst, sig):
            if not guard.may_write(dst, f"photo {pid}"):
                kept += 1
            else:
                try:
                    im = Image.open(src)
                    im.load()
                except Exception as e:                       # noqa: BLE001 - any unreadable image
                    r.warn(f"photo {pid}: {src.name} cannot be read ({type(e).__name__}); a designed card shows instead")
                    r.partial = True
                    continue
                im = im.convert("RGBA") if im.mode in ("P", "LA", "PA") else im
                if im.mode == "RGBA":
                    bg = Image.new("RGB", im.size, (235, 228, 214)); bg.paste(im, mask=im.split()[3]); im = bg
                if ph.get("crop"):
                    w, h = im.size; c = ph["crop"]
                    im = im.crop((int(c[0] * w), int(c[1] * h), int(c[2] * w), int(c[3] * h)))
                if max(im.size) > prep_assets.MAX_SIDE:
                    im.thumbnail((prep_assets.MAX_SIDE, prep_assets.MAX_SIDE), Image.LANCZOS)
                g = prep_assets.grade(im, ph.get("kind", "photo"), look)
                tmp = dst.with_name(dst.stem + ".tmp.jpg")
                g.save(tmp, quality=93)
                tmp.replace(dst)
                guard.record(dst, sig)
                made += 1
        with Image.open(dst) as im:
            meta[pid] = {"w": im.width, "h": im.height, "kind": ph.get("kind", "photo")}
    L.save(out / "meta.json", meta)
    r.note(f"photos: {len(meta)} ready ({look}); {made} graded now" + (f", {kept} of yours kept" if kept else ""))


def prep_footage_all(p, r):
    if not shutil.which("ffmpeg"):
        r.warn("footage: ffmpeg is not installed, so the clips cannot be prepared; designed cards show instead")
        r.partial = True
        return
    import prep_footage
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        metas, errors = prep_footage.prep_all(p["root"])
    for e in errors:
        r.warn(f"footage {e}; a designed card shows instead")
        r.partial = True
    r.note(f"footage: {len(metas)} clip(s) ready")


def prep_maps(p, guard, r, download, offline_):
    import make_map
    spec = L.load(p["map_json"])
    for m in spec.get("maps", []):
        name = m.get("name")
        if not name or not m.get("source"):
            r.error("map.json: every map needs a name and a source"); continue
        sources = [m["source"]] + ([m["neighbors"]["source"]] if (m.get("neighbors") or {}).get("source") else [])
        missing = [s for s in sources if not source_path(p, s).exists()]
        urls = [s for s in missing if str(s).startswith(("http://", "https://"))]
        if missing and len(urls) < len(missing):
            r.error(f"map {name}: {', '.join(s for s in missing if s not in urls)} not found"); continue
        if urls and (offline_ or not download):
            r.error(f"map {name}: its boundary data ({', '.join(urls)}) is not downloaded yet. "
                    + ("Offline: nothing is downloaded. " if offline_ else "")
                    + "Run docpipe.py run --download-maps (public-domain data, downloaded once into assets/data), "
                      "or set \"source\" to a local file")
            continue
        sig = sha_obj([m] + [sha_file(source_path(p, s)) if source_path(p, s).exists() else s for s in sources])
        dst = p["prep"] / f"map_{name}.json"
        if guard.current(dst, sig):
            continue
        if not guard.may_write(dst, f"map {name}"):
            continue
        spec_ = json.loads(json.dumps(m))                      # local sources resolved against the project
        for d in (spec_, spec_.get("neighbors") or {}):
            if d.get("source") and not str(d["source"]).startswith(("http://", "https://")):
                d["source"] = str(source_path(p, d["source"]))
        log = io.StringIO()
        try:
            with contextlib.redirect_stdout(log):
                data = make_map.build(spec_, p["data"])
        except (Exception, SystemExit) as e:                 # noqa: BLE001 - make_map exits on a bad spec
            r.error(f"map {name}: could not be built ({type(e).__name__}: {str(e)[:200]})"); continue
        for ln in log.getvalue().splitlines():
            if "warning" in ln:
                r.warn(f"map {name}: {ln.strip()}")
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_text(json.dumps(data)); tmp.replace(dst)
        guard.record(dst, sig)
        r.note(f"map {name}: {len(data['regions'])} regions, {len(data['neighbors'])} neighbours, {len(data['places'])} places")


def run(proj, force=False, download_maps=False, offline_flag=False):
    p = ap_paths(proj)
    r = L.Result()
    r.partial = False
    has = {k: p[k].exists() for k in ("photos_json", "footage_json", "map_json")}
    try:
        import numpy  # noqa: F401
        from PIL import Image
        import prep_assets
    except ImportError as e:
        r.warn(f"assets: {e.name} is not installed (pip install -r requirements.txt), so nothing could be prepared; "
               "the film tools need it too")
        r.partial = True
        return r
    p["prep"].mkdir(parents=True, exist_ok=True)
    guard = Protected(p, force, r)
    with contextlib.redirect_stdout(io.StringIO()):
        prep_assets.textures(p["prep"])                     # made once; never replaced here
    if has["photos_json"]:
        prep_photos(p, guard, r, prep_assets, Image)
    if has["footage_json"]:
        prep_footage_all(p, r)
    if has["map_json"]:
        prep_maps(p, guard, r, download_maps, offline(offline_flag))
    guard.save()
    if not any(has.values()):
        r.note("no photos.json, footage.json or map.json yet: board textures only")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--force", action="store_true", help="replace prepared files you edited (keeping a .bak)")
    ap.add_argument("--download-maps", action="store_true", help="download map boundary data that is not cached yet")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    r = run(a.project, a.force, a.download_maps, a.offline)
    print(r.report("assets"))
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
