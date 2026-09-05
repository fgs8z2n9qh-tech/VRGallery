"""What the workers are still saying after the window has closed.

closeEvent drains both thread pools before closing the database, which stops
any NEW signal -- but a signal a worker emitted on its way out is already a
queued call sitting in the event queue, and it is delivered after closeEvent
returns. Its slot reads the database. `sqlite3.ProgrammingError: Cannot operate
on a closed database`, raised inside a Qt slot, has no caller to catch it:
PySide prints it and, when stdout is being captured, the process goes down
without printing anything at all. That is how this was found -- a test suite
that stopped mid-run, exit code 127, no message.

Disconnecting the bridge on the way out does NOT help: Qt delivers a call that
was already posted. The check belongs where the database is read.
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
def closed_window(app, tmp_path):
    """A window that has been through closeEvent, database and all."""
    paths.set_appdir(str(tmp_path / "lib"))
    paths.ensure_dirs()
    from vrgallery.config import Config
    from vrgallery.db import Database
    from vrgallery.mainwindow import MainWindow

    cfg = Config()
    cfg.set("onboarded", True, save=False)
    cfg.set("check_updates", False, save=False)
    cfg.set("api_enabled", False, save=False)
    win = MainWindow(app, cfg, Database(), auto_index=False)
    win.show()
    app.processEvents()
    win._quitting = True
    win.close()
    app.processEvents()
    yield win
    # A closed window left for the garbage collector is a C++ object destroyed
    # at an arbitrary point in a LATER test, which is how a suite acquires an
    # access violation that moves around when you add a file.
    win.deleteLater()
    app.processEvents()


def test_the_database_knows_it_has_been_closed(closed_window):
    """Everything else here rests on this one flag."""
    assert closed_window.db.closed is True


def test_a_fresh_database_does_not_claim_to_be_closed(app, tmp_path):
    """The flag is a class attribute so it exists before the first close; if it
    were only set in close(), every slot would raise AttributeError instead."""
    paths.set_appdir(str(tmp_path / "lib2"))
    paths.ensure_dirs()
    from vrgallery.db import Database
    db = Database()
    assert db.closed is False
    db.close()
    assert db.closed is True


def test_a_late_progress_signal_does_not_touch_the_closed_database(closed_window, app):
    """The deep scan reports progress from a worker thread; the last one lands
    after the close.

    Called DIRECTLY, and that is the whole point of the test. Emitting the
    signal instead proves nothing: an exception raised inside a Qt slot never
    reaches the caller, so PySide prints it and the test sails past -- which is
    exactly why this went unnoticed until a captured run died with no message.
    """
    closed_window._on_deep_progress(3, 10)
    closed_window._on_deep_progress(10, 10)      # the done branch, which is the
                                                 # one that reads counts()
    closed_window.bridge.deep_progress.emit(10, 10)   # and through the wire too
    app.processEvents()


def test_a_late_index_result_does_not_touch_the_closed_database(closed_window, app):
    """Same for the index pass, which reads counts() and unscanned()."""
    stats = {"new": 2, "auth": [], "total": 5, "bytes": 100, "favorites": 0}
    closed_window._on_index_done(stats)
    closed_window.bridge.index_done.emit(stats)
    app.processEvents()


def test_the_window_still_works_normally_before_it_is_closed(app, tmp_path):
    """The guard must not swallow the signals that arrive while the app is
    running -- it is a shutdown check, not a mute button."""
    paths.set_appdir(str(tmp_path / "lib3"))
    paths.ensure_dirs()
    from vrgallery.config import Config
    from vrgallery.db import Database
    from vrgallery.mainwindow import MainWindow

    cfg = Config()
    cfg.set("onboarded", True, save=False)
    cfg.set("check_updates", False, save=False)
    cfg.set("api_enabled", False, save=False)
    win = MainWindow(app, cfg, Database(), auto_index=False)
    win.show()
    app.processEvents()
    try:
        win.lab_status.setText("")
        win.bridge.deep_progress.emit(1, 4)
        app.processEvents()
        assert win.lab_status.text(), "a live progress signal was ignored"
    finally:
        win._quitting = True
        win.close()
        win.deleteLater()
        app.processEvents()
