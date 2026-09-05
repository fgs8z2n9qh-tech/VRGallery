"""Dragging a window edge, one resize per compositor frame.

Measured on the real window at 180 Hz, a resize frame cost 32.5 ms -- the
content lagging six frames behind the edge in your hand, which is what reads as
flicker. Nearly all of it was work being redone at the frame rate that only has
one right answer per drag: re-wrapping two thousand rows, rebuilding the month
rail, refitting the header three times over, and rebuilding the glass out of a
blur every single frame, because every part of its cache is keyed on the size.

It is 11.3 ms now. These hold the four pieces of that in place.
"""
import os
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QListView, QWidget

from vrgallery import paths, widgets
from vrgallery.gridmodel import KIND_PHOTO


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(app, tmp_path):
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
        "path": str(tmp_path / "photos" / f"VRChat_2026-02-0{1 + d // 12}"
                    f"_10-{d:02d}-00.000.png"),
        "folder": str(tmp_path / "photos"),
        "filename": f"VRChat_2026-02-0{1 + d // 12}_10-{d:02d}-00.000.png",
        "taken_at": f"2026-02-0{1 + d // 12}T10:{d:02d}:00",
        "day": f"2026-02-0{1 + d // 12}",
        "filesize": 10, "mtime": float(d),
    } for d in range(36)])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    win.activate("all")
    for _ in range(60):
        app.processEvents()
    yield win.page_grid
    win._quitting = True
    win.close()


def _settle(app, secs=0.4):
    """Let the debounced timers fire."""
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        app.processEvents()


def _per_row(page):
    """How many photo tiles the fullest row holds."""
    rows = {}
    for r in range(page.model.rowCount()):
        kind, _payload = page.model.row_at(r)
        if kind != KIND_PHOTO:
            continue
        y = page.view.visualRect(page.model.index(r, 0)).y()
        rows[y] = rows.get(y, 0) + 1
    return max(rows.values()) if rows else 0


# ------------------------------------------------------ the grid's re-wrap

def test_the_grid_rewraps_once_the_drag_stops(page, app):
    """The whole point of not re-wrapping during the drag is that it happens
    after it. Without this the grid would simply be broken: it would keep the
    column count it had when the window opened, for ever."""
    _settle(app)
    wide = _per_row(page)
    assert wide >= 3, f"nothing to lose: only {wide} tiles per row to start with"

    page.window().resize(760, 900)
    _settle(app)
    narrow = _per_row(page)
    assert narrow < wide, (
        f"the grid never re-wrapped: {narrow} tiles per row in a 760 px window, "
        f"the same as in a 1400 px one")

    page.window().resize(1400, 900)
    _settle(app)
    assert _per_row(page) == wide, "it did not come back when the room did"


def test_the_grid_holds_its_wrap_while_the_edge_is_still_moving(page, app):
    """Re-wrapping is two thousand size hints out to Python and back, and it
    has to finish before the view can paint. At one per compositor frame the
    window falls six frames behind the edge you are dragging."""
    _settle(app)
    page.window().resize(1380, 900)          # the first one is not a drag yet
    app.processEvents()
    before = _per_row(page)
    for w in range(1340, 700, -40):          # a drag, with no gaps in it
        page.window().resize(w, 900)
        app.processEvents()
    assert _per_row(page) == before, (
        "the grid re-wrapped mid-drag; that is the 27 ms a frame this is about")
    _settle(app)
    assert _per_row(page) < before, "and then it never caught up"


def test_one_resize_on_its_own_rewraps_without_waiting(page, app):
    """Maximising, or snapping the window to half the screen, is a single
    resize with nothing following it. Making that wait out the drag debounce
    would leave the grid visibly wrong for a tenth of a second."""
    _settle(app)
    wide = _per_row(page)
    page.window().resize(700, 900)
    for _ in range(8):                       # a few event-loop turns, no waiting
        app.processEvents()
    assert _per_row(page) < wide, (
        "a lone resize sat on the old wrap instead of re-flowing straight away")


def test_the_view_is_not_left_re_wrapping_itself(page):
    """Qt's Adjust mode posts a relayout from its own resizeEvent and every
    paint flushes it, so Qt's own tenth-of-a-second wait never expires."""
    assert page.view.resizeMode() == QListView.Fixed


