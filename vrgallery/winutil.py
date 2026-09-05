"""Windows helpers: recycle bin, dark titlebar, AppUserModelID, Explorer reveal."""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

FO_DELETE = 3
FOF_ALLOWUNDO = 0x40
FOF_NOCONFIRMATION = 0x10
FOF_SILENT = 0x4
FOF_NOERRORUI = 0x400
# FOF_ALLOWUNDO is best-effort: when the shell cannot put an item in a Recycle Bin
# (network share, most removable media, bin disabled or full) it deletes for good.
# FOF_WANTNUKEWARNING partially overrides FOF_NOCONFIRMATION and forces a prompt in
# exactly that case, which is the difference between "moved to the bin" and "gone".
FOF_WANTNUKEWARNING = 0x4000


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def recycle(paths_list):
    """Move files to the Recycle Bin.

    Returns (removed_paths, err_message_or_empty) — `removed_paths` is the subset
    that genuinely disappeared, verified afterwards, so callers never mark a file
    as gone when it is still sitting on disk.
    """
    files = [os.path.abspath(p) for p in paths_list if p and os.path.exists(p)]
    if not files:
        return [], ""
    buf = ctypes.create_unicode_buffer("\x00".join(files) + "\x00\x00")
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    # FOF_SILENT only hides the progress bar; it does not suppress the nuke warning.
    # FOF_NOERRORUI is deliberately NOT set, so a real failure explains itself.
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_WANTNUKEWARNING | FOF_SILENT
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    removed = [f for f in files if not os.path.exists(f)]
    if res != 0 or op.fAnyOperationsAborted:
        if len(removed) == len(files):
            return removed, ""          # user-visible dialog, but it all went through
        return removed, ("cancelled" if op.fAnyOperationsAborted
                         else f"SHFileOperation error ({res})")
    return removed, ""


# Restoring from the Recycle Bin is only possible through a shell verb, and the
# verb's name is localized. There is no pywin32 or comtypes here (the app is
# deliberately dependency-light), so the shell is driven through PowerShell,
# which is always present on Windows.
_RESTORE_PS = r"""
param([string]$ListFile)
$ErrorActionPreference = 'SilentlyContinue'
$names = @('undelete','restore','visszaallitas','visszaállítás','wiederherstellen',
           'restaurer','ripristina','restaurar','herstellen','przywroc','przywróć',
           'obnovit','aterstall','återställ','gendan','palauta','geri yukle','geri yükle')
$targets = @{}
foreach ($line in [System.IO.File]::ReadAllLines($ListFile, [System.Text.Encoding]::UTF8)) {
  if ($line) { $targets[$line.ToLowerInvariant()] = $true }
}
$shell = New-Object -ComObject Shell.Application
$bin = $shell.Namespace(10)
if ($bin -eq $null) { exit 0 }
foreach ($item in @($bin.Items())) {
  $folder = $bin.GetDetailsOf($item, 1)
  if (-not $folder) { continue }
  $full = Join-Path $folder $item.Name
  if (-not $targets.ContainsKey($full.ToLowerInvariant())) { continue }
  $done = $false
  foreach ($v in @($item.Verbs())) {
    $n = ($v.Name -replace '&','').Trim().ToLowerInvariant()
    if ($names -contains $n) { $v.DoIt(); $done = $true; break }
  }
  if (-not $done) { $item.InvokeVerb('undelete') }
}
"""


