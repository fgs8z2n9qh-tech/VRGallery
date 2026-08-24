"""Dragging photos out of the grid.

The important test in here is the one about CopyAction. Qt's default for an item
view offers whatever the drop target supports, and a folder accepts a move --
which would take the originals out of the VRChat folder and leave the library
pointing at nothing.

The rest exist because an adversarial review of the first version of this file
found it green against six separate mutations, including deleting setUrls and
calling drag.exec() with no arguments at all -- which makes Qt default the
supported actions to MoveAction. Every test here drives a real press, because
the guards that keep a favourite click or a context menu from turning into a
file drag live in mousePressEvent and nothing that stubs the selection can see
them.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication

from vrgallery import gridmodel
from vrgallery.gridmodel import (KIND_HEADER, KIND_PERIOD, KIND_PHOTO, KIND_SPACER,
                                 GridModel, GridView, ItemRole, KindRole, PhotoDelegate)


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


class FakeCache:
    """A thumbnail cache that records whether anyone asked it to FETCH.

    get() is not a lookup in the real one: it queues a decode. The drag ghost
    wants a picture that already exists, and testing with cache=None hid that
    it was calling the wrong one.
    """

    def __init__(self, have=()):
        self.have = {}
        for pid in have:
            pm = QPixmap(64, 64)
            pm.fill(Qt.red)
            self.have[pid] = pm
        self.gets = []
        self.peeks = []

    def get(self, item, scanned_hint=1):
        self.gets.append(getattr(item, "id", item))
        return self.have.get(getattr(item, "id", item))

    def peek(self, pid):
        self.peeks.append(pid)
        return self.have.get(pid)

    def age_ms(self, _pid):
        return 9999.0


@pytest.fixture()
def grid(app, tmp_path):
    """A shown grid over three photos, two of which are really on disk."""
    folder = tmp_path / "photos"
    folder.mkdir()
    rows, paths = [], []
    for i in range(3):
        name = f"VRChat_2026-03-0{i + 1}_12-00-00.000.png"
        path = folder / name
        if i < 2:                       # the third one is missing from disk
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        paths.append(str(path))
        rows.append({
            "id": i + 1, "path": str(path), "taken_at": f"2026-03-0{i + 1}T12:00:00",
            "day": "2026-03-01", "world_id": None, "world_name": "Somewhere",
            "favorite": 0, "width": 100, "height": 100, "filesize": 72,
            "mtime": 1.0, "meta_source": "", "avatar_name": None,
            "session_id": None, "instance_type": "", "rating": 0, "is_video": 0,
        })
    model = GridModel()
    model.set_photos(rows, group_by_day=True, top_gap=40)
    view = GridView()
    view.setModel(model)
    cache = FakeCache(have=(1, 2, 3))
    view.setItemDelegate(PhotoDelegate(view, cache))
    view.resize(700, 500)
    view.show()
    app.processEvents()
    yield view, model, paths, cache
    view.hide()


def _rows_of(model, kind):
    return [r for r, (k, _p) in enumerate(model._rows) if k == kind]


def _items(model):
    return [p for k, p in model._rows if k == KIND_PHOTO]


def _press_on(view, row, button=Qt.LeftButton, at=None):
    """A real press, so the guards in mousePressEvent actually run."""
    ix = view.model().index(row)
    r = view.visualRect(ix)
    pos = at or r.center()
    QTest.mousePress(view.viewport(), button, Qt.NoModifier, pos)
    return ix


class FakeDrag:
    """Records everything the real QDrag would have been told."""
    last = None

    def __init__(self, _parent):
        self.mime = None
        self.pixmap = None
        self.hotspot = None
        self.actions = None
        FakeDrag.last = self

    def setMimeData(self, m):
        self.mime = m

    def setPixmap(self, pm):
        self.pixmap = pm

    def setHotSpot(self, pt):
        self.hotspot = pt

    def exec(self, *actions):
        self.actions = actions
        return Qt.CopyAction


@pytest.fixture()
def fakedrag(monkeypatch):
    FakeDrag.last = None
    monkeypatch.setattr(gridmodel, "QDrag", FakeDrag)
    return FakeDrag


# ------------------------------------------------------------------- safety

def test_a_drag_only_ever_offers_a_copy(grid, fakedrag):
    """A move would take the originals out of the VRChat folder.

    Note the assertion on a NON-EMPTY actions tuple: drag.exec() with no
    arguments is legal and makes Qt default the supported actions to MoveAction,
    and `"actions" in seen` was green against exactly that.
    """
    view, model, _paths, _cache = grid
    photo_rows = _rows_of(model, KIND_PHOTO)
    view.selectionModel().select(model.index(photo_rows[0]),
                                 view.selectionModel().SelectionFlag.Select)
    _press_on(view, photo_rows[0])
    view.startDrag(Qt.CopyAction | Qt.MoveAction)     # Qt offering us a move

    d = fakedrag.last
    assert d is not None and d.actions, "the drag never started, or exec took no arguments"
    for a in d.actions:
        assert a == Qt.CopyAction, f"a drag offered {a}"


def test_the_view_cannot_receive_a_drop(grid):
    """Nothing should be able to drop INTO the grid and change the library."""
    view, _model, _paths, _cache = grid
    assert view.dragDropMode() == QAbstractItemView.DragOnly
    assert view.defaultDropAction() == Qt.CopyAction
    assert not view.viewport().acceptDrops()


# ------------------------------------------------- which gestures may drag

def test_a_right_press_never_becomes_a_drag(grid, fakedrag):
    """Qt's drag branch tests buttons() != NoButton, so a right-press and a
    wobble started a drag, and the drag grabbed the mouse, and the context menu
    never opened."""
    view, model, _paths, _cache = grid
    row = _rows_of(model, KIND_PHOTO)[0]
    view.selectionModel().select(model.index(row),
                                 view.selectionModel().SelectionFlag.Select)
    _press_on(view, row, button=Qt.RightButton)
    assert not view.dragEnabled()
    view.startDrag(Qt.CopyAction)
    assert fakedrag.last is None, "a right-press started a file drag"


def test_a_press_on_a_day_header_never_drags_the_selection(grid, fakedrag):
    """A header keeps ItemIsEnabled, so ctrl-pressing one kept the selection and
    eight pixels of movement flung every selected photo into the drop target."""
    view, model, _paths, _cache = grid
    for r in _rows_of(model, KIND_PHOTO):
        view.selectionModel().select(model.index(r),
                                     view.selectionModel().SelectionFlag.Select)
    _press_on(view, _rows_of(model, KIND_HEADER)[0])
    assert not view.dragEnabled()
    view.startDrag(Qt.CopyAction)
    assert fakedrag.last is None, "a header press dragged the whole selection out"


def test_a_press_on_the_favourite_star_never_drags(grid, fakedrag):
    """The star is a 27 px target with its own click; a twelve-pixel wobble on it
    used to become a file drag instead of a favourite."""
    view, model, _paths, _cache = grid
    row = _rows_of(model, KIND_PHOTO)[0]
    ix = model.index(row)
    star = view.itemDelegate()._star_rect(view.visualRect(ix)).center()
    view.selectionModel().select(ix, view.selectionModel().SelectionFlag.Select)
    _press_on(view, row, at=star)
    assert not view.dragEnabled(), "the star press armed a drag"
    view.startDrag(Qt.CopyAction)
    assert fakedrag.last is None


def test_a_period_card_is_not_draggable(app):
    """A year card is a place to go, not a file -- and leaving it draggable cost
    it the single click that opens it, which is the only way in."""
    model = GridModel()
    model.set_periods(
        [{"k": "2026", "c": 12, "b": 999, "cover_id": None}], "year", {}, top_gap=40)
    rows = _rows_of(model, KIND_PERIOD)
    assert rows, "the fixture built no period card"
    for r in rows:
        assert not (model.flags(model.index(r)) & Qt.ItemIsDragEnabled)


def test_only_photos_carry_the_drag_flag(grid):
    view, model, _paths, _cache = grid
    kinds = {k for k, _ in model._rows}
    assert {KIND_PHOTO, KIND_HEADER, KIND_SPACER} <= kinds
    for row, (kind, _payload) in enumerate(model._rows):
        draggable = bool(model.flags(model.index(row)) & Qt.ItemIsDragEnabled)
        assert draggable == (kind == KIND_PHOTO), f"row {row} ({kind}) drag={draggable}"


# -------------------------------------------------------------- what is sent

def test_the_drag_carries_file_urls(grid, fakedrag):
    """Asserted on the mime itself, not on what drag_payload returned: building
    the URLs from the unfiltered items passed the old version of this."""
    view, model, paths, _cache = grid
    for r in _rows_of(model, KIND_PHOTO):
        view.selectionModel().select(model.index(r),
                                     view.selectionModel().SelectionFlag.Select)
    _press_on(view, _rows_of(model, KIND_PHOTO)[0])
    view.startDrag(Qt.CopyAction)

    mime = fakedrag.last.mime
    urls = [os.path.normcase(u.toLocalFile()) for u in mime.urls()]
    assert urls, "no file urls in the payload"
    assert set(urls) == {os.path.normcase(p) for p in paths[:2]}
    assert os.path.normcase(paths[2]) not in urls, "a missing file was sent"
    # A plain-text list too, for targets that take text but not files. Asserting
    # that text/plain merely EXISTS proves nothing: Qt synthesises it from the
    # uri-list, so deleting setText() left this green with the target receiving
    # "file:///C:/..." instead of a path.
    text = mime.text()
    assert not text.startswith("file:"), "text/plain is just the uri-list"
    assert paths[0] in text, "the plain-text fallback is not the file paths"


def test_the_photo_under_the_hand_leads(grid, fakedrag):
    """The order the target receives them in is the order you see, and the one
    you grabbed comes first -- so the ghost shows the tile in your hand rather
    than the far end of the selection."""
    view, model, paths, _cache = grid
    photo_rows = _rows_of(model, KIND_PHOTO)
    for r in photo_rows:
        view.selectionModel().select(model.index(r),
                                     view.selectionModel().SelectionFlag.Select)
    second = model.index(photo_rows[1])
    # NoUpdate: setCurrentIndex() on its own CLEARS the selection down to that
    # one index, which left this test asserting on a selection of one and green
    # against the reordering being deleted entirely.
    view.selectionModel().setCurrentIndex(
        second, view.selectionModel().SelectionFlag.NoUpdate)
    selected = view.selected_photo_items()
    assert len(selected) > 1, "the selection collapsed; this proves nothing"
    ordered = view.drag_order(selected)
    assert ordered[0] is second.data(ItemRole), "the grabbed photo is not first"


def test_a_photo_that_is_no_longer_on_disk_is_left_behind(grid):
    view, model, paths, _cache = grid
    mime, sent = view.drag_payload(_items(model))     # all three, one missing
    assert sent == paths[:2]
    assert [u.toLocalFile() for u in mime.urls()]


def test_dragging_nothing_but_missing_files_starts_no_drag(grid, fakedrag):
    view, model, _paths, _cache = grid
    missing = [it for it in _items(model) if not os.path.exists(it.path)]
    assert missing, "the fixture should have one missing photo"
    assert view.drag_payload(missing) == (None, [])


# --------------------------------------------------------------- the ghost

def test_the_ghost_never_asks_the_cache_to_fetch(grid, fakedrag):
    """cache.get() queues a decode. Dragging a select-all through it queued
    fourteen hundred jobs and emptied the cache the viewport was using."""
    view, model, _paths, cache = grid
    cache.gets.clear()
    pm = view.drag_pixmap(_items(model), cache)
    assert not pm.isNull()
    assert cache.peeks, "the ghost did not look up a thumbnail at all"
    assert cache.gets == [], "the ghost queued thumbnail work"


def test_the_badge_counts_what_will_actually_land(grid, fakedrag, monkeypatch):
    """Offscreen has no font engine, so every glyph rasterizes to the same
    .notdef box -- the count has to be read off the drawText call, not the
    pixels. The badge counted the selection, so eight selected with three gone
    promised eight and delivered five."""
    view, model, paths, _cache = grid
    drawn = []
    real = gridmodel.QPainter.drawText

    def spy(self, *a):
        if a and isinstance(a[-1], str):
            drawn.append(a[-1])
        return real(self, *a)

    monkeypatch.setattr(gridmodel.QPainter, "drawText", spy)
    for r in _rows_of(model, KIND_PHOTO):
        view.selectionModel().select(model.index(r),
                                     view.selectionModel().SelectionFlag.Select)
    _press_on(view, _rows_of(model, KIND_PHOTO)[0])
    view.startDrag(Qt.CopyAction)

    assert fakedrag.last.pixmap is not None and not fakedrag.last.pixmap.isNull()
    assert fakedrag.last.hotspot is not None
    assert "2" in drawn, f"badge said {drawn!r}, but only two files are going"
    assert "3" not in drawn, "the badge counted a photo that is not on disk"