def test_maximising_and_restoring_still_re_wrap(page, app):
    """A width change does not only arrive from a drag. Fixed mode re-wraps
    nothing it is not told to, so every other route in has to be walked."""
    _settle(app)
    win = page.window()
    windowed_w = page.view.viewport().width()
    windowed = _per_row(page)
    win.showMaximized()
    _settle(app)
    wide_w = page.view.viewport().width()
    if wide_w == windowed_w:
        pytest.skip("this screen maximises to the width the window already had")
    # Which way it goes depends on the screen -- offscreen, "maximised" is
    # NARROWER than the window the fixture asks for. What has to hold is that
    # the wrap followed the width at all.
    assert (_per_row(page) > windowed) == (wide_w > windowed_w), (
        f"{_per_row(page)} tiles per row in a {wide_w} px viewport, against "
        f"{windowed} in a {windowed_w} px one")
    win.showNormal()
    _settle(app)
    assert _per_row(page) == windowed, "restoring kept the maximised wrap"


def test_going_to_the_tray_and_back_does_not_lose_the_wrap(page, app):
    """Hiding and showing takes the window through its own resize path."""
    _settle(app)
    before = _per_row(page)
    win = page.window()
    win.hide()
    app.processEvents()
    win.show_from_tray()
    _settle(app)
    assert _per_row(page) == before, (
        f"{_per_row(page)} tiles per row after coming back from the tray, "
        f"where there were {before}")


# ---------------------------------------------------------------- the rail

def test_the_month_rail_is_rebuilt_once_a_drag_ends_not_once_a_frame(page, app):
    """Every mark costs a visualRect that walks the whole laid-out grid, and
    three years of photos is three dozen marks."""
    _settle(app)
    calls = []
    real = page.rail_marks
    page.rail_marks = lambda: (calls.append(1), real())[1]
    for w in range(1400, 900, -25):
        page.window().resize(w, 900)
        app.processEvents()
    assert not calls, f"the rail was rebuilt {len(calls)} times during one drag"
    _settle(app)
    assert calls, "and then it was never rebuilt at all"


def test_the_rail_repaints_the_pip_and_not_the_whole_scale(page, app):
    """It is a 900 px strip carrying a picture that does not change; what moves
    is eleven pixels of it."""
    _settle(app)
    rail = page.rail
    rail.set_marks([(0, "2026-01"), (500, "2026-02"), (1000, "2026-03")], 4000)
    painted = []
    rail.update = lambda *a: painted.append(a)
    rail.set_pos(0)
    painted.clear()
    rail.set_pos(1)                       # far too small to move the pip
    assert painted == [], "a repaint for a pip that did not move"
    rail.set_pos(150)                     # about a wheel notch
    assert len(painted) == 1 and painted[0], "the pip moved and nothing repainted"
    rect = painted[0][0]
    assert rect.width() < rail.width(), "it repainted the full width"
    assert rect.height() < 60, (
        f"it repainted {rect.height()} px of a {rail.height()} px rail to move "
        f"a pip by a notch")


# -------------------------------------------------------------- the header

def test_the_header_is_refitted_once_for_the_three_calls_a_resize_makes(page, app):
    """The viewport's own event filter, the viewport_resized it emits, and the
    page's resizeEvent -- all three land on place()."""
    _settle(app)
    head = page.headwrap
    fits = []
    real = head.fit
    head.fit = lambda: (fits.append(1), real())[1]
    head.place()
    head.place()
    head.place()
    assert len(fits) <= 1, f"fit() ran {len(fits)} times for one placement"

    page.window().resize(1100, 900)
    app.processEvents()
    assert fits, "a real width change did not refit the header"


def test_a_pinned_control_still_survives_a_placement(page, app):
    """place() skips the refit when nothing it depends on moved, and what it
    depends on includes which controls are switched on: a pinned one outranks
    the rest when there is not room for all of them."""
    _settle(app)
    win = page.window()
    win.activate("cleanup")                # where the switchable pills live
    app.processEvents()
    cleanup = win.stack.currentWidget()
    head = getattr(cleanup, "headwrap", None) or cleanup.head
    pinnable = [w for _prio, w in head._optional
                if getattr(w, "isCheckable", None) and w.isCheckable()]
    assert pinnable, "no control in this header can be switched on at all"
    head.place()                           # so the key is settled
    seen = []
    real = head.fit
    head.fit = lambda: (seen.append(1), real())[1]
    # Switched on with its signals blocked, so that the ONLY thing that has
    # changed is the thing the key is supposed to be watching. On, not off:
    # these pills are an exclusive group and refuse to be the one that leaves
    # nothing switched on.
    off = [w for w in pinnable if not w.isChecked()]
    assert off, "every pill was already on; nothing to switch"
    off[0].blockSignals(True)
    off[0].setChecked(True)
    off[0].blockSignals(False)
    head.place()
    assert seen, "switching on a control that outranks the others was ignored"