def restore_from_recycle_bin(paths_list):
    """Put files back where they came from. -> (restored_paths, still_missing).

    Nothing is deleted and nothing is overwritten. Whether a file came back is
    decided by looking at the disk afterwards, never by the shell's word for it.
    """
    wanted = [p for p in paths_list if p]
    already = [p for p in wanted if os.path.exists(p)]
    todo = [p for p in wanted if not os.path.exists(p)]
    if not todo:
        return already, []

    import subprocess
    import tempfile
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.exists(ps):
        return already, todo

    tmpdir = tempfile.mkdtemp(prefix="vrgallery-restore-")
    list_path = os.path.join(tmpdir, "targets.txt")
    script_path = os.path.join(tmpdir, "restore.ps1")
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            f.write(chr(10).join(os.path.abspath(p) for p in todo))
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_RESTORE_PS)
        subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", script_path, "-ListFile", list_path],
                       capture_output=True, timeout=90,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    finally:
        for f in (list_path, script_path):
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    restored = already + [p for p in todo if os.path.exists(p)]
    return restored, [p for p in todo if not os.path.exists(p)]


def open_recycle_bin():
    """Last resort when the shell will not restore: let them do it by hand."""
    try:
        os.startfile("shell:RecycleBinFolder")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- Aero Snap

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WM_NCCALCSIZE = 0x0083
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92
MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


def snap_styles(hwnd):
    """Give a frameless window the styles Windows snaps, and keep it frameless.

    Qt's FramelessWindowHint produces a WS_POPUP window, and Windows will not
    snap one: not by dragging it to an edge, not with Win+Left, not with the
    snap-layout flyout. Aero Snap is a property of a SIZEABLE window with a
    maximize box, so the window has to have WS_THICKFRAME and WS_MAXIMIZEBOX --
    and then the frame those imply has to be taken back off in WM_NCCALCSIZE,
    or Windows draws its own title bar and border over the app's.

    startSystemMove() was never enough on its own. It hands the drag to the
    compositor, which is what makes the drag smooth, but the compositor only
    offers to snap what the window styles say is snappable.
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
        want = style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_CAPTION
        if want != style:
            user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, want)
            user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
                                | SWP_NOZORDER | SWP_NOACTIVATE)
        return True
    except Exception:
        return False


def _frame_thickness():
    try:
        g = ctypes.windll.user32.GetSystemMetrics
        return (g(SM_CXSIZEFRAME) + g(SM_CXPADDEDBORDER),
                g(SM_CYSIZEFRAME) + g(SM_CXPADDEDBORDER))
    except Exception:
        return 8, 8


def _is_maximized(hwnd):
    try:
        return bool(ctypes.windll.user32.IsZoomed(wintypes.HWND(hwnd)))
    except Exception:
        return False


class SnapFilter:
    """Cancels the non-client frame that `snap_styles` had to add.

    Only WM_NCCALCSIZE is touched, and only to say "the client area is the whole
    window" -- which is what keeps the app looking frameless while Windows
    treats it as an ordinary sizeable window for snapping.

    The one exception is a MAXIMISED window. Windows sizes a maximised window to
    the work area PLUS its frame, expecting the frame to be cropped off; with
    the frame cancelled outright, the client would spill over the taskbar. So
    while maximised the frame is inset by hand instead.
    """

    def __init__(self, hwnds=None):
        self._hwnds = hwnds if hwnds is not None else set()

    def watch(self, hwnd):
        self._hwnds.add(int(hwnd))

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = _MSG.from_address(int(message))
            if msg.message != WM_NCCALCSIZE or not msg.wParam:
                return False, 0
            if int(msg.hwnd) not in self._hwnds:
                return False, 0
            if _is_maximized(int(msg.hwnd)):
                dx, dy = _frame_thickness()
                r = _RECT.from_address(msg.lParam)
                r.left += dx
                r.top += dy
                r.right -= dx
                r.bottom -= dy
            return True, 0            # client area == window rect
        except Exception:
            return False, 0


# ------------------------------------------------- the one running instance

SINGLE_PROP = "VRGalleryMainWindow"
SW_SHOW = 5
SW_RESTORE = 9
ASFW_ANY = -1
_show_msg = None
_enum_cb = None          # EnumWindows keeps no reference; losing it crashes


def show_message_id():
    """A window message id both instances agree on, without sharing anything.

    RegisterWindowMessage returns the same number for the same string in every
    process on the desktop, which is exactly what two copies of one app need to
    say one thing to each other.
    """
    global _show_msg
    if _show_msg is None and os.name == "nt":
        _show_msg = ctypes.windll.user32.RegisterWindowMessageW("VRGalleryShowWindow")
    return _show_msg or 0


def mark_main_window(hwnd):
    """Tag the window so a second instance can pick it out of every window on
    the desktop. The app's own title is empty -- it draws its own title bar --
    so there is nothing else to recognise it by."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetPropW(wintypes.HWND(hwnd), SINGLE_PROP,
                                      wintypes.HANDLE(1))
    except Exception:
        pass


