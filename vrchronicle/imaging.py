"""Image work: shot-time parsing, thumbnails, luma/dhash, VRCX PNG metadata."""
import hashlib
import json
import os
import re
from datetime import datetime

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 268435456  # 16k x 16k safety cap

from . import paths

THUMB_PX = 512
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SKIP_DIR_NAMES = {"ipod photo cache"}

# VRChat_2026-08-21_18-52-08.986_3840x2160.png  (new)
RE_NEW = re.compile(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})(?:\.(\d{1,3}))?")
# VRChat_1920x1080_2021-01-01_12-00-00.000.png  (old — same regex hits the date part)


def parse_shot_time(filename):
    m = RE_NEW.search(filename)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
        ms = int((m.group(7) or "0").ljust(3, "0"))
        return datetime(y, mo, d, h, mi, s, ms * 1000)
    except ValueError:
        return None


def thumb_key(path, mtime, size):
    h = hashlib.sha1(f"{path.lower()}|{int(mtime)}|{size}".encode("utf-8", "replace")).hexdigest()
    return h


def thumb_path(key):
    return os.path.join(paths.THUMB_DIR, key + ".jpg")


def _dhash(gray_im):
    """64-bit difference hash from a 9x8 grayscale image -> hex string."""
    small = gray_im.resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            i = row * 9 + col
            bits = (bits << 1) | (1 if px[i] > px[i + 1] else 0)
    return "%016x" % bits


def dhash_distance(a, b):
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (ValueError, TypeError):
        return 64


def parse_vrcx_text(text_chunks):
    """VRCX screenshot-helper JSON from PNG text chunks.
    -> (world_id, world_name, [(name, uid)]) or None."""
    for _key, val in (text_chunks or {}).items():
        if not isinstance(val, str) or "{" not in val:
            continue
        s = val.strip()
        i = s.find("{")
        try:
            data = json.loads(s[i:])
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("application", "")).lower() not in ("vrcx", "screenshotmanager"):
            if "world" not in data:
                continue
        world = data.get("world") or {}
        wid = world.get("id") if isinstance(world, dict) else None
        wname = world.get("name") if isinstance(world, dict) else None
        players = []
        for p in data.get("players") or []:
            if isinstance(p, dict) and p.get("displayName"):
                players.append((str(p["displayName"]), p.get("id")))
        if wid or wname or players:
            return wid, wname, players
    return None


def deep_scan(path, key):
    """Single decode pass: writes the disk thumbnail and returns
    dict(width, height, luma, dhash, vrcx) — vrcx may be None."""
    out = thumb_path(key)
    with Image.open(path) as im:
        im.load()
        vrcx = None
        if im.format == "PNG":
            try:
                vrcx = parse_vrcx_text(getattr(im, "text", None))
            except Exception:
                vrcx = None
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        rgb = im.convert("RGB")
    rgb.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    tmp = out + ".tmp"
    rgb.save(tmp, "JPEG", quality=85)
    os.replace(tmp, out)
    gray = rgb.convert("L")
    small = gray.resize((64, 64), Image.BILINEAR)
    data = list(small.getdata())
    luma = sum(data) / len(data)
    dh = _dhash(gray)
    return {"width": w, "height": h, "luma": luma, "dhash": dh, "vrcx": vrcx}


def convert_to_jpeg(path, quality):
    """PNG -> JPEG next to the original. Returns (new_path, new_size).
    Never touches the original file (the caller recycles it after verifying)."""
    stem, _ext = os.path.splitext(path)
    new_path = stem + ".jpg"
    n = 1
    while os.path.exists(new_path):
        new_path = f"{stem}_{n}.jpg"
        n += 1
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        rgb = im.convert("RGB")
    tmp = new_path + ".tmp"
    rgb.save(tmp, "JPEG", quality=quality, optimize=True)
    os.replace(tmp, new_path)
    # verify the new file decodes before anyone deletes the source
    with Image.open(new_path) as chk:
        chk.load()
    return new_path, os.path.getsize(new_path)


def shrink_for_upload(path, max_bytes=8 * 1024 * 1024, tmp_dir=None):
    """If the file is too big for a Discord webhook, produce a smaller JPEG copy.
    Returns a path (original if already small enough) and whether it's temporary."""
    try:
        if os.path.getsize(path) <= max_bytes:
            return path, False
    except OSError:
        return path, False
    import tempfile
    tmp_dir = tmp_dir or paths.APPDIR
    fd, out = tempfile.mkstemp(prefix="upload_", suffix=".jpg", dir=tmp_dir)
    os.close(fd)                 # unique name: concurrent shares must not collide
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im).convert("RGB")
        for target, q in ((2560, 90), (2560, 82), (1920, 80), (1600, 75)):
            copy = im.copy()
            copy.thumbnail((target, target), Image.LANCZOS)
            copy.save(out, "JPEG", quality=q)
            if os.path.getsize(out) <= max_bytes:
                break
    return out, True


def scan_folder_files(folders):
    """Yield absolute file paths of images under the configured folders,
    skipping junk dirs (e.g. 'iPod Photo Cache')."""
    seen = set()
    for root_folder in folders:
        if not os.path.isdir(root_folder):
            continue
        for root, dirs, files in os.walk(root_folder):
            dirs[:] = [d for d in dirs
                       if d.lower() not in SKIP_DIR_NAMES and not d.startswith(".")]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in IMAGE_EXTS:
                    continue
                p = os.path.join(root, fn)
                pl = p.lower()
                if pl in seen:
                    continue
                seen.add(pl)
                yield p
