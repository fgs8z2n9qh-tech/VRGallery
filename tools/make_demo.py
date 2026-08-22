r"""Build a throwaway, pseudonymised copy of the library for screenshots.

Documentation screenshots of a *social* app would otherwise publish two things
that are not the author's to publish: other people's VRChat display names (and,
on the People page, how often and since when they are seen), and the photos
themselves, which are personal and often have other people in frame.

So this builds a library that is structurally real and personally empty:
  * every display name and avatar name becomes a stable made-up one,
  * user ids are cleared and secrets are stripped from the config,
  * every photo is replaced by a generated scene, with the thumbnail cache
    pre-filled so the app never re-analyses (which would flatten the duplicate
    groups the Cleanup page is meant to demonstrate).

World names, dates, counts and groupings are left alone — those are what the
screenshots are supposed to show.

    python tools\make_demo.py [--out DIR] [--scenes N] [--keep-photos]
    .venv\Scripts\python.exe run.py --data-dir DIR --no-index --shot x.png --page moments

--no-index matters: an index pass would write the real names straight back in
from VRChat's still-growing log file.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from vrchronicle import paths

FIRST = ["Nova", "Pixel", "Juniper", "Echo", "Marlow", "Bramble", "Cinder", "Wren",
         "Quill", "Sable", "Tumble", "Vesper", "Onyx", "Pepper", "Rune", "Willow",
         "Fennec", "Halcyon", "Indigo", "Jasper", "Koda", "Lumen", "Mirth", "Nimbus",
         "Opal", "Puddle", "Quartz", "Ripple", "Sorrel", "Thistle", "Umber", "Vale"]
SUFFIX = ["", "", "", "_VR", "42", "_", "07", "x", "99", "_hm", "12"]
# avatar names carry real names just as often as display names do
AV_ADJ = ["Mossy", "Sunlit", "Velvet", "Copper", "Dappled", "Frosted", "Amber",
          "Twilight", "Cobalt", "Hazel", "Sable", "Crimson"]
AV_NOUN = ["Fox", "Otter", "Lynx", "Wolf", "Dragon", "Raccoon", "Hare", "Sparrow",
           "Tiger", "Deer", "Corgi", "Serval"]


def alias(name, seed="vrchronicle-demo"):
    """Stable pseudonym: the same input always yields the same fake name."""
    h = hashlib.sha1((seed + "|" + name).encode("utf-8", "replace")).digest()
    return FIRST[h[0] % len(FIRST)] + SUFFIX[h[1] % len(SUFFIX)] + (
        str(h[2] % 90 + 10) if h[3] % 3 == 0 else "")


def avatar_alias(name):
    h = hashlib.sha1(("avatar|" + name).encode("utf-8", "replace")).digest()
    return f"{AV_ADJ[h[0] % len(AV_ADJ)]} {AV_NOUN[h[1] % len(AV_NOUN)]}"


# ---------------------------------------------------------------- scene art

SKIES = [
    ((28, 34, 72), (232, 138, 122)),      # dusk
    ((12, 16, 38), (46, 84, 146)),        # night
    ((126, 196, 232), (238, 244, 250)),   # clear day
    ((250, 186, 120), (120, 74, 122)),    # sunset
    ((16, 52, 60), (96, 190, 176)),       # teal morning
    ((44, 24, 60), (196, 92, 148)),       # neon
    ((196, 214, 226), (246, 248, 250)),   # overcast
    ((10, 24, 30), (28, 96, 108)),        # deep water
]


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_scene(seed, size=(1920, 1080)):
    """A plausible VR-world vista built from nothing but a seed.

    Not anybody's photo: a gradient sky, a light source, layered silhouettes and
    a few motes. Enough variety that a grid of them reads as a photo library.
    """
    import random

    from PIL import Image, ImageDraw, ImageFilter

    rnd = random.Random(seed)
    w, h = size
    top, bottom = SKIES[rnd.randrange(len(SKIES))]
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = int(h * rnd.uniform(0.55, 0.75))
    for y in range(h):
        t = min(1.0, y / max(1, horizon))
        d.line([(0, y), (w, y)], fill=_lerp(top, bottom, t ** 0.85))

    # a sun or moon, with a soft bloom
    if rnd.random() < 0.8:
        cx = rnd.randint(int(w * 0.1), int(w * 0.9))
        cy = rnd.randint(int(h * 0.12), horizon - 40)
        r = rnd.randint(int(h * 0.03), int(h * 0.09))
        glow = Image.new("RGB", (w, h), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([cx - r * 3, cy - r * 3, cx + r * 3, cy + r * 3],
                   fill=(90, 84, 66))
        img = Image.blend(img, Image.blend(img, glow.filter(
            ImageFilter.GaussianBlur(r * 1.6)), 0.0), 0.0)
        d = ImageDraw.Draw(img)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(252, 248, 232))

    # motes / stars above the horizon
    for _ in range(rnd.randint(40, 160)):
        x = rnd.randint(0, w)
        y = rnd.randint(0, horizon)
        s = rnd.choice([1, 1, 1, 2])
        v = rnd.randint(180, 255)
        d.ellipse([x, y, x + s, y + s], fill=(v, v, min(255, v + 10)))

    # three receding silhouette layers
    layers = rnd.randint(2, 4)
    for layer in range(layers):
        depth = (layer + 1) / layers
        shade = _lerp(bottom, (8, 10, 16), 0.35 + 0.5 * depth)
        base = horizon + int((h - horizon) * (layer / max(1, layers)) * 0.55)
        pts = [(0, h)]
        x = 0
        while x < w:
            step = rnd.randint(int(w * 0.06), int(w * 0.2))
            peak = base - rnd.randint(int(h * 0.02), int(h * 0.22 * (1.2 - depth)))
            pts.append((x, peak))
            x += step
        pts.append((w, base))
        pts.append((w, h))
        d.polygon(pts, fill=shade)

    # a couple of upright structures, like a building or a torii in the distance
    if rnd.random() < 0.55:
        shade = _lerp(bottom, (6, 8, 14), 0.75)
        for _ in range(rnd.randint(1, 4)):
            bw = rnd.randint(int(w * 0.02), int(w * 0.07))
            bx = rnd.randint(0, w - bw)
            bh = rnd.randint(int(h * 0.08), int(h * 0.3))
            by = horizon + rnd.randint(-20, 60)
            d.rectangle([bx, by - bh, bx + bw, by + 10], fill=shade)

    # gentle vignette so the grid does not look like flat wallpaper
    vig = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vig).ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(w * 0.06))
    img = Image.composite(img, Image.new("RGB", (w, h), (6, 8, 12)), vig)
    return img


def swap_in_scenes(con, photo_dir, out_dir, count):
    """Repoint every photo at a generated scene and pre-render its thumbnail.

    The thumbnail is written under the exact cache key the app will look for, so
    the app never runs a deep scan on the stand-in — which matters because that
    would overwrite the stored perceptual hashes, and the Cleanup page's
    duplicate groups (a real, interesting property of the library) would
    collapse into one meaningless pile.
    """
    from vrchronicle import imaging

    os.makedirs(photo_dir, exist_ok=True)
    thumb_dir = os.path.join(out_dir, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    import io

    # photos.path is UNIQUE, so every row needs its own filename. Hard links let
    # a few dozen generated files back thousands of paths for almost no disk.
    masters = []
    for i in range(count):
        src = os.path.join(photo_dir, f"_scene_{i:03d}.png")
        img = make_scene(i)
        img.save(src, "PNG")
        thumb = img.copy()
        thumb.thumbnail((imaging.THUMB_PX, imaging.THUMB_PX))
        buf = io.BytesIO()
        thumb.save(buf, "JPEG", quality=85)
        st = os.stat(src)
        masters.append({"src": src, "size": st.st_size, "mtime": st.st_mtime,
                        "dims": img.size, "thumb": buf.getvalue()})

    # The recorded filesize/mtime are kept exactly as they were: they drive the
    # size statistics the screenshots are meant to show, and the thumbnail cache
    # key is derived from them, so the stand-in thumbnails must be filed under
    # those values rather than the tiny stand-in file's own.
    rows = con.execute(
        "SELECT id, filename, filesize, mtime FROM photos ORDER BY id").fetchall()
    used = set()
    for pid, filename, filesize, mtime in rows:
        m = masters[pid % len(masters)]
        name = filename or f"VRChat_{pid}.png"
        stem, ext = os.path.splitext(name)
        while name.lower() in used:
            stem += "_"
            name = stem + ext
        used.add(name.lower())
        dst = os.path.join(photo_dir, name)
        if not os.path.exists(dst):
            try:
                os.link(m["src"], dst)
            except OSError:
                shutil.copy2(m["src"], dst)
        key = imaging.thumb_key(dst, mtime or 0, filesize or 0)
        tp = os.path.join(thumb_dir, key + ".jpg")
        if not os.path.exists(tp):
            with open(tp, "wb") as f:
                f.write(m["thumb"])
        con.execute(
            "UPDATE photos SET path=?, folder=?, filename=?,"
            " width=?, height=?, scanned=1, missing=0 WHERE id=?",
            (dst, photo_dir, name, m["dims"][0], m["dims"][1], pid))
    con.commit()
    return len(masters)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.environ.get("TEMP", "."),
                                                  "vrchronicle-demo"))
    ap.add_argument("--scenes", type=int, default=64,
                    help="how many generated scenes to spread over the library")
    ap.add_argument("--keep-photos", action="store_true",
                    help="show the real photos (never do this for anything public)")
    a = ap.parse_args()
    src_dir = paths.APPDIR
    src_db = paths.DB_PATH
    if not os.path.exists(src_db):
        print("no library at", src_db)
        return 1
    out = os.path.abspath(a.out)
    if os.path.isdir(out):
        # only ever remove a folder we made ourselves
        if not os.path.exists(os.path.join(out, ".vrchronicle-demo")):
            print("refusing to touch", out, "- not a demo folder")
            return 1
        thumbs = os.path.join(out, "thumbs")
        if os.path.isdir(thumbs):
            subprocess.run(["cmd", "/c", "rmdir", thumbs], capture_output=True)
        shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, ".vrchronicle-demo"), "w").close()

    # a checkpointed copy, so nothing is left in the WAL
    con = sqlite3.connect(src_db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    dst_db = os.path.join(out, "vrchronicle.db")
    shutil.copy2(src_db, dst_db)

    if a.keep_photos:
        # share the real thumbnail cache instead of duplicating gigabytes
        link = subprocess.run(["cmd", "/c", "mklink", "/J",
                               os.path.join(out, "thumbs"), paths.THUMB_DIR],
                              capture_output=True, text=True)
        if link.returncode != 0:
            os.makedirs(os.path.join(out, "thumbs"), exist_ok=True)
    else:
        os.makedirs(os.path.join(out, "thumbs"), exist_ok=True)

    con = sqlite3.connect(dst_db)
    names = set()
    for table in ("photo_players", "session_players"):
        names |= {r[0] for r in con.execute(f"SELECT DISTINCT name FROM {table}")}
    names |= {r[0] for r in con.execute("SELECT DISTINCT player FROM avatar_events")}
    # aliases must stay unique: photo_players has a UNIQUE(photo_id, name) key,
    # so two people collapsing onto one fake name would fail the update
    mapping, taken = {}, set()
    for n in sorted(x for x in names if x):
        base = alias(n)
        fake, i = base, 2
        while fake in taken:
            fake = f"{base}{i}"
            i += 1
        taken.add(fake)
        mapping[n] = fake
    for real, fake in mapping.items():
        con.execute("UPDATE photo_players SET name=? WHERE name=?", (fake, real))
        con.execute("UPDATE session_players SET name=? WHERE name=?", (fake, real))
        con.execute("UPDATE avatar_events SET player=? WHERE player=?", (fake, real))
    # avatar names are often "<real name> <something>", so they go too
    avatars = {r[0] for r in con.execute(
        "SELECT DISTINCT avatar_name FROM photos WHERE avatar_name IS NOT NULL")}
    avatars |= {r[0] for r in con.execute("SELECT DISTINCT avatar FROM avatar_events")}
    av_map, av_taken = {}, set()
    for n in sorted(x for x in avatars if x):
        base = avatar_alias(n)
        fake, i = base, 2
        while fake in av_taken:
            fake = f"{base} {i}"
            i += 1
        av_taken.add(fake)
        av_map[n] = fake
    for real, fake in av_map.items():
        con.execute("UPDATE photos SET avatar_name=? WHERE avatar_name=?", (fake, real))
        con.execute("UPDATE avatar_events SET avatar=? WHERE avatar=?", (fake, real))

    # user ids identify people just as well as names do
    con.execute("UPDATE photo_players SET user_id=NULL")
    con.execute("UPDATE session_players SET user_id=NULL")
    con.commit()

    photo_dir = os.path.join(out, "photos")
    if not a.keep_photos:
        n_scenes = swap_in_scenes(con, photo_dir, out, a.scenes)
        print(f"{n_scenes} generated scenes stand in for every photo")
    con.close()

    # config: same folders and accent, pseudonymised self names, no secrets
    cfg = {}
    try:
        with open(os.path.join(src_dir, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except OSError:
        pass
    cfg["self_names"] = [mapping.get(n, alias(n)) for n in cfg.get("self_names", [])]
    for secret in ("webhook_url", "api_token", "frame_dir", "frame_publish_cmd",
                   "backup_dir", "adb_path"):
        cfg[secret] = ""
    if not a.keep_photos:
        cfg["folders"] = [photo_dir]    # the real library must stay out of sight
    cfg["api_enabled"] = False          # never open a port from the demo copy
    cfg["close_to_tray"] = False
    cfg["window"] = [80, 60, 1500, 940, False]
    with open(os.path.join(out, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print(f"demo library at {out}")
    print(f"{len(mapping)} display names and {len(av_map)} avatar names "
          "pseudonymised, user ids cleared")
    print("self names ->", cfg["self_names"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