def find_other_instance():
    """The main window of another copy of this app, or 0."""
    global _enum_cb
    if os.name != "nt":
        return 0
    found = []
    me = os.getpid()
    user32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != me and user32.GetPropW(hwnd, SINGLE_PROP):
            found.append((int(hwnd), pid.value))
            return False
        return True

    _enum_cb = proto(_cb)
    try:
        user32.EnumWindows(_enum_cb, 0)
    except Exception:
        return 0
    return found[0] if found else 0


def signal_existing_instance():
    """Ask the copy that is already running to come to the front. -> True if asked.

    Telling it rather than doing it: the running instance may be hidden in the
    tray, and ShowWindow from outside would put its native window back on screen
    while Qt still believed it was hidden. It handles the message itself and
    goes through the same path the tray icon uses.
    """
    other = find_other_instance()
    if not other:
        return False
    hwnd, pid = other
    user32 = ctypes.windll.user32
    try:
        # Windows refuses SetForegroundWindow to a process that is not already
        # in front. THIS process is -- it was just launched -- so it can hand
        # that right over to the one that will actually raise the window.
        user32.AllowSetForegroundWindow(wintypes.DWORD(pid))
    except Exception:
        pass
    try:
        return bool(user32.PostMessageW(wintypes.HWND(hwnd),
                                        wintypes.UINT(show_message_id()), 0, 0))
    except Exception:
        return False


def dark_titlebar(hwnd):
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def round_corners(hwnd, on=True):
    """Ask DWM for rounded corners and a shadow.

    A frameless window loses both by default; this puts them back, so a custom
    title bar does not cost the window its Windows 11 shape.
    """
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        val = ctypes.c_int(2 if on else 1)      # 2 = round, 1 = do not round
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def set_app_id(app_id="VRGallery.Desktop"):
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_autostart(name):
    """-> the stored command line, or '' when autostart is off."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return ""


def set_autostart(name, command):
    """command='' removes the entry. HKCU only — never needs admin."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if command:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def autostart_command(extra_args=""):
    """(executable, arguments) that will relaunch this app, frozen or from source."""
    if getattr(sys, "frozen", False):
        return sys.executable, extra_args
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "run.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return exe, f'"{script}" {extra_args}'.strip()


SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def set_wallpaper(image_path):
    """Point Windows at an image file. Needs a real path, not a URL."""
    if not os.path.exists(image_path):
        return False
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, os.path.abspath(image_path),
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
        return bool(ok)
    except Exception:
        return False


def open_url(url):
    """Open an http(s) URL in the default browser, nothing else."""
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return False
    import webbrowser
    webbrowser.open(url)
    return True


def _explorer_exe():
    """Full path, so PATH cannot decide which 'explorer' we launch."""
    win = os.environ.get("SystemRoot") or r"C:\Windows"
    exe = os.path.join(win, "explorer.exe")
    return exe if os.path.exists(exe) else "explorer.exe"


def reveal_in_explorer(path):
    if os.path.exists(path):
        subprocess.Popen([_explorer_exe(), "/select,", os.path.normpath(path)])
    else:
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            os.startfile(folder)


def open_file(path):
    try:
        os.startfile(path)
    except OSError:
        pass
