"""Every page must build and refresh against a library, headless.

A shadowed import or a missing column only shows up when a page is actually
constructed, and that used to mean noticing it in a screenshot.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from vrchronicle import paths


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
    for mode in ("black", "burst", "dupes", "large"):
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

    # "All time" groups the whole library by year, not by month
    assert page.selected_year() == ""
    assert page.card_months._title.text() == "PHOTOS PER YEAR"

    before = page.lab_sub.text()
    page.cb_year.setCurrentIndex(1)                  # pick the only real year
    assert page.card_months._title.text() == "PHOTOS PER MONTH"
    assert page.selected_year() == page.cb_year.currentText()
    assert page.lab_sub.text() != before, "picking a year changed nothing"
    assert page.lab_sub.text().startswith(page.selected_year())
    # and the poster button names the year it would build
    assert page.btn_year.text() == f"{page.poster_year()} in review"


def test_filters_apply_without_error(window):
    page = window.page_grid
    window.activate("all")
    page.btn_filter.setChecked(True)
    page._apply_filters()
    page._clear_filters()
