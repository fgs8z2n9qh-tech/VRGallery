"""A run of shots seconds apart, folded into one tile.

Measured on the author's library: 108 runs of three or more within 30 seconds,
holding 400 photographs -- 22% of everything, and the visible tiles fall from
1812 to 1520. On the grid it is the difference between a day and eight nearly
identical frames of the same pose.

THE DANGEROUS PART, and the reason most of this file exists: a collapsed burst
is ONE row standing for many photographs. Every destructive path in the app --
delete, the drag out to Explorer or Discord, favouriting, the count on the
selection bar -- goes through selected_photo_items(). Return the representative
alone and selecting a stack of eight and dragging it out quietly sends one file,
with nothing on screen to say so.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication

from vrgallery.gridmodel import (KIND_BURST, KIND_HEADER, KIND_PHOTO, KIND_SPACER,
                                 GridModel, GridView)


@pytest.fixture(scope="module", autouse=True)
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


_KEEP = []


def rows(spec):
    """spec: [(day, 'HH:MM:SS'), ...] -> photo rows in that order."""
    out = []
    for i, (day, hms) in enumerate(spec):
        out.append({
            "id": i + 1, "path": f"/p/{i}.png", "taken_at": f"{day}T{hms}",
            "day": day, "world_name": "", "favorite": 0, "filesize": 10,
            "mtime": float(i), "width": 0, "height": 0, "rating": 0,
            "is_video": 0, "world_id": None, "meta_source": "",
            "avatar_name": None, "session_id": None, "instance_type": "",
        })
    return out


def model_of(spec, group_by_day=True, collapse=True):
    m = GridModel()
    _KEEP.append(m)
    m.collapse = collapse
    m.set_photos(rows(spec), group_by_day=group_by_day)
    return m


def kinds(m):
    return [k for k, _p in m._rows]


D1, D2 = "2026-02-01", "2026-02-02"


# ------------------------------------------------------------- the grouping

def test_a_run_of_three_seconds_apart_becomes_one_tile():
    m = model_of([(D1, "10:00:00"), (D1, "10:00:05"), (D1, "10:00:11")])
    assert kinds(m) == [KIND_HEADER, KIND_BURST]
    assert len(m._rows[1][1]) == 3


def test_two_shots_are_not_a_burst():
    """Two of a thing is a pair, not a run; folding them hides one photograph
    behind a badge for no gain at all."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:05")])
    assert kinds(m) == [KIND_HEADER, KIND_PHOTO, KIND_PHOTO]


def test_a_gap_ends_the_run():
    m = model_of([(D1, "10:00:00"), (D1, "10:00:05"), (D1, "10:00:10"),
                  (D1, "10:05:00"), (D1, "10:05:04"), (D1, "10:05:08")])
    assert kinds(m) == [KIND_HEADER, KIND_BURST, KIND_BURST]
    assert [len(m._rows[i][1]) for i in (1, 2)] == [3, 3]


def test_a_run_never_crosses_a_day():
    """Midnight to midnight is thirty seconds apart often enough, and a stack
    that belonged to two days would sit under one of their headers."""
    m = model_of([(D1, "23:59:50"), (D1, "23:59:55"), (D2, "00:00:02"),
                  (D2, "00:00:06"), (D2, "00:00:10")])
    assert kinds(m) == [KIND_HEADER, KIND_PHOTO, KIND_PHOTO, KIND_HEADER, KIND_BURST]


def test_a_long_shoot_does_not_become_one_enormous_tile():
    """A sitting with no pause in it would otherwise fold whole. It did: the
    entire All sheet collapsed to a single tile in a test."""
    m = model_of([(D1, f"10:00:{s:02d}") for s in range(0, 50, 2)])
    assert all(len(p) <= GridModel.BURST_MAX
               for k, p in m._rows if k == KIND_BURST)
    assert sum(1 for k in kinds(m) if k == KIND_BURST) > 1


def test_a_photo_with_no_readable_time_ends_the_run():
    """A burst is a claim about time; with none to go on, claim nothing."""
    spec = rows([(D1, "10:00:00"), (D1, "10:00:04"), (D1, "10:00:08")])
    spec[1]["taken_at"] = "not-a-timestamp"
    m = GridModel()
    _KEEP.append(m)
    m.set_photos(spec)
    assert KIND_BURST not in kinds(m)


def test_the_flat_sheet_is_never_folded():
    """The All level is deliberately one uninterrupted wall of the library, and
    it has no day boundaries to stop a run."""
    m = model_of([(D1, f"10:00:{s:02d}") for s in range(0, 12)],
                 group_by_day=False)
    assert kinds(m) == [KIND_PHOTO] * 12


