import os
import sys

# tests run against the source tree, not an installed copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _library_elsewhere():
    """Point the app at a throwaway folder for the whole run.

    Database() and Config() both call paths.ensure_dirs(), so a test that
    forgets to redirect them creates -- and writes into -- the real library
    under %LOCALAPPDATA%. This used to be a comment claiming it never happened;
    now it is enforced.
    """
    from vrgallery import paths
    holder = tempfile.mkdtemp(prefix="vrgallery-tests-")
    paths.set_appdir(os.path.join(holder, "library"))
    yield
    shutil.rmtree(holder, ignore_errors=True)


@pytest.fixture(autouse=True)
def _drain_dead_widgets():
    """Collect Python's dead widgets between tests, not during the next one.

    PySide deletes the C++ half of a QWidget when the last Python reference to
    it goes -- and Python decides WHEN that is. A widget dropped at the end of
    one test can therefore be destroyed part-way through the next one's show(),
    reentering Qt while it lays a window out. The result is an access violation
    at a line that has nothing to do with the cause, in a test that passes on
    its own, and that moves somewhere else the moment a file is added to the
    suite. That is exactly how it presented: adding two test files turned
    test_glass's shadow test into a segfault at page.show().

    So the collection happens here, where nothing is being shown, and the
    deleteLater events it produces are drained before the next test starts.
    """
    yield
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents()          # whatever already asked for deleteLater
    gc.collect()                     # drop the C++ halves, here and not later
    if app is not None:
        app.processEvents()          # and let Qt finish the job
