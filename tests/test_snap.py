"""Aero Snap on a window that draws its own frame.

Qt's FramelessWindowHint makes a WS_POPUP window, and Windows will not snap one
at all -- not by dragging it to an edge, not with Win+Left, not with the
snap-layout flyout. startSystemMove() was never enough: it hands the drag to the
compositor, but the compositor only offers to snap what the window STYLES say is
snappable. So the styles go back on and the frame they imply is cancelled again
in WM_NCCALCSIZE.

Most of that can only be seen on a real window, and the tests run offscreen.
What is checked here is the part that is pure logic -- and it is the part that
matters, because getting it wrong means a maximised window covering the taskbar.
Measured by hand on the real platform, at 100% scale on a 1920x1080 screen:

    normal      window 1200x800 at -1559,116   client 1200x800  (frameless)
    maximised   window 1936x1048 at -1928,-8   client 1920x1032 at -1920,0

that is, the window rect overhangs by the frame Windows insists on adding, and
the client -- everything you can actually see -- lands exactly on the work area.
"""
import ctypes
import os
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from ctypes import wintypes

from vrgallery import winutil


class _NCCALC(ctypes.Structure):
    """Only rgrc[0] matters here, and it is the first thing in the struct."""
    _fields_ = [("rgrc0", winutil._RECT), ("rgrc1", winutil._RECT),
                ("rgrc2", winutil._RECT), ("lppos", ctypes.c_void_p)]


def _send(filt, hwnd, message=winutil.WM_NCCALCSIZE, wparam=1, rect=(100, 100, 900, 700)):
    params = _NCCALC()
    params.rgrc0 = winutil._RECT(*rect)
    msg = winutil._MSG()
    msg.hwnd = wintypes.HWND(hwnd)
    msg.message = message
    msg.wParam = wparam
    msg.lParam = ctypes.addressof(params)
    handled, result = filt.nativeEventFilter(
        b"windows_generic_MSG", ctypes.addressof(msg))
    return handled, result, params.rgrc0


def test_a_normal_window_keeps_its_whole_rect_as_client(monkeypatch):
    """Which is what makes it look frameless while Windows thinks it has one."""
    monkeypatch.setattr(winutil, "_is_maximized", lambda _h: False)
    filt = winutil.SnapFilter()
    filt.watch(4242)
    handled, result, r = _send(filt, 4242)
    assert handled and result == 0, "the frame was not cancelled"
    assert (r.left, r.top, r.right, r.bottom) == (100, 100, 900, 700), \
        "a non-maximised window must keep the rect Windows proposed"


def test_a_maximised_window_is_inset_so_it_does_not_cover_the_taskbar(monkeypatch):
    """Windows sizes a maximised window to the work area PLUS its frame, and
    expects the frame to be cropped. Cancel the frame outright and the client
    spills over the taskbar."""
    monkeypatch.setattr(winutil, "_is_maximized", lambda _h: True)
    dx, dy = winutil._frame_thickness()
    assert dx > 0 and dy > 0, "no frame thickness to inset by"
    filt = winutil.SnapFilter()
    filt.watch(4242)
    handled, _result, r = _send(filt, 4242)
    assert handled
    assert (r.left, r.top, r.right, r.bottom) == (100 + dx, 100 + dy, 900 - dx, 700 - dy)


def test_other_windows_are_left_alone(monkeypatch):
    """The filter is installed on the whole application, so every top-level
    window's messages pass through it -- dialogs, the tray, Qt's own helpers."""
    monkeypatch.setattr(winutil, "_is_maximized", lambda _h: False)
    filt = winutil.SnapFilter()
    filt.watch(4242)
    handled, _result, r = _send(filt, 9999)
    assert not handled, "a window we never asked about was reframed"
    assert (r.left, r.top, r.right, r.bottom) == (100, 100, 900, 700)


def test_every_other_message_passes_straight_through(monkeypatch):
    monkeypatch.setattr(winutil, "_is_maximized", lambda _h: False)
    filt = winutil.SnapFilter()
    filt.watch(4242)
    for message in (0x0005, 0x000F, 0x0084, 0x0024):   # SIZE, PAINT, NCHITTEST, GETMINMAXINFO
        handled, _r, _rect = _send(filt, 4242, message=message)
        assert not handled, f"message 0x{message:04X} was swallowed"


def test_the_query_form_of_nccalcsize_is_not_touched(monkeypatch):
    """wParam FALSE means Windows is only asking, and lParam is a bare RECT."""
    monkeypatch.setattr(winutil, "_is_maximized", lambda _h: False)
    filt = winutil.SnapFilter()
    filt.watch(4242)
    handled, _r, _rect = _send(filt, 4242, wparam=0)
    assert not handled


def test_the_styles_windows_snaps_are_the_ones_asked_for():
    """Aero Snap is a property of a SIZEABLE window with a maximize box."""
    assert winutil.WS_THICKFRAME and winutil.WS_MAXIMIZEBOX
    import inspect
    body = inspect.getsource(winutil.snap_styles)
    for name in ("WS_THICKFRAME", "WS_MAXIMIZEBOX", "WS_MINIMIZEBOX", "SWP_FRAMECHANGED"):
        assert name in body, f"snap_styles no longer sets {name}"


# ------------------------------------------------- one running instance

def test_the_wake_up_message_id_is_the_same_in_every_process():
    """RegisterWindowMessage is how two copies of an app agree on a number
    without sharing anything. If it ever returned 0 the second copy would post
    into the void and the box would come back."""
    first = winutil.show_message_id()
    assert first, "no message id registered"
    assert winutil.show_message_id() == first, "the id is not stable"


def test_the_finder_never_returns_this_process():
    """It must not find US -- a copy that woke itself would be a hang.

    Asserting it finds NOTHING would be wrong: this machine has the real app
    installed, and the test then passes or fails depending on whether it happens
    to be running, which it was.
    """
    found = winutil.find_other_instance()
    assert found == 0 or found[1] != os.getpid(), "it found its own window"


def test_the_window_marker_is_a_property_not_a_title():
    """The app draws its own title bar and its window title is empty, so there
    is nothing else on the desktop to recognise it by."""
    import inspect
    body = inspect.getsource(winutil.find_other_instance)
    assert "GetPropW" in body and winutil.SINGLE_PROP
    assert "GetWindowThreadProcessId" in body, "it could match its own window"


def test_the_second_copy_hands_over_the_right_to_come_forward():
    """Windows refuses SetForegroundWindow to a process that is not already in
    front; without AllowSetForegroundWindow the window would only blink in the
    taskbar."""
    import inspect
    body = inspect.getsource(winutil.signal_existing_instance)
    assert "AllowSetForegroundWindow" in body
    assert "PostMessageW" in body, "it must ask, not reach into the other process"
