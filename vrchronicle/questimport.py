"""Pull VRChat screenshots off a standalone headset over ADB.

Photos taken on a Quest never touch the PC, so they are invisible to the rest of
the app. This copies them into a chosen folder (normally one of your indexed
photo folders) and leaves the originals on the headset alone.
"""
import os
import re
import subprocess

# where VRChat puts pictures on Android; the first hit wins
REMOTE_DIRS = (
    "/sdcard/Android/data/com.vrchat.mobile.playstore/files/VRChat",
    "/sdcard/Android/data/com.vrchat.mobile.playstore/files/Pictures",
    "/sdcard/Pictures/VRChat",
    "/sdcard/DCIM/VRChat",
)
COMMON_ADB = (
    r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe",
    r"%ProgramFiles%\SideQuest\resources\app.asar.unpacked\build\platform-tools\adb.exe",
    r"%LOCALAPPDATA%\Programs\SideQuest\resources\app.asar.unpacked\build\platform-tools\adb.exe",
    r"%USERPROFILE%\platform-tools\adb.exe",
    r"C:\platform-tools\adb.exe",
)
RE_IMAGE = re.compile(r"\.(png|jpg|jpeg)$", re.I)
NO_FLASH = 0x08000000        # CREATE_NO_WINDOW: never flash a console


def find_adb(configured=""):
    if configured and os.path.exists(configured):
        return configured
    for cand in COMMON_ADB:
        p = os.path.expandvars(cand)
        if os.path.exists(p):
            return p
    from shutil import which
    return which("adb") or ""


def _run(adb, args, timeout=60):
    return subprocess.run([adb] + args, capture_output=True, text=True,
                          timeout=timeout, creationflags=NO_FLASH)


def devices(adb):
    """-> list of (serial, state). Empty when nothing is plugged in or authorised."""
    try:
        out = _run(adb, ["devices"], timeout=20)
    except Exception:
        return []
    found = []
    for line in (out.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            found.append((parts[0], parts[1]))
    return found


def list_remote(adb, serial=""):
    """-> (remote_dir, [filenames]) for the first directory that has images."""
    base = ["-s", serial] if serial else []
    for d in REMOTE_DIRS:
        try:
            out = _run(adb, base + ["shell", "ls", "-1", d], timeout=40)
        except Exception:
            continue
        text = out.stdout or ""
        if "No such file" in text or out.returncode != 0:
            continue
        names = [n.strip() for n in text.splitlines()
                 if n.strip() and RE_IMAGE.search(n.strip())]
        if names:
            return d, names
    return "", []


def pull(adb, remote_dir, names, dest_dir, serial="", progress=None, should_stop=None):
    """Copy the files that are not already in dest_dir. -> (pulled, skipped, errors)."""
    base = ["-s", serial] if serial else []
    os.makedirs(dest_dir, exist_ok=True)
    pulled = skipped = 0
    errors = []
    total = len(names)
    for i, name in enumerate(names):
        if should_stop and should_stop():
            break
        dst = os.path.join(dest_dir, name)
        if os.path.exists(dst):
            skipped += 1
        else:
            tmp = dst + ".part"
            try:
                out = _run(adb, base + ["pull", f"{remote_dir}/{name}", tmp], timeout=300)
                if out.returncode != 0 or not os.path.exists(tmp):
                    raise OSError((out.stderr or "adb pull failed").strip()[:100])
                os.replace(tmp, dst)
                pulled += 1
            except Exception as e:
                errors.append(f"{name}: {e.__class__.__name__}")
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if progress:
            progress(i + 1, total, pulled)
    return pulled, skipped, errors
