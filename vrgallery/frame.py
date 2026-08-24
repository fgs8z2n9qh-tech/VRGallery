"""Publish one photo to the in-world picture frame.

VRGallery never uploads anything on its own: it writes the frame image (and a
small manifest) into a folder YOU choose — a synced folder, a git working copy,
a web root — and then optionally runs a publish command you configured. The
Udon side of the frame lives in `world/VRGalleryPhotoFrame.cs`.
"""
import json
import os
import subprocess
from datetime import datetime

from . import export

IMAGE_NAME = "frame.jpg"
MANIFEST_NAME = "frame.json"


def publish(photo_path, world, taken_at, people, frame_dir, publish_cmd="",
            max_px=2048, quality=88, captioned=False, accent=("#34d97a", "#8ae05e")):
    """Returns (ok, message). Blocking — call it from a worker thread."""
    if not frame_dir:
        return False, "No frame folder set (Settings ▸ In-world frame)."
    if not os.path.isdir(frame_dir):
        try:
            os.makedirs(frame_dir, exist_ok=True)
        except OSError:
            return False, "Frame folder could not be created."
    if not os.path.exists(photo_path):
        return False, "Photo not found."

    img_path = os.path.join(frame_dir, IMAGE_NAME)
    tmp = img_path + ".tmp"
    try:
        if captioned:
            export.captioned_card(photo_path, world, taken_at, people, tmp,
                                  max_px=max_px, quality=quality, accent=accent)
        else:
            export.downscaled_copy(photo_path, tmp, max_px=max_px, quality=quality)
        os.replace(tmp, img_path)
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, f"Could not write the frame image ({e.__class__.__name__})."

    try:
        with open(os.path.join(frame_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump({
                "world": world or "",
                "taken_at": taken_at or "",
                "people": list(people or []),
                "published_at": datetime.now().isoformat(timespec="seconds"),
                "source": os.path.basename(photo_path),
            }, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    if publish_cmd:
        try:
            # cmd.exe otherwise resolves a bare command name from the working
            # directory first, so anything dropped into the frame folder could
            # hijack e.g. "git". This env flag turns that lookup off.
            env = dict(os.environ, NoDefaultCurrentDirectoryInExePath="1")
            proc = subprocess.run(publish_cmd, cwd=frame_dir, shell=True, env=env,
                                  capture_output=True, text=True, timeout=180)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                detail = tail[-1][:120] if tail else f"exit {proc.returncode}"
                return False, f"Frame written, publish command failed: {detail}"
        except subprocess.TimeoutExpired:
            return False, "Frame written, but the publish command timed out."
        except Exception as e:
            return False, f"Frame written, publish command error: {e.__class__.__name__}"
        return True, "Frame published."
    return True, f"Frame image written to {frame_dir}."
