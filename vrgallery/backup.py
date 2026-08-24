"""Verified backup of the photo library to a folder you choose.

Copy-only and additive: it never deletes anything at the destination, and every
copied file is size-checked (optionally hash-checked) before it counts as done.
"""
import hashlib
import os
import shutil
import time

MANIFEST = "vrgallery-backup.txt"


def _digest(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _same(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b) and _digest(a) == _digest(b)
    except OSError:
        return False


def plan(photo_rows, dest_root):
    """Work out what is missing at the destination.

    Layout mirrors the source's YYYY-MM folder per photo day, so a backup is
    browsable on its own and stays stable as the library grows.

    Two photos from different source folders can share a basename (VRChat names
    by timestamp), which would otherwise silently overwrite each other at the
    destination. The second one to claim a name gets a suffix derived from its
    source path, and the iteration order is sorted so the same photo keeps the
    same destination on every run.
    """
    todo, already, bytes_todo = [], 0, 0
    claimed = {}
    for r in sorted(photo_rows, key=lambda row: (row["path"] or "").lower()):
        src = r["path"]
        day = (r["day"] or "")[:7] or "unsorted"
        name = os.path.basename(src)
        dst = os.path.join(dest_root, day, name)
        if claimed.setdefault(dst, src) != src:
            stem, ext = os.path.splitext(name)
            tag = hashlib.sha1(src.lower().encode("utf-8", "replace")).hexdigest()[:8]
            dst = os.path.join(dest_root, day, f"{stem}~{tag}{ext}")
            claimed[dst] = src
        try:
            ssize = r["filesize"] or os.path.getsize(src)
        except OSError:
            continue
        if os.path.exists(dst):
            try:
                if os.path.getsize(dst) == ssize:
                    already += 1
                    continue
            except OSError:
                pass
        todo.append((src, dst, ssize))
        bytes_todo += ssize
    return todo, already, bytes_todo


def run(todo, dest_root, verify_hash=False, progress=None, should_stop=None):
    """Copy the planned files. Returns (copied, failed, bytes_copied, errors)."""
    copied = failed = 0
    bytes_copied = 0
    errors = []
    total = len(todo)
    for i, (src, dst, ssize) in enumerate(todo):
        if should_stop and should_stop():
            break
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".part"
            shutil.copy2(src, tmp)
            if os.path.getsize(tmp) != ssize:
                raise OSError("size mismatch after copy")
            if verify_hash and _digest(tmp) != _digest(src):
                raise OSError("checksum mismatch after copy")
            # belt and braces: never replace a destination file that holds
            # something else, whatever put it there
            if os.path.exists(dst) and not _same(dst, tmp):
                stem, ext = os.path.splitext(dst)
                n = 2
                while os.path.exists(f"{stem} ({n}){ext}"):
                    n += 1
                dst = f"{stem} ({n}){ext}"
            os.replace(tmp, dst)
            copied += 1
            bytes_copied += ssize
        except Exception as e:
            failed += 1
            errors.append(f"{os.path.basename(src)}: {e.__class__.__name__}")
            try:
                os.remove(dst + ".part")
            except OSError:
                pass
        if progress:
            progress(i + 1, total, bytes_copied)

    try:
        with open(os.path.join(dest_root, MANIFEST), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  copied={copied} "
                    f"failed={failed} bytes={bytes_copied}\n")
    except OSError:
        pass
    return copied, failed, bytes_copied, errors


def last_run(dest_root):
    """The final manifest line, so the UI can say when the last backup was."""
    p = os.path.join(dest_root, MANIFEST)
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""
