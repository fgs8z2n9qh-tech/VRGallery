"""Swapping the whole ground, not just the accent.

The colours are the easy half: style.PAL is mutated in place, so every one of
the hundred-odd `style.PAL[...]` reads in the app follows for free. The half
that can go wrong is everything that BAKED a colour into a pixmap and kept it --
rendered day headers, the rounded tile cache, the timeline rail's scale, the
glass panels, which hold a whole composited surface. Miss one and the window
comes back wearing two colour schemes at once.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from vrgallery import paths, style


@pytest.fixture(scope="module", autouse=True)
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore():
    """Every test here changes a module global; put it back."""
    before = dict(style.PAL)
    yield
    style.PAL.clear()
    style.PAL.update(before)


# ------------------------------------------------------------- the palette

def test_there_is_more_than_one_ground_and_the_default_is_the_old_one():
    assert "midnight" in style.PALETTES and "ember" in style.PALETTES
    assert style.DEFAULT_PALETTE == "midnight"
    assert style.PALETTES["midnight"]["bg"] == "#0d0f15", (
        "the default ground is not the colour the app has always been")


def test_applying_a_palette_changes_the_dict_everyone_already_holds():
    """Rebinding style.PAL would leave every module that did `from . import
    style` reading the old one. It is updated in place instead."""
    held = style.PAL
    style.apply_palette("ember")
    assert held is style.PAL, "PAL was rebound; half the app would not follow"
    assert held["bg"] == style.PALETTES["ember"]["bg"]
    assert held["text"] == style.PALETTES["ember"]["text"]


def test_it_comes_back():
    ground = style.PAL["bg"]
    style.apply_palette("ember")
    assert style.PAL["bg"] != ground
    style.apply_palette("midnight")
    assert style.PAL["bg"] == ground


def test_a_name_nobody_recognises_falls_back_rather_than_half_applying():
    style.apply_palette("ember")
    assert style.apply_palette("chartreuse") == "midnight"
    assert style.PAL["bg"] == style.PALETTES["midnight"]["bg"]


def test_a_palette_carries_no_label_or_swatch_into_the_colours():
    """label and swatch are for the settings page; a stray one in PAL would be
    handed to QColor the first time something looked up a missing key."""
    style.apply_palette("ember")
    assert "label" not in style.PAL and "swatch" not in style.PAL


def test_every_palette_defines_every_colour_the_other_does():
    """A key present in one and missing from the other does not reset on a
    switch -- it keeps the value from whichever ground was in force before."""
    keys = {k: set(p) - {"label", "swatch"} for k, p in style.PALETTES.items()}
    first = next(iter(keys.values()))
    for name, ks in keys.items():
        assert ks == first, f"{name} does not define the same colours as the rest"


def test_the_stylesheet_is_built_from_whatever_is_in_force():
    style.apply_palette("ember")
    qss = style.build_qss("vrblue")
    assert style.PALETTES["ember"]["bg"] in qss
    assert style.PALETTES["midnight"]["sidebar"] not in qss


# ---------------------------------------------------- and the baked pixmaps

@pytest.fixture()
def window(app, tmp_path):
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
        "path": str(tmp_path / f"p{i}.png"), "folder": str(tmp_path),
        "filename": f"p{i}.png", "taken_at": f"2026-02-0{1 + i // 5}T10:0{i}:00",
        "day": f"2026-02-0{1 + i // 5}", "filesize": 10, "mtime": float(i),
    } for i in range(10)])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    win.activate("all")
    for _ in range(40):
        app.processEvents()
    yield win
    win._quitting = True
    win.close()
    win.deleteLater()
    app.processEvents()


def _chip_colour(pm):
    """The count chip's fill, sampled out of a rendered day header."""
    from PySide6.QtGui import QColor
    img = pm.toImage()
    from collections import Counter
    right = Counter(img.pixel(x, y) & 0xFFFFFF
                    for x in range(img.width() - 40, img.width() - 8)
                    for y in range(6, img.height() - 8))
    return right.most_common(1)[0][0]


def test_a_header_drawn_in_the_old_colours_does_not_survive_the_switch(window, app):
    """A day header is rendered once and blitted for ever after.

    Not "the cache is empty": clearing it is only the mechanism, and the repaint
    that follows the switch fills it straight back up. What has to be true is
    that what comes back is drawn in the NEW ground.
    """
    from PySide6.QtGui import QColor
    d = window.page_grid.delegate
    was = _chip_colour(d._header_pixmap("2026-02-01", 4, 600, 38))
    assert was == QColor(style.PAL["surface2"]).rgb() & 0xFFFFFF, (
        "the chip is not the colour this test thinks it is")

    window.set_palette("ember")
    app.processEvents()
    now = _chip_colour(d._header_pixmap("2026-02-01", 4, 600, 38))
    assert now == QColor(style.PALETTES["ember"]["surface2"]).rgb() & 0xFFFFFF, (
        f"the header came back #{now:06x}: it was blitted from the old theme")


def test_switching_drops_the_rounded_tile_cache(window, app):
    d = window.page_grid.delegate
    d._tiles[("x", 1, 1, 1.0, 6)] = object()
    window.set_palette("ember")
    app.processEvents()
    assert not d._tiles, "tiles drawn on the old surface colour survived"


def test_switching_drops_the_timeline_rail_scale(window, app):
    window.page_grid.rail._scale = ("key", object())
    window.set_palette("ember")
    app.processEvents()
    assert window.page_grid.rail._scale is None


def test_the_choice_is_remembered(window, app):
    window.set_palette("ember")
    assert window.cfg.get("palette") == "ember"
    window.set_palette("midnight")
    assert window.cfg.get("palette") == "midnight"


def test_the_accent_is_not_disturbed_by_a_change_of_ground(window, app):
    """They are two settings, and picking a warm ground must not silently
    repaint every blue control."""
    before = window.cfg.get("accent")
    window.set_palette("ember")
    assert window.cfg.get("accent") == before
