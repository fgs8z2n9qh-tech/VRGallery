"""Every page wears the same floating glass header, and nothing hides behind it.

The header used to exist on the Photos page alone; the rest carried a plain
inline title. These tests are what keeps the two from drifting apart again.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
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
        "path": str(tmp_path / "photos" / f"VRChat_2026-01-{d:02d}_10-00-00.000.png"),
        "folder": str(tmp_path / "photos"),
        "filename": f"VRChat_2026-01-{d:02d}_10-00-00.000.png",
        "taken_at": f"2026-01-{d:02d}T10:00:00", "day": f"2026-01-{d:02d}",
        "filesize": 1234, "mtime": float(d),
    } for d in range(1, 20)])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.resize(1200, 820)
    yield win
    win._quitting = True
    win.close()


# page key -> the attribute holding its header
HEADED = ["all", "favs", "memories", "moments", "albums", "sessions", "worlds",
          "people", "avatars", "stats", "cleanup", "settings"]


def _head(window, key):
    window.activate(key)
    page = window.stack.currentWidget()
    return page, getattr(page, "head", None) or getattr(page, "headwrap", None)


@pytest.mark.parametrize("key", HEADED)
def test_every_page_has_the_floating_header(window, key):
    page, head = _head(window, key)
    assert isinstance(head, widgets.PageHead), f"{key} has no glass header"
    assert head.parent() is page
    assert head._scroller is not None, f"{key}'s header floats over nothing"


@pytest.mark.parametrize("key", HEADED)
def test_the_header_hovers_flush_with_the_top_of_the_page(window, key):
    """Not in the layout, and no sliver of content peeking over it."""
    page, head = _head(window, key)
    app_ = QApplication.instance()
    app_.processEvents()
    head.place()
    assert head.geometry().top() == 0
    vp = head._scroller.viewport()
    right = vp.mapTo(page, QPoint(vp.width(), 0)).x()
    assert head.geometry().right() <= right, f"{key}'s header lies on the scrollbar"


@pytest.mark.parametrize("key", HEADED)
def test_the_page_leaves_room_for_its_own_header(window, key):
    """Whatever scrolls has to start below the glass, not behind it."""
    _page, head = _head(window, key)
    QApplication.instance().processEvents()
    assert head.reserved() >= head.bar.sizeHint().height()


def test_a_header_with_no_controls_does_not_collapse_to_nothing():
    """Sessions has a title and nothing else; fading it would leave a blank bar."""
    from PySide6.QtWidgets import QWidget
    page = QWidget()
    head = widgets.PageHead(page, "Sessions")
    head.measure()
    assert not head._can_collapse
    assert head._tight == head._open


def test_a_header_with_controls_collapses_to_clear_the_tallest_one():
    from PySide6.QtWidgets import QWidget
    page = QWidget()
    head = widgets.PageHead(page, "Moments")
    btn = head.add(widgets.ghost_btn("Rescan", "refresh"))
    head.measure()
    assert head._can_collapse
    assert head._tight < head._open
    assert head._tight >= btn.sizeHint().height(), "the control would be clipped"


# ------------------------------------------------------------------ scrolling

SCROLLERS = {"all": "view", "favs": "view", "memories": "scroll", "moments": "scroll",
             "albums": "view", "sessions": "scroll", "worlds": "view", "people": "view",
             "avatars": "view", "stats": "scroll", "cleanup": "view", "settings": "scroll"}


@pytest.mark.parametrize("key,attr", sorted(SCROLLERS.items()))
def test_every_scrolling_surface_glides(window, key, attr):
    """The wheel used to step on seven of the nine surfaces."""
    window.activate(key)
    page = window.stack.currentWidget()
    scroller = getattr(page, attr)
    filters_installed = [o for o in scroller.viewport().children()
                         if isinstance(o, widgets.SmoothScroll)]
    # the filter is parented to the view, not the viewport, so look there too
    if not filters_installed:
        filters_installed = [o for o in scroller.children()
                             if isinstance(o, widgets.SmoothScroll)]
    assert filters_installed, f"{key}: {attr} still steps"


def test_the_photo_grid_shows_one_scroll_affordance_not_two(window):
    """The timeline rail IS the scrollbar; a plain one beside it is clutter."""
    window.activate("all")
    page = window.page_grid
    QApplication.instance().processEvents()
    if page.rail.isVisible():
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    else:
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_the_rail_scale_starts_below_the_floating_header(window):
    """Its first year label used to sit up beside the window buttons."""
    window.activate("all")
    page = window.page_grid
    QApplication.instance().processEvents()
    page._refresh_rail()
    top, _bottom = page.rail._span()
    assert top >= page.head_height(), "the rail points at photos behind the glass"


def _wheel(widget):
    return QWheelEvent(QPointF(4, 4), widget.mapToGlobal(QPoint(4, 4)),
                       QPoint(0, -120), QPoint(0, -120), Qt.NoButton,
                       Qt.NoModifier, Qt.NoScrollPhase, False)


@pytest.mark.parametrize("factory", [widgets.ComboBox, widgets.SpinBox])
def test_a_control_you_scroll_past_does_not_change_itself(app, factory):
    """Flicking down a page over a combo box must not rewrite the setting."""
    w = factory()
    if isinstance(w, widgets.ComboBox):
        w.addItems(["one", "two", "three"])
    before = w.currentIndex() if isinstance(w, widgets.ComboBox) else w.value()
    ev = _wheel(w)
    w.wheelEvent(ev)
    after = w.currentIndex() if isinstance(w, widgets.ComboBox) else w.value()
    assert after == before
    assert not ev.isAccepted(), "the wheel was swallowed instead of passed on"
