"""The app in a window narrow enough to sit beside something else.

The point of all of this is being able to snap VR Gallery to half a screen and
keep a video on the other half. On a 1920-wide display that is a 960 px window,
and the app used to refuse to go below 1080 -- so half-screen was not merely
awkward, it was impossible. These tests hold that open.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from vrgallery import paths, widgets


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, tmp_path):
    paths.set_appdir(str(tmp_path / "lib"))
    paths.ensure_dirs()
    from vrgallery.config import Config
    from vrgallery.db import Database
    from vrgallery.mainwindow import MainWindow

    cfg = Config()
    cfg.set("onboarded", True, save=False)
    cfg.set("check_updates", False, save=False)
    cfg.set("api_enabled", False, save=False)
    db = Database()
    db.upsert_photos([{
        "path": str(tmp_path / "photos" / f"VRChat_2026-02-{d:02d}_10-00-00.000.png"),
        "folder": str(tmp_path / "photos"),
        "filename": f"VRChat_2026-02-{d:02d}_10-00-00.000.png",
        "taken_at": f"2026-02-{d:02d}T10:00:00", "day": f"2026-02-{d:02d}",
        "filesize": 10, "mtime": float(d),
    } for d in range(1, 16)])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.show()
    app.processEvents()
    yield win
    win._quitting = True
    win.close()


# a 1920 screen, halved and quartered -- the sizes this has to survive
HALF = (960, 1032)
QUARTER = (960, 516)


def test_the_window_can_be_made_half_a_screen_wide(window, app):
    """It could not: the minimum was 1080 wide and 660 tall."""
    mn = window.minimumSize()
    assert mn.width() <= HALF[0], f"cannot be snapped to half a 1920 screen ({mn.width()})"
    assert mn.height() <= QUARTER[1], f"cannot be snapped to a quarter ({mn.height()})"

    window.resize(*QUARTER)
    app.processEvents()
    assert window.width() == QUARTER[0] and window.height() == QUARTER[1]


def _head(win, key):
    win.activate(key)
    page = win.stack.currentWidget()
    QApplication.instance().processEvents()
    return page, getattr(page, "head", None) or getattr(page, "headwrap", None)


HEADED = ["all", "favs", "memories", "moments", "albums", "sessions", "worlds",
          "people", "avatars", "stats", "cleanup", "settings"]


@pytest.mark.parametrize("key", HEADED)
def test_no_header_overflows_its_bar_when_the_window_is_halved(window, app, key):
    """The controls used to keep their full width and simply lie on top of each
    other: blank rounded squares where the pills were, the search box across
    the sort box."""
    window.resize(*HALF)
    app.processEvents()
    page, head = _head(window, key)
    head.place()
    app.processEvents()
    assert head._row_width() <= head.width(), (
        f"{key}: the header needs {head._row_width()} px in a {head.width()} px bar")


@pytest.mark.parametrize("key", HEADED)
def test_no_header_overflows_at_the_smallest_the_window_goes(window, app, key):
    window.resize(window.minimumWidth(), window.minimumHeight())
    app.processEvents()
    page, head = _head(window, key)
    head.place()
    app.processEvents()
    assert head._row_width() <= head.width(), (
        f"{key}: the header needs {head._row_width()} px in a {head.width()} px bar")


def test_what_gets_dropped_comes_back_when_there_is_room(window, app):
    window.activate("all")
    page = window.page_grid
    head = page.headwrap

    window.resize(window.minimumWidth(), 700)
    app.processEvents()
    head.place()
    assert head._dropped, "nothing gave way in the narrowest window there is"
    assert page.search.isVisible(), "the search box must never be the thing that goes"

    window.resize(1600, 900)
    app.processEvents()
    head.place()
    assert not head._dropped, "the controls did not come back when there was room"


def test_the_size_slider_goes_before_the_level_pills(window, app):
    """Drop order is a judgement about what a person can do without: Ctrl+wheel
    resizes the thumbnails, but nothing else browses by year."""
    window.activate("all")
    head = window.page_grid.headwrap
    order = {id(w): prio for prio, w in head._optional}
    assert order[id(window.page_grid.slider)] < order[id(window.page_grid.levels)]
    assert order[id(window.page_grid.sort_box)] < order[id(window.page_grid.levels)]


def test_a_control_the_page_does_not_want_is_not_brought_back_by_a_wide_window(window, app):
    """The two reasons a control can be off screen are different, and when both
    of them wrote to setVisible() they overwrote each other."""
    window.resize(1600, 900)
    app.processEvents()
    page = window.page_grid
    head = page.headwrap
    head.allow(page.levels, False)
    head.place()
    app.processEvents()
    assert not head.allows(page.levels)
    assert page.levels.isHidden(), "a denied control came back because there was room"
    head.allow(page.levels, True)
    head.place()
    assert page.levels.isVisible()
