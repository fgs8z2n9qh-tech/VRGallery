"""Dragging photos out of the grid.

The important test in here is the one about CopyAction. Qt's default for an item
view offers whatever the drop target supports, and a folder accepts a move --
which would take the originals out of the VRChat folder and leave the library
pointing at nothing.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication

from vrgallery import gridmodel, paths
from vrgallery.gridmodel import KIND_HEADER, KIND_PHOTO, KIND_SPACER, GridModel, GridView


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def grid(app, tmp_path):
    """A grid over three photos, two of which are really on disk."""
    folder = tmp_path / "photos"
    folder.mkdir()
    rows = []
    for i in range(3):
        name = f"VRChat_2026-03-0{i + 1}_12-00-00.000.png"
        path = folder / name
        if i < 2:                       # the third one is missing from disk
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        rows.append({
            "id": i + 1, "path": str(path), "taken_at": f"2026-03-0{i + 1}T12:00:00",
            "day": f"2026-03-0{i + 1}", "world_id": None, "world_name": "Somewhere",
            "favorite": 0, "width": 100, "height": 100, "filesize": 72,
            "mtime": 1.0, "meta_source": "", "avatar_name": None,
            "session_id": None, "instance_type": "", "rating": 0, "is_video": 0,
        })
    model = GridModel()
    model.set_photos(rows, group_by_day=True, top_gap=40)
    view = GridView()
    view.setModel(model)
    view.resize(600, 400)
    return view, model, [str(folder / f"VRChat_2026-03-0{i + 1}_12-00-00.000.png")
                         for i in range(3)]


def _items(model):
    return [p for k, p in model._rows if k == KIND_PHOTO]


# ------------------------------------------------------------------- safety

def test_a_drag_only_ever_offers_a_copy(grid, monkeypatch):
    """A move would take the originals out of the VRChat folder."""
    view, model, _paths = grid
    seen = {}

    class FakeDrag:
        def __init__(self, _parent):
            pass

        def setMimeData(self, m):
            seen["mime"] = m

        def setPixmap(self, pm):
            seen["pixmap"] = pm

        def setHotSpot(self, pt):
            pass

        def exec(self, *actions):
            seen["actions"] = actions
            return Qt.CopyAction

    monkeypatch.setattr(gridmodel, "QDrag", FakeDrag)
    view.selected_photo_items = lambda: _items(model)[:2]
    view.startDrag(Qt.CopyAction | Qt.MoveAction)     # Qt offering us a move

    assert "actions" in seen, "the drag never started"
    for a in seen["actions"]:
        assert a == Qt.CopyAction, f"a drag offered {a}"


def test_the_view_cannot_receive_a_drop(grid):
    """Nothing should be able to drop INTO the grid and change the library."""
    view, _model, _paths = grid
    assert view.dragDropMode() == QAbstractItemView.DragOnly
    assert view.defaultDropAction() == Qt.CopyAction
    assert view.dragEnabled()


# -------------------------------------------------------------- what is sent

def test_the_drag_carries_file_urls(grid):
    view, model, all_paths = grid
    mime, sent = view.drag_payload(_items(model)[:2])
    assert mime is not None
    urls = [u.toLocalFile() for u in mime.urls()]
    assert [os.path.normcase(u) for u in urls] == \
           [os.path.normcase(p) for p in all_paths[:2]]
    assert mime.hasUrls() and mime.hasText()
    assert sent == all_paths[:2]


def test_a_photo_that_is_no_longer_on_disk_is_left_behind(grid):
    """A library outlives the folder it points at; a URL to nothing gets the
    user an error dialog from Explorer instead of from us."""
    view, model, all_paths = grid
    mime, sent = view.drag_payload(_items(model))     # all three, one missing
    assert len(sent) == 2
    assert all_paths[2] not in sent


def test_dragging_nothing_but_missing_files_starts_no_drag(grid, monkeypatch):
    view, model, _paths = grid
    missing = [it for it in _items(model) if not os.path.exists(it.path)]
    assert missing, "the fixture should have one missing photo"
    mime, sent = view.drag_payload(missing)
    assert mime is None and sent == []

    started = []
    monkeypatch.setattr(gridmodel, "QDrag",
                        lambda _p: started.append(1) or pytest.fail("drag started"))
    view.selected_photo_items = lambda: missing
    view.startDrag(Qt.CopyAction)
    assert not started


# ------------------------------------------------------------- what can drag

def test_only_photos_are_draggable(grid):
    """A day header or the header spacer must not pick up and travel."""
    view, model, _paths = grid
    for row, (kind, _payload) in enumerate(model._rows):
        f = model.flags(model.index(row))
        draggable = bool(f & Qt.ItemIsDragEnabled)
        if kind == KIND_PHOTO:
            assert draggable, f"row {row} is a photo and will not drag"
        else:
            assert not draggable, f"row {row} is a {kind} and should not drag"
    assert KIND_HEADER in [k for k, _ in model._rows]
    assert KIND_SPACER in [k for k, _ in model._rows]


def test_the_cursor_carries_a_thumbnail_and_a_count(grid):
    view, model, _paths = grid
    one = view.drag_pixmap(_items(model)[:1], None)
    many = view.drag_pixmap(_items(model), None)
    assert not one.isNull() and not many.isNull()
    assert one.size() == many.size()
    # the badge only appears when there is more than one, so the two differ
    assert one.toImage() != many.toImage(), "no count badge on a multi-photo drag"