# --------------------------------------------------------------- the glass

def test_the_glass_is_not_rebuilt_on_every_frame_of_a_drag(page, app):
    """Every part of its cache is keyed on the size, so a resize per frame
    missed all of it and paid 2.7 ms of blur, vibrance and refraction each
    time: 4.9 of the 14.7 ms a resize frame cost."""
    _settle(app)
    bar = page.headwrap.bar
    builds = []
    real = widgets.Glass.surface

    def counted(widget, source, *a, **kw):
        before = getattr(widget, "_glass_surface", None)
        out = real(widget, source, *a, **kw)
        if widget is bar and getattr(widget, "_glass_surface", None) is not before:
            builds.append(1)
        return out

    widgets.Glass.surface = staticmethod(counted)
    try:
        bar.repaint()                     # one, so that there is a cache at all
        builds.clear()
        frames = 0
        t0 = time.perf_counter()
        for w in range(1400, 1100, -6):
            page.window().resize(w, 900)
            bar.repaint()
            frames += 1
        elapsed = time.perf_counter() - t0
        # The rate a rebuild is allowed to happen at is the one it happens at
        # while the page scrolls underneath: TTL apart, and no faster, however
        # many frames arrive in between. Without that it is one per frame.
        allowed = int(elapsed / widgets.Glass.TTL) + 2
        assert frames > allowed, (
            f"{frames} frames in {elapsed * 1000:.0f} ms is not fast enough to "
            f"prove anything: the TTL allows {allowed} rebuilds anyway")
        assert len(builds) <= allowed, (
            f"{len(builds)} rebuilds in {elapsed * 1000:.0f} ms of dragging, "
            f"where the TTL allows {allowed}")
    finally:
        widgets.Glass.surface = staticmethod(real)


def test_a_stretched_glass_still_covers_the_whole_bar(page, app):
    """The frames between two rebuilds paint the last surface scaled up. Drawn
    at its own size instead -- which is what drawPixmap(0, 0, pm) does -- a bar
    that has just been widened has a bare strip down its right-hand side."""
    page.window().resize(1000, 900)
    _settle(app)
    bar = page.headwrap.bar
    ttl = widgets.Glass.TTL
    widgets.Glass.TTL = 30.0              # so it is certainly still stretching
    try:                                  # when the paint below actually runs
        bar._glass_surface = None         # and the next paint really builds one
        bar.repaint()
        cached = getattr(bar, "_glass_surface", None)
        assert cached is not None, "no surface to stretch"

        page.window().resize(1400, 900)   # wider: the surface no longer reaches
        app.processEvents()
        stale = bar._stretch_instead()
        assert stale is not None, "it rebuilt instead of stretching"
        assert stale.width() < bar.width(), "this is not the case being tested"

        pm = QPixmap(bar.size())
        pm.fill(Qt.transparent)
        # Without DrawWindowBackground: render() paints the palette brush over
        # the whole widget by default, which would fill the bare strip in and
        # hide the very thing being looked for.
        bar.render(pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        img = pm.toImage()
        # Above the controls, inside the rounded end: glass and nothing else.
        near = img.pixelColor(14, 4)
        far = img.pixelColor(bar.width() - 14, 4)
        assert near.alpha() > 0, "the bar did not paint at all"
        assert far.alpha() > 0, (
            f"a bare strip {bar.width() - stale.width()} px wide down the right "
            f"of the bar: the stale surface was drawn at its own size")
    finally:
        widgets.Glass.TTL = ttl
        bar._glass_surface = None


def test_the_glass_waits_out_its_own_ttl_rather_than_repainting_for_nothing(page, app):
    """Painting the bar repaints every control in it, and a scroll on a 180 Hz
    display says the backdrop moved six times per rebuild. 91% of the header's
    paints were redrawing the identical pixmap."""
    _settle(app)
    bar = page.headwrap.bar
    bar._glass_surface = None
    bar.repaint()                          # a surface built just now, so it is
    updates = []                           # inside its own TTL from here
    real = bar.update
    bar.update = lambda *a: updates.append(a)
    try:
        for v in range(1, 12):
            bar.set_glass_stamp(v)
        assert updates == [], (
            f"{len(updates)} repaints for a surface that cannot have changed yet")
        assert bar._due.isActive(), "and nothing will ever repaint it either"
    finally:
        bar.update = real