def test_collapsing_can_be_turned_off():
    spec = [(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")]
    m = model_of(spec, collapse=False)
    assert kinds(m) == [KIND_HEADER, KIND_PHOTO, KIND_PHOTO, KIND_PHOTO]
    m.set_collapse_bursts(True)
    assert kinds(m) == [KIND_HEADER, KIND_BURST]


# ------------------------------------------------ what a fold must not break

def test_the_photo_list_is_never_folded():
    """photos() is what the lightbox walks and what the API hands out. Folding
    it would make a stack's other seven shots unreachable everywhere."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    assert len(m.photos()) == 3


def test_every_photo_in_a_stack_still_knows_where_it_is():
    """row_of_id is how the app reveals a photograph. For one inside a stack the
    answer is the stack's row -- not -1, which would scroll nowhere."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    burst_row = kinds(m).index(KIND_BURST)
    for it in m.photos():
        assert m.row_of_id(it.id) == burst_row


def test_a_stack_opens_at_the_start_of_its_run():
    """It paints the LAST frame, because that is usually the keeper. Opening
    there would put you at the end of the run with nowhere to go but back."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    assert m.photo_pos(kinds(m).index(KIND_BURST)) == 0


def test_the_day_still_counts_every_photograph():
    """The header counts photographs, not tiles: three shown as one stack is
    still a day with three photographs in it."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    assert m._rows[0] == (KIND_HEADER, (D1, 3))


def test_the_rail_and_the_pinned_day_survive_a_stack():
    """Both read a date off whatever is at a row, and a stack's payload is a
    list -- they used to reach for .day on it and raise."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    row = kinds(m).index(KIND_BURST)
    assert m.day_of_row(row)[0] == D1
    assert m.month_marks()[0][1] == D1[:7]


def test_opening_a_stack_puts_its_photographs_back_one_by_one():
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    first = m._rows[kinds(m).index(KIND_BURST)][1][0]
    assert m.toggle_burst(first.id)
    assert kinds(m) == [KIND_HEADER, KIND_PHOTO, KIND_PHOTO, KIND_PHOTO]
    assert m.toggle_burst(first.id)
    assert kinds(m) == [KIND_HEADER, KIND_BURST]


def test_a_new_list_closes_whatever_was_open():
    """Otherwise an id from the old library keeps a run open in the new one."""
    m = model_of([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    m.toggle_burst(m.photos()[0].id)
    assert KIND_BURST not in kinds(m)
    m.set_photos(rows([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")]))
    assert KIND_BURST in kinds(m)


# --------------------------------------------- the part that loses your files

def _view_with(spec):
    v = GridView()
    _KEEP.append(v)
    m = GridModel()
    _KEEP.append(m)
    m.set_photos(rows(spec))
    v.setModel(m)
    v.resize(900, 600)
    return v, m


def test_selecting_a_stack_means_selecting_every_photograph_in_it():
    """THE one that matters. Every destructive path goes through here."""
    v, m = _view_with([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06"),
                       (D1, "10:00:09")])
    row = kinds(m).index(KIND_BURST)
    v.selectionModel().select(m.index(row, 0), QItemSelectionModel.Select)
    got = v.selected_photo_items()
    assert len(got) == 4, (
        f"a stack of four selected {len(got)} photograph(s); deleting or "
        f"dragging that selection would have touched only those")
    assert {it.id for it in got} == {it.id for it in m.photos()}


def test_dragging_a_stack_carries_every_file():
    """The drag payload is built from the selection, so this follows from the
    test above -- and is worth pinning down anyway, because it is the path that
    puts files into somebody else's Discord."""
    v, m = _view_with([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    row = kinds(m).index(KIND_BURST)
    v.selectionModel().select(m.index(row, 0), QItemSelectionModel.Select)
    items = v.drag_order(v.selected_photo_items())
    assert len(items) == 3


def test_a_stack_is_still_a_thing_you_can_drag():
    """It stands for files, so it has to carry the drag flags a photo does."""
    v, m = _view_with([(D1, "10:00:00"), (D1, "10:00:03"), (D1, "10:00:06")])
    row = kinds(m).index(KIND_BURST)
    fl = m.flags(m.index(row, 0))
    assert fl & Qt.ItemIsSelectable and fl & Qt.ItemIsDragEnabled


def test_selection_still_works_for_a_plain_photograph():
    """The expansion must not have broken the ordinary case."""
    v, m = _view_with([(D1, "10:00:00"), (D1, "10:30:00")])
    for row, (kind, _p) in enumerate(m._rows):
        if kind == KIND_PHOTO:
            v.selectionModel().select(m.index(row, 0), QItemSelectionModel.Select)
            break
    assert len(v.selected_photo_items()) == 1
