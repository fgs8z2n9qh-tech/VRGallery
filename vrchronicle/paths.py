"""Branding constants, central paths, and crash logging."""
import os
import sys
import faulthandler

APP_NAME = "VRChronicle"
APP_TAGLINE = "VRChat photo album"
APP_ID = "VRChronicle.Desktop"      # AppUserModelID: taskbar grouping identity
APP_VERSION = "1.4.0"
_LEGACY_NAMES = ("Aperture",)     # data dirs from before the rename

APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
THUMB_DIR = os.path.join(APPDIR, "thumbs")
DB_PATH = os.path.join(APPDIR, "vrchronicle.db")
CONFIG_PATH = os.path.join(APPDIR, "config.json")
CRASH_LOG = os.path.join(APPDIR, "crash.log")
LOCK_PATH = os.path.join(APPDIR, "vrchronicle.lock")
EXPORT_DIR = os.path.join(APPDIR, "exports")

_crash_fh = None


def set_appdir(directory):
    """Point the whole app at a different data folder.

    Must be called before anything opens the database. Used by --data-dir, which
    exists so a throwaway copy of a library can be run side by side with the real
    one (documentation screenshots, testing) without touching it.
    """
    global APPDIR, THUMB_DIR, DB_PATH, CONFIG_PATH, CRASH_LOG, LOCK_PATH, EXPORT_DIR
    APPDIR = os.path.abspath(directory)
    THUMB_DIR = os.path.join(APPDIR, "thumbs")
    DB_PATH = os.path.join(APPDIR, "vrchronicle.db")
    CONFIG_PATH = os.path.join(APPDIR, "config.json")
    CRASH_LOG = os.path.join(APPDIR, "crash.log")
    LOCK_PATH = os.path.join(APPDIR, "vrchronicle.lock")
    EXPORT_DIR = os.path.join(APPDIR, "exports")


def is_default_appdir():
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.normcase(APPDIR) == os.path.normcase(os.path.join(base, APP_NAME))


def migrate_legacy_appdir():
    """Adopt the data folder from a previous name (Aperture -> VRChronicle).

    Only ever moves when the new folder does not exist yet, so a real
    VRChronicle library is never touched. Best-effort: on failure we simply
    start with an empty library and reindex.
    """
    if os.path.isdir(APPDIR) or not is_default_appdir():
        return False
    base = os.path.dirname(APPDIR)
    for old_name in _LEGACY_NAMES:
        old = os.path.join(base, old_name)
        if not os.path.isdir(old):
            continue
        try:
            os.rename(old, APPDIR)
        except OSError:
            return False
        # the database file carried the old product name too
        for legacy_db in ("aperture.db", "aperture.db-wal", "aperture.db-shm"):
            src = os.path.join(APPDIR, legacy_db)
            if os.path.exists(src):
                dst = os.path.join(APPDIR, legacy_db.replace("aperture.db", "vrchronicle.db"))
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        return True
    return False


def ensure_dirs():
    migrate_legacy_appdir()
    os.makedirs(APPDIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)


def enable_crash_log():
    global _crash_fh
    try:
        ensure_dirs()
        _crash_fh = open(CRASH_LOG, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_crash_fh)
    except Exception:
        pass


def pretty(path):
    """A path fit to show on screen: the home directory as %USERPROFILE%.

    Shorter to read, and it keeps the account name out of screenshots and
    support pastes.
    """
    if not path:
        return ""
    home = os.path.normpath(os.path.expanduser("~"))
    p = os.path.normpath(str(path))
    if os.path.normcase(p) == os.path.normcase(home):
        return "%USERPROFILE%"
    # match on a path boundary: C:\Users\Erikson is not inside C:\Users\Erik
    prefix = home if home.endswith(os.sep) else home + os.sep
    if os.path.normcase(p).startswith(os.path.normcase(prefix)):
        return "%USERPROFILE%" + os.sep + p[len(prefix):]
    return p


def app_root():
    """Project root (where assets/ lives), both for source and frozen runs."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset(*parts):
    return os.path.join(app_root(), "assets", *parts)


def default_vrchat_pictures():
    """Best guess for the VRChat screenshot folder."""
    cands = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            pics = winreg.QueryValueEx(k, "My Pictures")[0]
            pics = os.path.expandvars(pics)
            cands.append(os.path.join(pics, "VRChat"))
    except Exception:
        pass
    home = os.path.expanduser("~")
    cands.append(os.path.join(home, "Pictures", "VRChat"))
    one = os.environ.get("OneDrive")
    if one:
        cands.append(os.path.join(one, "Pictures", "VRChat"))
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0] if cands else os.path.join(home, "Pictures", "VRChat")


def vrchat_log_dir():
    home = os.path.expanduser("~")
    return os.path.join(home, "AppData", "LocalLow", "VRChat", "VRChat")
