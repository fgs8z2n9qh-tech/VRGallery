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
# recordings people make of the same sessions, usually with OBS into the same
# folder; indexed so they sit on the timeline, but never decoded
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
SKIP_DIR_NAMES = {"ipod photo cache"}


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS

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


KNOWN_WRITERS = ("vrchat", "vrcx", "screenshotmanager")

# Bump when parse_photo_meta starts reading something new: a library indexed by
# an older build gets its photos' metadata read again, without touching pixels.
META_VERSION = 2


def read_meta(path):
    """The embedded metadata of one PNG, without decoding it.

    Pillow reads the text chunks out of the header, so this costs a file open
    and a few kilobytes -- which is what makes it cheap enough to re-read a
    whole library when the parser learns a new field, instead of putting every
    photo back through a full deep scan and rewriting every thumbnail.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            return parse_photo_meta(getattr(im, "text", None))
    except Exception:
        return None


def parse_photo_meta(text_chunks):
    """The JSON VRChat or VRCX embeds in a screenshot's PNG text chunks.

    Both write the same shape -- VRCX modelled its helper on VRChat's own
    metadata -- so one parser reads either, and says which it was:

        {"application": "VRChat", "version": 1,
         "author": {"id": "usr_...", "displayName": "..."},
         "world":  {"id": "wrld_...", "name": "...",
                    "instanceId": "wrld_...:51899~hidden(usr_...)~region(eu)"},
         "players": [{"id": "usr_...", "displayName": "..."}, ...]}

    Three things here that the old VRCX-only reader threw away, and that the
    photos really carry -- of 600 in this library, 555 had all of them:

      * the AUTHOR, which is who took the shot;
      * the INSTANCE ID, which says whether you were in a public world, a
        friends+ instance or a group one -- until now that could only come from
        the logs, and VRChat deletes those after a few sessions;
      * the region, which comes out of the same string.

    -> dict, or None if there was nothing to read.
    """
    from . import vrclog
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
        app = str(data.get("application", "")).lower()
        if app not in KNOWN_WRITERS and "world" not in data:
            continue
        world = data.get("world") if isinstance(data.get("world"), dict) else {}
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        players = []
        for pl in data.get("players") or []:
            if isinstance(pl, dict) and pl.get("displayName"):
                players.append((str(pl["displayName"]), pl.get("id")))

        # "wrld_xxx:51899~hidden(usr_y)~region(eu)" -- everything after the
        # FIRST colon is what the log parser already knows how to read, so the
        # two ways of learning an instance type cannot drift apart.
        inst = str(world.get("instanceId") or "")
        itype, region = "", ""
        if inst:
            itype, region = vrclog.parse_instance(inst.split(":", 1)[-1])

        out = {
            "source": "vrchat" if app == "vrchat" else "vrcx",
            "world_id": world.get("id") or None,
            "world_name": world.get("name") or None,
            "instance_id": inst or None,
            "instance_type": itype or "",
            "region": region or "",
            "author_name": str(author["displayName"]) if author.get("displayName") else None,
            "author_id": author.get("id") or None,
            "players": players,
        }
        if any((out["world_id"], out["world_name"], out["players"],
                out["author_name"], out["instance_type"])):
            return out
    return None


def parse_vrcx_text(text_chunks):
    """Kept for callers that only want the three things it used to return."""
    meta = parse_photo_meta(text_chunks)
    if meta is None:
        return None
    return meta["world_id"], meta["world_name"], meta["players"]


def deep_scan(path, key):
    """Single decode pass: writes the disk thumbnail and returns
    dict(width, height, luma, dhash, vrcx) — vrcx is parse_photo_meta's dict
    or None."""
    out = thumb_path(key)
    with Image.open(path) as im:
        im.load()
        vrcx = None
        if im.format == "PNG":
            try:
                vrcx = parse_photo_meta(getattr(im, "text", None))
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
                if ext not in MEDIA_EXTS:
                    continue
                p = os.path.join(root, fn)
                pl = p.lower()
                if pl in seen:
                    continue
                seen.add(pl)
                yield p
