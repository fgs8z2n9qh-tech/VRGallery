"""Config load/save (atomic JSON, never clobbers on failure)."""
import json
import os
import tempfile

from . import paths

DEFAULTS = {
    "version": 2,
    "folders": [],            # screenshot folders to index
    "self_names": [],         # own VRChat display names (learned from logs)
    "webhook_url": "",
    "slideshow_secs": 5,
    "jpeg_quality": 92,
    "accent": "vrblue",
    "thumb_px": 176,
    "sort_desc": True,
    "window": None,           # [x, y, w, h, maximized]
    # tray / autostart
    "close_to_tray": True,
    "start_minimized": False,
    "autostart": False,
    # sharing / export
    "copy_mode": "jpeg",      # 'jpeg' (downscaled) or 'original'
    "copy_max_px": 2560,
    "share_captioned": False,
    # local HTTP API (Hexpad keys, scripts)
    "api_enabled": True,
    "api_port": 8770,
    "api_token": "",
    # in-world picture frame
    "frame_dir": "",
    "frame_publish_cmd": "",
    "frame_captioned": False,
    "frame_max_px": 2048,
    # backup / import
    "backup_dir": "",
    "backup_verify_hash": False,
    "adb_path": "",
    "_tray_hint_shown": False,
}


class Config:
    def __init__(self):
        self._d = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        self._d[k] = data[k]
        except FileNotFoundError:
            pass
        except Exception:
            # corrupt config: keep defaults, keep the broken file aside for recovery
            try:
                bad = paths.CONFIG_PATH + ".broken"
                if not os.path.exists(bad):
                    os.replace(paths.CONFIG_PATH, bad)
            except Exception:
                pass
        if not self._d["folders"]:
            d = paths.default_vrchat_pictures()
            if os.path.isdir(d):
                self._d["folders"] = [d]

    def save(self):
        paths.ensure_dirs()
        try:
            fd, tmp = tempfile.mkstemp(dir=paths.APPDIR, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, paths.CONFIG_PATH)
        except Exception:
            pass

    def get(self, key):
        return self._d.get(key, DEFAULTS.get(key))

    def set(self, key, value, save=True):
        self._d[key] = value
        if save:
            self.save()

    # convenience
    @property
    def folders(self):
        return [f for f in self._d.get("folders", []) if f]

    @property
    def self_names(self):
        return set(self._d.get("self_names", []))

    def add_self_names(self, names):
        cur = list(self._d.get("self_names", []))
        changed = False
        for n in names:
            if n and n not in cur:
                cur.append(n)
                changed = True
        if changed:
            self._d["self_names"] = cur
            self.save()
