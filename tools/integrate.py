r"""Register VR Gallery with the user's other apps (Atlas card + Hexpad key).

Both targets are LIVE user configs, so every write here:
  * makes a timestamped .bak first,
  * writes UTF-8 without a BOM through a temp file + os.replace,
  * refuses to clobber anything that already exists (idempotent).

Run:  python tools\integrate.py [--atlas] [--hexpad]   (no flags = both)
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.dirname(HERE)      # ...\Desktop\project
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
APPDATA = os.environ.get("APPDATA", "")
ICON_SRC = os.path.join(HERE, "assets", "VRGallery.ico")


def is_running(exe_name):
    """Both target apps hold their whole config in memory and rewrite it wholesale,
    so editing the file underneath a running instance just gets clobbered."""
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
                             capture_output=True, text=True, timeout=15)
        return exe_name.lower() in (out.stdout or "").lower()
    except Exception:
        return False


def backup(path):
    if os.path.exists(path):
        bak = f"{path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(path, bak)
        return bak
    return None


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


# ---------------------------------------------------------------- Atlas

def do_atlas():
    assets = os.path.join(PROJ, "Atlas", "assets")
    cfg_path = os.path.join(LOCALAPPDATA, "Atlas", "config.json")
    if not os.path.isdir(assets):
        print("Atlas: assets folder not found, skipping")
        return
    if os.path.exists(ICON_SRC):
        shutil.copy2(ICON_SRC, os.path.join(assets, "VRGallery.ico"))
        print("Atlas: icon copied into assets")

    if not os.path.exists(cfg_path):
        print("Atlas: no live config yet — the new default entry will seed itself")
        return
    if is_running("Atlas.exe"):
        print("Atlas: it is running right now — close it and re-run, or it will "
              "overwrite this edit on exit")
        return
    data = load_json(cfg_path)
    apps = data.get("apps")
    if not isinstance(apps, list):
        print("Atlas: unexpected config shape, not touching it")
        return
    if any(a.get("id") == "vrgallery" for a in apps):
        print("Atlas: already registered")
        return
    entry = {
        "id": "vrgallery", "name": "VR Gallery", "tag": "VRChat photo album",
        "icon": "VRGallery.ico", "accent": "#f472b6",
        "target": os.path.join(HERE, "dist", "VRGallery", "VRGallery.exe"),
        "args": "",
        "cwd": os.path.join(HERE, "dist", "VRGallery"),
        "folder": HERE,
        "config_dir": os.path.join(LOCALAPPDATA, "VR Gallery"),
        "match": [
            os.path.join(HERE, "dist", "VRGallery", "vrgallery.exe").lower(),
            os.path.join(LOCALAPPDATA, "Programs", "VRGallery", "vrgallery.exe").lower(),
        ],
    }
    # keep VoxelWorld last, the way the source list orders it
    idx = next((i for i, a in enumerate(apps) if a.get("id") == "voxelworld"), len(apps))
    apps.insert(idx, entry)
    bak = backup(cfg_path)
    write_json(cfg_path, data)
    print(f"Atlas: entry added ({len(apps)} apps). Backup: {os.path.basename(bak or '-')}")


# ---------------------------------------------------------------- Hexpad

KEY_SLOTS = ["key1", "key2", "key3", "key4", "key5", "key6"]


def render_key_icon(out_path):
    """A 144px PNG of the app mark for the dock key face."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    from vrgallery import icons
    app = QGuiApplication.instance() or QGuiApplication([])
    pm = icons.logo_pixmap(144, 1.0)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ok = pm.save(out_path, "PNG")
    del app
    return ok


def do_hexpad(api_url):
    cfg_path = os.path.join(APPDATA, "AjazzDock", "config.json")
    if not os.path.exists(cfg_path):
        print("Hexpad: no config found, skipping")
        return
    for exe in ("Hexpad.exe", "AjazzDock.exe"):
        if is_running(exe):
            print(f"Hexpad: {exe} is running right now — close it and re-run, or it "
                  "will overwrite this edit when it next saves")
            return
    data = load_json(cfg_path)
    profiles = data.get("profiles") or []
    if not profiles:
        print("Hexpad: no profiles, skipping")
        return

    # already there?
    def uses_our_url(node):
        return isinstance(node, dict) and "127.0.0.1" in str(node.get("url", "")) \
            and "/latest/" in str(node.get("url", ""))

    def all_pages(prof):
        """Profile pages first, then folder pages — folders are usually roomier."""
        for page in prof.get("pages") or []:
            yield page, page.get("name") or "page"
        for fid, folder in (prof.get("folders") or {}).items():
            for i, page in enumerate(folder.get("pages") or []):
                yield page, f"{folder.get('name') or fid} ▸ {i + 1}"

    for prof in profiles:
        for page, _label in all_pages(prof):
            for binding in (page.get("items") or {}).values():
                if uses_our_url((binding or {}).get("action")):
                    print("Hexpad: a VR Gallery key already exists")
                    return

    # find a free LCD key
    target = None
    for prof in profiles:
        for page, label in all_pages(prof):
            items = page.setdefault("items", {})
            for slot in KEY_SLOTS:
                b = items.get(slot)
                if b is None or (b.get("action", {}).get("type", "none") == "none"
                                 and not b.get("live") and not b.get("icon")):
                    target = (prof, label, items, slot)
                    break
            if target:
                break
        if target:
            break
    if not target:
        print("Hexpad: every key on every page is taken — add one by hand "
              f"with:\n  POST {api_url}")
        return

    prof, page_label, items, slot = target
    icon_path = os.path.join(APPDATA, "AjazzDock", "icons", "VR Gallery.png")
    icon_ok = False
    try:
        icon_ok = render_key_icon(icon_path)
    except Exception as e:
        print("Hexpad: icon render failed:", e.__class__.__name__)
    items[slot] = {
        "action": {"type": "http", "url": api_url, "method": "POST",
                   "body": "{}", "content_type": "application/json"},
        "color": "#000000",
        "label": "Share shot",
        "show_label": False,
        "fit": "cover",
        "icon": icon_path if icon_ok else "📸",
    }
    bak = backup(cfg_path)
    write_json(cfg_path, data)
    print(f"Hexpad: key added on profile {prof.get('name')!r} / {page_label} / {slot}. "
          f"Backup: {os.path.basename(bak or '-')}")
    print("        Restart Hexpad to pick up the new key.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", action="store_true")
    ap.add_argument("--hexpad", action="store_true")
    ap.add_argument("--url", default="", help="the VR Gallery API URL for the Hexpad key")
    a = ap.parse_args()
    both = not (a.atlas or a.hexpad)
    if a.atlas or both:
        do_atlas()
    if a.hexpad or both:
        url = a.url
        if not url:
            from vrgallery.config import Config
            cfg = Config()
            token = cfg.get("api_token") or ""
            port = cfg.get("api_port") or 8770
            if not token:
                print("Hexpad: no API token yet — start VR Gallery once, then re-run")
                return
            url = f"http://127.0.0.1:{port}/latest/discord?token={token}"
        do_hexpad(url)


if __name__ == "__main__":
    main()
