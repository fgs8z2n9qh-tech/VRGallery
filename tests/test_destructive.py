"""The paths that can lose a file.

The rule this app promises: photos are only ever read, and the two cleanup
actions move originals to the Recycle Bin after asking. Both bugs these tests
pin down shipped once and were caught in review, so they stay pinned.
"""
import os

import pytest

from vrchronicle import backup, export


def _photo(path, day, size):
    return {"path": str(path), "day": day, "filesize": size}


def test_same_basename_from_two_folders_both_survive(tmp_path):
    """VRChat names by timestamp, so two source folders collide constantly.
    Flattening them into one destination name silently destroys a backup."""
    a, b, dest = tmp_path / "A", tmp_path / "B", tmp_path / "dest"
    for d in (a, b, dest):
        d.mkdir()
    name = "VRChat_2026-08-21_12-00-00.000_1920x1080.png"
    (a / name).write_bytes(b"A" * 400)
    (b / name).write_bytes(b"B" * 800)
    rows = [_photo(a / name, "2026-08-21", 400), _photo(b / name, "2026-08-21", 800)]

    todo, already, _bytes = backup.plan(rows, str(dest))
    assert (len(todo), already) == (2, 0)
    copied, failed, _n, errors = backup.run(todo, str(dest))
    assert (copied, failed, errors) == (2, 0, [])

    got = sorted((dest / "2026-08").iterdir())
    assert len(got) == 2
    assert sorted(p.stat().st_size for p in got) == [400, 800]


def test_backup_is_idempotent(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    f = src / "shot.png"
    f.write_bytes(b"x" * 123)
    rows = [_photo(f, "2026-01-05", 123)]

    todo, _already, _b = backup.plan(rows, str(dest))
    backup.run(todo, str(dest))
    todo2, already2, _b2 = backup.plan(rows, str(dest))
    assert (todo2, already2) == ([], 1)


def test_backup_never_replaces_a_different_file_already_there(tmp_path):
    """Whatever put a file at the destination, it is not ours to overwrite."""
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    (dest / "2026-01").mkdir(parents=True)
    f = src / "shot.png"
    f.write_bytes(b"new" * 50)
    squatter = dest / "2026-01" / "shot.png"
    squatter.write_bytes(b"someone else's file")
    rows = [_photo(f, "2026-01-05", 150)]

    todo, _a, _b = backup.plan(rows, str(dest))
    backup.run(todo, str(dest))
    assert squatter.read_bytes() == b"someone else's file"
    assert len(list((dest / "2026-01").iterdir())) == 2


def test_backup_reports_a_failure_rather_than_claiming_success(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    todo = [(str(tmp_path / "missing.png"), str(dest / "2026-01" / "missing.png"), 10)]
    copied, failed, nbytes, errors = backup.run(todo, str(dest))
    assert (copied, failed, nbytes) == (0, 1, 0)
    assert errors


def test_xmp_sidecar_keeps_a_foreign_sidecar(tmp_path):
    """A Lightroom .xmp holds crops, exposure and ratings. Losing it is silent
    and unrecoverable, so it gets copied aside before we write ours."""
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"png")
    side = tmp_path / "shot.xmp"
    side.write_text('<x:xmpmeta x:xmptk="Adobe Lightroom">EDITS</x:xmpmeta>',
                    encoding="utf-8")

    export.xmp_sidecar(str(photo), "World", "2026-01-02T10:00:00", ["Someone"])

    baks = [p for p in tmp_path.iterdir() if ".xmp.bak-" in p.name]
    assert len(baks) == 1
    assert "EDITS" in baks[0].read_text(encoding="utf-8")
    assert "VRChronicle" in side.read_text(encoding="utf-8")


def test_xmp_sidecar_refreshes_its_own_without_piling_up_backups(tmp_path):
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"png")
    for _ in range(3):
        export.xmp_sidecar(str(photo), "World", "2026-01-02T10:00:00", ["Someone"])
    assert not [p for p in tmp_path.iterdir() if ".xmp.bak-" in p.name]


def test_xmp_sidecar_can_skip_instead_of_touching_a_foreign_file(tmp_path):
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"png")
    side = tmp_path / "shot.xmp"
    side.write_text("<x:xmpmeta>OTHER</x:xmpmeta>", encoding="utf-8")

    assert export.xmp_sidecar(str(photo), "W", "", [], on_existing="skip") is None
    assert side.read_text(encoding="utf-8") == "<x:xmpmeta>OTHER</x:xmpmeta>"


def test_xmp_escapes_names_that_would_break_the_xml(tmp_path):
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"png")
    export.xmp_sidecar(str(photo), 'World & <friends>', "2026-01-02T10:00:00",
                       ['A "quoted" name'])
    text = (tmp_path / "shot.xmp").read_text(encoding="utf-8")
    assert "&amp;" in text and "&lt;friends&gt;" in text
    assert "<friends>" not in text

    import xml.etree.ElementTree as ET
    ET.fromstring(text[text.index("<x:xmpmeta"):text.index("</x:xmpmeta>") + 12])
