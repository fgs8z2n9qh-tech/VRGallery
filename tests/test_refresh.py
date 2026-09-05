"""Rebuilding the grid for an answer that has not changed.

An index pass runs at launch, 2.5 seconds after every new screenshot, and --
this is the one that matters -- every time LiveWatcher notices the VRChat log
grew, which while the game is running is every fifteen seconds. Each pass ended
with after_photos_changed() -> GridPage.refresh(), which re-queried and called
beginResetModel unconditionally.

That is 32 ms of teardown and rebuild for a list that is usually identical,
but the cost is not the point: beginResetModel drops the view's scroll position
and its selection. Play VRChat with the gallery open and the grid throws you
back to the top of the library every fifteen seconds, under your hand.

refresh() now compares the answer it got with the answer it is already showing.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from vrgallery import paths


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
        "path": str(tmp_path / "photos" / f"VRChat_2026-02-0{1 + d // 20}"
                    f"_10-{d:02d}-00.000.png"),
        "folder": str(tmp_path / "photos"),
        "filename": f"VRChat_2026-02-0{1 + d // 20}_10-{d:02d}-00.000.png",
        "taken_at": f"2026-02-0{1 + d // 20}T10:{d:02d}:00",
        "day": f"2026-02-0{1 + d // 20}",
        "filesize": 1000 + d, "mtime": float(d),
    } for d in range(40)])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.resize(1300, 900)
    win.show()
    app.processEvents()
    win.activate("all")
    for _ in range(40):
        app.processEvents()
    yield win.page_grid
    win._quitting = True
    win.close()
    win.deleteLater()
    app.processEvents()


def _resets(page):
    """A counter of how many times the model was torn down."""
    box = {"n": 0}
    page.model.modelReset.connect(lambda: box.__setitem__("n", box["n"] + 1))
    return box


def test_a_refresh_that_changes_nothing_does_not_rebuild_the_model(page, app):
    page.refresh()
    app.processEvents()
    seen = _resets(page)
    for _ in range(5):
        page.refresh()
        app.processEvents()
    assert seen["n"] == 0, (
        f"{seen['n']} model rebuilds for five refreshes of an unchanged library")


def test_the_scroll_position_survives_an_index_pass(page, app):
    """This is what it costs the user: beginResetModel sends the view back to
    the top, and an index pass lands every fifteen seconds while VRChat runs."""
    page.refresh()
    app.processEvents()
    bar = page.view.verticalScrollBar()
    assert bar.maximum() > 100, "not enough content to scroll; nothing to lose"
    bar.setValue(bar.maximum() // 2)
    app.processEvents()
    where = bar.value()
    assert where > 0

    page.window().after_photos_changed()     # exactly what _on_index_done calls
    app.processEvents()
    assert bar.value() == where, (
        f"the grid jumped from {where} to {bar.value()} because an index pass "
        f"finished")


def test_a_library_that_really_changed_is_rebuilt(page, app):
    """The saving is only allowed where there is nothing to show."""
    page.refresh()
    app.processEvents()
    seen = _resets(page)
    page.db.upsert_photos([{
        "path": "/tmp/photos/VRChat_2026-03-09_11-00-00.000.png",
        "folder": "/tmp/photos", "filename": "VRChat_2026-03-09_11-00-00.000.png",
        "taken_at": "2026-03-09T11:00:00", "day": "2026-03-09",
        "filesize": 4242, "mtime": 99.0,
    }])
    page.refresh()
    app.processEvents()
    assert seen["n"] == 1, "a new photo did not reach the grid"
    assert any(p.id for p in page.model.photos()), "the model came back empty"


def test_a_field_changing_under_a_photo_is_noticed(page, app):
    """The stamp covers every column, not just the row count -- favouriting a
    photo changes nothing about the list's shape."""
    page.refresh()
    app.processEvents()
    photos = page.model.photos()
    assert photos, "no photos to favourite"
    seen = _resets(page)
    page.db.set_favorite([photos[0].id], True)
    page.refresh()
    app.processEvents()
    assert seen["n"] == 1, "a favourited photo did not reach the grid"


def test_switching_the_filter_still_rebuilds(page, app):
    """Same query object, different answer."""
    page.refresh()
    app.processEvents()
    seen = _resets(page)
    page.search.setText("nothing-matches-this")
    page._apply_search()
    app.processEvents()
    assert seen["n"] >= 1, "a search that empties the grid did not rebuild it"
    assert page.model.rowCount() <= 1, "the search did not actually filter"
    page.search.setText("")
    page._apply_search()
    app.processEvents()
    assert seen["n"] >= 2, "clearing the search did not bring the photos back"


def test_a_result_that_cannot_be_fingerprinted_is_always_rebuilt(page, app):
    """The stamp is a hash, and a hash needs hashable values. If a row ever
    carried something that will not hash, the honest answer is "I do not know",
    and not knowing must mean rebuild -- never "assume unchanged"."""
    from vrgallery import gridpage
    _rows_stamp = gridpage._rows_stamp

    assert _rows_stamp([]) is not None, "an empty library is perfectly knowable"
    assert _rows_stamp([(1, "a"), (2, "b")]) is not None
    assert _rows_stamp([(1, ["a list is not hashable"])]) is None

    page.refresh()
    app.processEvents()
    seen = _resets(page)
    # The rows themselves are left alone and the fingerprint is made to fail
    # instead: what is under test is what refresh() does with "I do not know",
    # not which column could produce it.
    real = gridpage._rows_stamp
    gridpage._rows_stamp = lambda rows: None
    try:
        # TWICE. Once proves nothing: the first unfingerprintable answer differs
        # from the hash already stored and would be rebuilt either way. It is
        # the second one -- "unknown" against a stored "unknown" -- that decides
        # whether not knowing means rebuild or means assume-unchanged.
        page.refresh()
        app.processEvents()
        page.refresh()
        app.processEvents()
    finally:
        gridpage._rows_stamp = real
    assert seen["n"] == 2, (
        f"{seen['n']} rebuilds for two results it could not fingerprint: "
        f"not knowing was taken for unchanged")
