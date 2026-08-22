"""Every page must build and refresh against a library, headless.

A shadowed import or a missing column only shows up when a page is actually
constructed, and that used to mean noticing it in a screenshot.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from PySide6.QtCore import QPoint

from vrchronicle import paths
from vrchronicle.gridmodel import KIND_PHOTO as KIND_PHOTO_KIND


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, tmp_path, monkeypatch):
    paths.set_appdir(str(tmp_path / "lib"))
    paths.ensure_dirs()
    from vrchronicle.config import Config
    from vrchronicle.db import Database
    from vrchronicle.mainwindow import MainWindow

    cfg = Config()
    cfg.set("onboarded", True, save=False)
    cfg.set("check_updates", False, save=False)
    cfg.set("api_enabled", False, save=False)
    cfg.set("folders", [str(tmp_path / "photos")], save=False)
    db = Database()
    db.upsert_photos([{
        "path": str(tmp_path / "photos" / "VRChat_2026-01-02_10-00-00.000.png"),
        "folder": str(tmp_path / "photos"),
        "filename": "VRChat_2026-01-02_10-00-00.000.png",
        "taken_at": "2026-01-02T10:00:00", "day": "2026-01-02",
        "filesize": 1234, "mtime": 1.0,
    }])
    win = MainWindow(app, cfg, db, auto_index=False)
    yield win
    win._quitting = True
    win.close()


PAGES = ["all", "favs", "memories", "moments", "albums", "sessions", "worlds",
         "people", "avatars", "stats", "cleanup", "settings"]


@pytest.mark.parametrize("key", PAGES)
def test_every_page_builds_and_refreshes(window, key):
    window.activate(key)
    assert window.stack.currentWidget() is not None


def test_person_profile_opens_for_an_unknown_name(window):
    window.show_person("Nobody At All")
    assert window.page_person.name == "Nobody At All"


def test_cleanup_modes_all_render(window):
    for mode in ("black", "burst", "dupes", "large", "deleted"):
        window.page_cleanup.mode = mode
        window.page_cleanup.refresh()


def test_the_new_album_card_is_clickable_when_there_are_no_albums(window):
    """The empty-state overlay used to cover the one card there was to click."""
    window.activate("albums")
    page = window.page_albums
    assert page.main.db.albums() == []          # the state a new library is in
    # isVisible() is False for everything while the window itself is hidden,
    # so ask whether the widget was explicitly hidden instead
    assert page.empty.isHidden(), "the empty state covered the New album card"

    ix = page.model.index(0, 0)
    assert ix.isValid()
    from vrchronicle.pages import CardRole
    assert ix.data(CardRole)["kind"] == "new"

    # A real click, hit-tested through whatever is layered over the view --
    # calling _clicked directly would pass even with the overlay in the way.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window.show()
    QTest.qWaitForWindowExposed(window)
    opened = []
    page.card_activated = opened.append
    QTest.mouseClick(page.view.viewport(), Qt.LeftButton,
                     pos=page.view.visualRect(ix).center())
    window.hide()
    assert opened and opened[0]["kind"] == "new", "the click never reached the card"


def test_a_page_with_nothing_at_all_still_shows_its_empty_state(window):
    window.activate("worlds")
    page = window.page_worlds
    page.refresh()
    assert page.model.rowCount() == 0
    assert not page.empty.isHidden()


def test_the_year_picker_actually_changes_the_statistics(window):
    """It used to be wired to nothing at all."""
    window.activate("stats")
    page = window.page_stats
    assert page.cb_year.itemData(0) == ""            # "All time" comes first
    assert page.cb_year.count() > 1, "the library's year is missing"

    # "All time" shows every month there is, with each January carrying the year
    assert page.selected_year() == ""
    assert page.card_months._title.text() == "PHOTOS PER MONTH"
    all_bars = list(page.chart_months.data)
    assert all_bars and all(len(b) == 3 for b in all_bars)

    before = page.lab_sub.text()
    page.cb_year.setCurrentIndex(1)                  # pick the only real year
    assert page.card_months._title.text() == "PHOTOS PER MONTH"
    assert len(page.chart_months.data) <= len(all_bars)
    assert page.selected_year() == page.cb_year.currentText()
    assert page.lab_sub.text() != before, "picking a year changed nothing"
    assert page.lab_sub.text().startswith(page.selected_year())
    # and the poster button names the year it would build
    assert page.btn_year.text() == f"{page.poster_year()} in review"


def test_every_statistics_chart_actually_paints(window):
    """Setting a chart's data is not proof that it can draw it.

    A shape change to BarChart's data slipped through a suite that only ever
    called set_data, and blew up in paintEvent on screen.
    """
    from PySide6.QtGui import QPixmap
    rows = []
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            day = f"{year}-{month:02d}-05"
            rows.append({"path": f"/c/{year}{month}.png", "folder": "/c",
                         "filename": f"VRChat_{day}_10-00-00.000.png",
                         "taken_at": f"{day}T10:00:00", "day": day,
                         "filesize": 10, "mtime": 1.0})
    window.db.upsert_photos(rows)
    window.activate("stats")
    page = window.page_stats
    for year_ix in (0, 1):                       # All time, then one year
        page.cb_year.setCurrentIndex(year_ix)
        for chart in (page.chart_months, page.chart_worlds, page.chart_people,
                      page.chart_hours, page.chart_avatars, page.chart_instances,
                      page.chart_regions):
            chart.resize(900, 200)
            target = QPixmap(chart.size())
            chart.render(target)                 # raises if paintEvent throws
            assert not target.isNull()


def test_the_timeline_rail_lands_on_the_month_it_shows(window, app):
    """The rail used to place its marks by model row.

    A day header is one row and a whole band, while twenty photos are twenty
    rows in three bands, so row position is not proportional to height and the
    year labels sat well above where that year really started.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    rows = []
    for year in (2023, 2024, 2025):
        for month in range(1, 13):
            for n in range(6):
                day = f"{year}-{month:02d}-{(n % 27) + 1:02d}"
                name = f"VRChat_{day}_10-00-{n:02d}.000.png"
                rows.append({"path": f"/x/{year}{month:02d}{n}.png", "folder": "/x",
                             "filename": name, "taken_at": f"{day}T10:00:0{n}",
                             "day": day, "filesize": 100, "mtime": 1.0})
    window.db.upsert_photos(rows)

    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    page.refresh()
    app.processEvents()
    page._refresh_rail()
    app.processEvents()

    marks, total = page.rail_marks()
    assert len(marks) >= 30, "the library should span three years of months"
    assert total > page.view.viewport().height()
    assert marks == sorted(marks), "marks must run down the rail in order"

    def topmost(view):
        """First item under the top of the viewport, skipping the gaps."""
        w = view.viewport().width()
        for y in range(2, 70, 3):
            for x in (10, w // 2, w - 12):
                ix = view.indexAt(QPoint(x, y))
                if ix.isValid():
                    return ix
        return None

    bar = page.view.verticalScrollBar()
    checked = 0
    for px, ym in marks:
        if px > bar.maximum():
            continue                       # inside the last screenful: cannot scroll there
        bar.setValue(px)
        app.processEvents()
        ix = topmost(page.view)
        assert ix is not None, f"nothing at the top after jumping to {ym}"
        kind, payload = page.model._rows[ix.row()]
        day = payload[0] if kind != KIND_PHOTO_KIND else payload.day
        assert day[:7] == ym, f"the rail says {ym} but that point shows {day[:7]}"
        checked += 1
    assert checked >= 20, "too few marks were actually verifiable"


def _many_photos(db, years=(2025, 2026)):
    rows = []
    for year in years:
        for month in range(1, 13):
            for d in (4, 12, 21):
                day = f"{year}-{month:02d}-{d:02d}"
                for n in range(5):
                    rows.append({"path": f"/s/{year}{month:02d}{d}{n}.png", "folder": "/s",
                                 "filename": f"VRChat_{day}_10-00-0{n}.000.png",
                                 "taken_at": f"{day}T10:00:0{n}", "day": day,
                                 "filesize": 10, "mtime": 1.0})
    db.upsert_photos(rows)
    return rows


def test_ctrl_wheel_resizes_the_thumbnails_and_keeps_your_place(window, app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    bar = page.view.verticalScrollBar()
    bar.setValue(int(bar.maximum() * 0.4))
    app.processEvents()
    before_row = page._top_index().row()
    before_px = page.slider.value()

    def wheel(delta, mods):
        pos = QPointF(page.view.viewport().rect().center())
        return QWheelEvent(pos, page.view.viewport().mapToGlobal(pos.toPoint()),
                           QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods,
                           Qt.NoScrollPhase, False)

    page.view.wheelEvent(wheel(120, Qt.ControlModifier))
    app.processEvents()
    assert page.slider.value() > before_px, "ctrl+wheel up did not zoom in"
    app.processEvents()
    # the row you were looking at is still the row at the top
    assert page._top_index().row() == before_row

    page.view.wheelEvent(wheel(-120, Qt.ControlModifier))
    app.processEvents()
    assert page.slider.value() == before_px

    # without ctrl it must still scroll, not zoom
    at = bar.value()
    page.view.wheelEvent(wheel(-120, Qt.NoModifier))
    app.processEvents()
    assert page.slider.value() == before_px
    assert bar.value() != at
    window.hide()


def test_the_day_header_sticks_only_once_you_have_scrolled_past_it(window, app):
    from PySide6.QtTest import QTest

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    bar = page.view.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()
    page._sync_sticky()
    assert page.sticky.isHidden(), "nothing to pin while the real header is on screen"

    bar.setValue(int(bar.maximum() * 0.35))
    app.processEvents()
    page._sync_sticky()
    assert not page.sticky.isHidden(), "scrolled into a day but nothing was pinned"
    top = page.model.day_of_row(page._top_index().row())
    assert page.sticky._day == top[0]
    assert page.sticky._count == top[1]
    # it is the grid's own day header frozen, so it spans the viewport and
    # keeps that row's left inset rather than being indented like a card
    assert page.sticky.width() == page.view.viewport().width()
    from vrchronicle.gridmodel import KIND_HEADER, KindRole
    for r in range(page.model.rowCount()):
        ix = page.model.index(r, 0)
        if ix.data(KindRole) == KIND_HEADER:
            assert page.sticky.PAD == page.view.visualRect(ix).x() + 4
            break
    else:
        raise AssertionError("no day header to compare against")

    page.set_level("year")               # periods have no days to pin
    page._sync_sticky()
    assert page.sticky.isHidden()
    page._level_clicked("day")
    window.hide()


def test_the_grid_scrolls_under_the_floating_header(window, app):
    """The header is glass, so the photos have to actually be behind it.

    The grid fills the page and a spacer row of the header's height keeps the
    first day from starting life hidden underneath.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from vrchronicle.gridmodel import KIND_SPACER, KindRole
    from vrchronicle.widgets import Glass

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    h = page.head_height()
    assert h > 20
    assert page.model.index(0, 0).data(KindRole) == KIND_SPACER
    # the view reaches the top of the page: there is content under the header
    assert page.view.mapTo(page, QPoint(0, 0)).y() == 0
    assert page.headwrap.geometry().top() == 0   # flush: no sliver above it
    # it must not lie across the scrollbar or the rail
    vp = page.view.viewport()
    assert page.headwrap.geometry().right() <= vp.mapTo(page, QPoint(vp.width(), 0)).x()

    # nothing is hidden at rest: the first real row starts below the header
    first = page.view.visualRect(page.model.index(1, 0))
    assert first.top() >= h - 2, "the first day would sit under the header"

    # scrolled, photos really are behind the bar, and the glass samples them
    bar = page.view.verticalScrollBar()
    bar.setValue(int(bar.maximum() * 0.3))
    app.processEvents()
    vw = page.view.viewport().width()
    behind = None
    for y in range(4, h, 3):                 # the layout has gaps; probe a few points
        for x in (12, vw // 3, vw // 2):
            ix = page.view.indexAt(QPoint(x, y))
            if ix.isValid():
                behind = ix
                break
        if behind is not None:
            break
    assert behind is not None, "nothing scrolled under the header"
    blurred, offset = Glass.backdrop(page.headbar, page.view.viewport())
    assert blurred is not None and not blurred.isNull()
    window.hide()


def test_the_header_shrinks_once_you_are_scrolled_in(window, app):
    """And the grid must not jump while it does."""
    from PySide6.QtTest import QTest

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    open_h = page.headbar.height()
    reserved = page.head_height()
    assert page.titlecol.maximumWidth() > 0
    assert not page._collapsed

    bar = page.view.verticalScrollBar()
    bar.setValue(page.COLLAPSE_AT + 40)
    app.processEvents()
    assert page._collapsed
    page._apply_collapse(1.0)                 # skip to the end of the animation
    assert page.headbar.height() < open_h, "the header did not shrink"
    assert page.titlecol.maximumWidth() == 0
    assert page._title_fx.opacity() == 0.0
    # what the grid leaves free must NOT follow it, or the content jumps
    assert page.head_height() == reserved
    # and the pinned day follows the header down to its new height
    assert page.head_now() < reserved

    bar.setValue(0)
    app.processEvents()
    assert not page._collapsed
    page._apply_collapse(0.0)
    assert page.headbar.height() == open_h
    assert page.titlecol.maximumWidth() > 0
    assert page.head_height() == reserved
    window.hide()


def test_all_shows_one_continuous_sheet_of_photos(window, app):
    """No day headings, square tiles, and the row divided exactly."""
    from PySide6.QtTest import QTest
    from vrchronicle.gridmodel import KIND_HEADER, KIND_PHOTO, KindRole

    rows = _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    page.set_level("day")
    app.processEvents()
    kinds = [page.model.index(r, 0).data(KindRole)
             for r in range(page.model.rowCount())]
    assert KIND_HEADER in kinds, "Days groups by day"

    page.set_level("all")
    app.processEvents()
    kinds = [page.model.index(r, 0).data(KindRole)
             for r in range(page.model.rowCount())]
    assert KIND_HEADER not in kinds, "All must be one uninterrupted run"
    assert kinds.count(KIND_PHOTO) == len(rows) + 1     # + the fixture's photo
    assert page.delegate.dense and page.view.spacing() == 2

    cell = page.delegate.cell_size()
    assert cell.width() == cell.height(), "tiles are square in this mode"
    gap = page.view.spacing() * 2
    vw = page.view.viewport().width() - gap
    n = max(1, round(vw / (cell.width() + gap)))
    assert abs(n * cell.width() + (n - 1) * gap - vw) <= n, "the row does not divide"
    assert page.sticky.isHidden(), "there are no days to pin here"

    page.set_level("day")                    # and back, without leftovers
    app.processEvents()
    assert not page.delegate.dense and page.view.spacing() == 7
    assert page.delegate.cell_size().width() != page.delegate.cell_size().height()
    window.hide()


def test_scrolling_does_not_redo_work_it_can_keep(window, app):
    """Both of these ran on every frame and neither changes between frames."""
    from PySide6.QtTest import QTest
    from vrchronicle.widgets import Glass

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    # the frosted backdrop is sampled at most every TTL, not every repaint
    page.headbar._glass_cache = None
    first, _off = Glass.backdrop(page.headbar, page.view.viewport())
    again, _off = Glass.backdrop(page.headbar, page.view.viewport())
    assert first is again, "the backdrop was sampled twice in one frame"
    again, _off = Glass.backdrop(page.headbar, page.view.viewport(), ttl=0)
    assert again is not first, "ttl=0 must force a fresh sample"

    # a tile is rounded and scaled once, then blitted
    d = page.delegate
    d._tiles.clear()
    item = page.model.photos()[0]
    from PySide6.QtGui import QPixmap
    pm = QPixmap(400, 225)
    pm.fill()
    a = d._tile(item, pm, 176, 99)
    b = d._tile(item, pm, 176, 99)
    assert a is b, "the tile was rebuilt for the same cell size"
    assert d._tile(item, pm, 200, 112) is not a, "a new size needs a new tile"
    d.set_cell_width(190)
    assert not d._tiles, "changing the thumbnail size must drop them"
    window.hide()


def test_the_wheel_glides_instead_of_jumping(window, app):
    """One notch used to move the bar in a single step."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    bar = page.view.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()
    smooth = page.view.smooth

    pos = QPointF(page.view.viewport().rect().center())
    ev = QWheelEvent(pos, page.view.viewport().mapToGlobal(pos.toPoint()),
                     QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    app.sendEvent(page.view.viewport(), ev)

    assert smooth._target == smooth.step, "the notch did not set a target"
    assert bar.value() == 0, "the bar must not jump to it in one step"

    # walk the animation with a fake clock, one 120 Hz frame at a time
    frame = 1.0 / 120.0
    seen = []
    for _ in range(400):
        smooth._step(frame)
        seen.append(bar.value())
        if smooth._target is None:
            break
    assert len(seen) > 8, f"it arrived in {len(seen)} frames, that is a jump"
    assert seen == sorted(seen), "it must only move one way"
    assert seen[-1] == smooth.step
    # decelerating: the first frame moves further than the last
    assert seen[0] - 0 > seen[-1] - seen[-2]

    # Time-based, not per-tick: a faster display gives MORE frames over the
    # same span, not a quicker arrival.
    def frames_at(hz):
        bar.setValue(0)
        smooth.stop()
        smooth._target, smooth._pos = smooth.step, 0.0
        n = 0
        while smooth._target is not None and n < 2000:
            smooth._step(1.0 / hz)
            n += 1
        return n
    slow, fast = frames_at(60), frames_at(144)
    assert fast > slow * 2, f"144Hz gave {fast} frames vs {slow} at 60Hz"
    assert abs(fast / 144.0 - slow / 60.0) < 0.05, "the glide changed duration"
    assert 60.0 <= smooth.hz <= 240.0

    # ctrl+wheel still zooms rather than scrolling
    before = page.slider.value()
    ev = QWheelEvent(pos, page.view.viewport().mapToGlobal(pos.toPoint()),
                     QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    app.sendEvent(page.view.viewport(), ev)
    app.processEvents()
    assert page.slider.value() > before
    window.hide()


def test_the_floating_panels_render_their_glass(window, app):
    """Glass samples a sibling's content, which mapTo cannot address.

    These panels are painted by hand and nothing else in the suite draws them,
    so a mapping or paint mistake would only ever show up on screen.
    """
    from PySide6.QtGui import QPixmap
    from PySide6.QtTest import QTest
    from vrchronicle.widgets import Glass

    _many_photos(window.db)
    window.resize(1200, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activate("all")
    page = window.page_grid
    app.processEvents()

    bar = page.view.verticalScrollBar()
    bar.setValue(int(bar.maximum() * 0.35))
    app.processEvents()

    from PySide6.QtCore import QItemSelectionModel
    sel = page.view.selectionModel()
    for row in range(3, 6):
        sel.select(page.model.index(row, 0), QItemSelectionModel.Select)
    app.processEvents()
    assert not page.selbar.isHidden(), "selecting photos should raise the bar"

    # the selection bar floats over photos, so its backdrop is really sampled
    blurred, offset = Glass.backdrop(page.selbar, page.view.viewport())
    assert blurred is not None and not blurred.isNull()
    assert offset.x() <= 0 and offset.y() <= 0, "the sample must start outside the panel"
    assert blurred.width() >= page.selbar.width()

    for w in (page.sticky, page.selbar):
        w.resize(max(80, w.width()), max(24, w.height()))
        target = QPixmap(w.size())
        w.render(target)                       # raises if paintEvent throws
        assert not target.isNull()

    window.toast("Glass", "ok")
    app.processEvents()
    target = QPixmap(window.toast_w.size())
    window.toast_w.render(target)
    assert not target.isNull()

    rail = page.rail
    rail._show_bubble(rail.height() * 0.4)
    assert rail._bubble is not None
    target = QPixmap(rail._bubble.size())
    rail._bubble.render(target)
    assert not target.isNull()
    rail._hide_bubble()
    window.hide()


def test_the_window_wears_its_own_chrome(window, app):
    """Frameless with a custom bar, and still a well-behaved window."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    assert window.windowFlags() & Qt.FramelessWindowHint
    tb = window.titlebar
    for b in (tb.btn_min, tb.btn_max, tb.btn_close):
        assert b.isEnabled()

    window.resize(1100, 700)
    window.show()
    QTest.qWaitForWindowExposed(window)
    app.processEvents()

    # the edges must be grabbable for resizing, and the corners diagonal
    w, h = window.width(), window.height()
    assert window._edges_at(QPoint(2, h // 2)) == Qt.LeftEdge
    assert window._edges_at(QPoint(w - 2, h // 2)) == Qt.RightEdge
    assert window._edges_at(QPoint(2, 2)) == (Qt.LeftEdge | Qt.TopEdge)
    assert not window._edges_at(QPoint(w // 2, h // 2))
    assert window._cursor_for(Qt.LeftEdge | Qt.TopEdge) == Qt.SizeFDiagCursor
    assert window._cursor_for(Qt.RightEdge) == Qt.SizeHorCursor
    assert window._cursor_for(window.NO_EDGE) is None

    # A frameless window that maximises to the FULL screen covers the taskbar.
    tb.toggle_max()
    app.processEvents()
    assert window.isMaximized()
    avail = window.screen().availableGeometry()
    g = window.frameGeometry()
    assert avail.contains(g), f"maximised past the work area: {g} vs {avail}"
    # nothing to grab while maximised, and the panels sit flush
    assert not window._edges_at(QPoint(2, 2))

    tb.toggle_max()
    app.processEvents()
    assert not window.isMaximized()
    window.hide()


def test_browsing_zooms_from_years_to_months_to_days(window, app):
    from vrchronicle.gridmodel import KIND_PERIOD, ItemRole, KindRole

    rows = []
    for year in (2024, 2025):
        for month in (3, 7):
            for n in range(4):
                day = f"{year}-{month:02d}-0{n + 1}"
                rows.append({"path": f"/x/{year}{month}{n}.png", "folder": "/x",
                             "filename": f"VRChat_{day}_10-00-0{n}.000.png",
                             "taken_at": f"{day}T10:00:0{n}", "day": day,
                             "filesize": 10, "mtime": 1.0})
    window.db.upsert_photos(rows)
    window.activate("all")
    page = window.page_grid
    assert not page.levels.isHidden(), "the level control belongs on Photos"

    def cards(page):
        """(index, payload) for the period cards, skipping the header spacer."""
        out = []
        for r in range(page.model.rowCount()):
            ix = page.model.index(r, 0)
            if ix.data(KindRole) == KIND_PERIOD:
                out.append((ix, ix.data(ItemRole)))
        return out

    def card_for(page, key):
        for ix, d in cards(page):
            if d["key"] == key:
                return ix
        raise AssertionError(f"no card for {key}")

    page.set_level("year")
    got = cards(page)
    assert [d["label"] for _ix, d in got] == ["2026", "2025", "2024"]  # newest first
    # the photo-only controls step aside at this level
    assert page.slider.isHidden() and page.sort_box.isHidden()

    page._open_from_index(card_for(page, "2024"))
    assert page.level == "month" and page._level_year == "2024"
    assert [d["key"] for _ix, d in cards(page)] == ["2024-07", "2024-03"]

    page._open_from_index(card_for(page, "2024-03"))
    assert page.level == "day"
    assert page.filter.date_from == "2024-03-01"
    assert page.filter.date_to == "2024-03-31"
    assert len(page.model.photos()) == 4
    assert not page.slider.isHidden(), "the photo controls come back at Days"

    page._level_clicked("day")                        # asking for Days means all days
    assert page.filter.date_from == "" and page.filter.date_to == ""
    assert len(page.model.photos()) == len(rows) + 1


def test_a_drill_page_has_no_level_control(window):
    """Years/Months only make sense for the whole library, not for one world."""
    window.activate("all")
    assert not window.page_grid.levels.isHidden()
    window.push_person("Nobody At All")
    window.activate("all")
    window.page_grid.configure(window.page_grid.filter, "Someone", back=True)
    assert window.page_grid.levels.isHidden()
    assert window.page_grid.level == "day"


def test_filters_apply_without_error(window):
    page = window.page_grid
    window.activate("all")
    page.btn_filter.setChecked(True)
    page._apply_filters()
    page._clear_filters()
