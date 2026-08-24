"""Keeping the account name out of anything shown on screen."""
import os

from vrgallery import paths


def test_a_path_inside_home_is_abbreviated():
    home = os.path.normpath(os.path.expanduser("~"))
    got = paths.pretty(os.path.join(home, "Pictures", "VRChat"))
    assert got == os.path.join("%USERPROFILE%", "Pictures", "VRChat")
    assert home not in got


def test_home_itself_has_no_trailing_separator():
    assert paths.pretty(os.path.expanduser("~")) == "%USERPROFILE%"


def test_a_sibling_that_merely_shares_the_prefix_is_left_alone():
    """C:\\Users\\Erikson is not inside C:\\Users\\Erik."""
    home = os.path.normpath(os.path.expanduser("~"))
    sibling = home + "son"
    assert paths.pretty(sibling) == sibling


def test_an_unrelated_path_is_returned_unchanged():
    assert paths.pretty("D:\\Photos") == os.path.normpath("D:\\Photos")
    assert paths.pretty("") == ""


# ---------------------------------------------------- renaming the whole app

def test_a_library_from_the_old_name_is_adopted(tmp_path, monkeypatch):
    """The rename must not look like a lost library.

    It moves the folder only when there is nothing under the new name, and the
    WAL and SHM files have to travel with the database or sqlite calls it
    damaged.
    """
    import importlib
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    importlib.reload(paths)
    assert paths.APPDIR == os.path.join(str(tmp_path), "VRGallery")

    old = tmp_path / "VRChronicle"
    old.mkdir()
    (old / "vrchronicle.db").write_text("library", encoding="utf-8")
    (old / "vrchronicle.db-wal").write_text("wal", encoding="utf-8")
    (old / "config.json").write_text("{}", encoding="utf-8")
    (old / "thumbs").mkdir()
    (old / "thumbs" / "1.jpg").write_text("t", encoding="utf-8")

    assert paths.migrate_legacy_appdir() is True
    new = tmp_path / "VRGallery"
    assert (new / "vrgallery.db").read_text(encoding="utf-8") == "library"
    assert (new / "vrgallery.db-wal").read_text(encoding="utf-8") == "wal"
    assert (new / "thumbs" / "1.jpg").exists()
    assert (new / "config.json").exists()
    assert not old.exists()

    assert paths.migrate_legacy_appdir() is False       # nothing left to do
    importlib.reload(paths)
    paths.set_appdir(str(tmp_path / "after"))   # never the real library


def test_an_existing_new_library_is_never_overwritten(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    importlib.reload(paths)

    (tmp_path / "VRChronicle").mkdir()
    (tmp_path / "VRChronicle" / "vrchronicle.db").write_text("old", encoding="utf-8")
    new = tmp_path / "VRGallery"
    new.mkdir()
    (new / "vrgallery.db").write_text("mine", encoding="utf-8")

    assert paths.migrate_legacy_appdir() is False
    assert (new / "vrgallery.db").read_text(encoding="utf-8") == "mine"
    assert (tmp_path / "VRChronicle").exists(), "the old folder is left alone"
    importlib.reload(paths)
    paths.set_appdir(str(tmp_path / "after"))


def test_a_copied_library_adopts_its_old_database(tmp_path):
    """--data-dir points at a copy; the folder move never touches those."""
    lib = tmp_path / "copy"
    lib.mkdir()
    (lib / "vrchronicle.db").write_text("copied", encoding="utf-8")
    (lib / "vrchronicle.db-wal").write_text("wal", encoding="utf-8")
    paths.set_appdir(str(lib))
    paths.ensure_dirs()
    assert (lib / "vrgallery.db").read_text(encoding="utf-8") == "copied"
    assert (lib / "vrgallery.db-wal").exists()
    assert not (lib / "vrchronicle.db").exists()
    assert paths.adopt_legacy_db() is False        # nothing left to adopt


def test_adoption_never_replaces_a_database_that_is_already_there(tmp_path):
    lib = tmp_path / "both"
    lib.mkdir()
    (lib / "vrchronicle.db").write_text("old", encoding="utf-8")
    (lib / "vrgallery.db").write_text("current", encoding="utf-8")
    paths.set_appdir(str(lib))
    assert paths.adopt_legacy_db() is False
    assert (lib / "vrgallery.db").read_text(encoding="utf-8") == "current"
    assert (lib / "vrchronicle.db").exists()
