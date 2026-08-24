import os
import sys

# tests run against the source tree, not an installed copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
