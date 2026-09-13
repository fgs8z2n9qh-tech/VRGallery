"""Naming a face box from the ones already named.

NOTE ON THIS FILE'S NAME. It was test_facesig.py, which sorts before
test_glass.py, and that turned out to matter: any test file that builds a
MainWindow before test_glass runs kills the suite with an access violation
inside Glass.sample. That is NOT this feature's doing -- it reproduces on the
commit before any of this existed, with test_narrow, test_resize or
test_shutdown in front of test_glass, and it has only ever been avoided by
those files happening to sort after it. It does not reproduce outside pytest.
Until somebody finds it, this file is named so that it lands on the lucky side
of that line, rather than being the one that makes a known landmine go off.

The whole feature rests on four properties of the signature, and each of them is
a thing that would quietly ruin it if it stopped holding:

  * it does not depend on the photo's resolution, because a tag is stored as
    fractions and the same person is shot at 1080p and at 4K
  * it does not depend on the brightness, because the same avatar walks from a
    neon club into a dark bedroom
  * it separates two avatars by more than it separates two shots of one
  * it says so when it is not sure, because a wrong name placed silently is
    worse than no name at all

Measured on the app author's own 347 hand-placed tags, leave-one-out: 81.7%
correct among the people the logs put in the instance, never matching a tag from
the same evening; 94% when it only speaks at a margin of 1.20. See facesig.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter

from vrgallery import facesig, paths


@pytest.fixture(scope="module", autouse=True)
def _app():
    """A QApplication before any QImage or QPainter exists.

    Every other file in this suite asks for one; these tests looked like they
    did not need it, being nothing but pixels. They do: Qt objects built before
    the application is constructed take the process down later, in whichever
    test happens to be running when Python collects them.
    """
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _photo(w, h, boxes, bright=1.0, seed=0):
    """An image with coloured rectangles standing in for avatars.

    boxes: [(x, y, w, h, (r, g, b))] in fractions. A little per-cell variation
    is painted in so the signature has something to work with besides one flat
    colour -- a real crop is never flat.
    """
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(14, 15, 20))
    p = QPainter(img)
    for i, (bx, by, bw, bh, rgb) in enumerate(boxes):
        x0, y0 = int(bx * w), int(by * h)
        cw, ch = max(8, int(bw * w)), max(8, int(bh * h))
        for row in range(6):
            for col in range(6):
                k = ((row * 7 + col * 5 + i * 3 + seed) % 5) - 2
                c = QColor(*[max(0, min(255, int(v * bright) + k * 9)) for v in rgb])
                p.fillRect(x0 + col * cw // 6, y0 + row * ch // 6,
                           cw // 6 + 1, ch // 6 + 1, c)
    p.end()
    return img


TEAL = (40, 180, 170)
ORANGE = (220, 120, 40)
PURPLE = (120, 60, 200)
BOX = (0.30, 0.25, 0.22, 0.30)


# ------------------------------------------------------------ the signature

def test_a_signature_is_the_size_it_says_it_is():
    img = _photo(900, 600, [BOX + (TEAL,)])
    sig = facesig.signature(img, *BOX)
    assert sig is not None and len(sig) == facesig.SIG_LEN
    assert isinstance(sig, bytes)


def test_the_same_picture_at_two_resolutions_gives_the_same_signature():
    """A tag is fractions of the image, and the library holds 1080p shots next
    to 4K ones. If the signature moved with the resolution, every comparison
    across them would be noise."""
    small = facesig.signature(_photo(640, 360, [BOX + (TEAL,)]), *BOX)
    large = facesig.signature(_photo(2560, 1440, [BOX + (TEAL,)]), *BOX)
    far = facesig.signature(_photo(640, 360, [BOX + (ORANGE,)]), *BOX)
    d_same = facesig.distance(small, large)
    d_other = facesig.distance(small, far)
    assert d_same < d_other / 3, (
        f"the same avatar at two sizes is {d_same} apart, a different one only "
        f"{d_other}")


def test_turning_the_lights_down_does_not_change_who_it_is():
    """The same avatar in a neon club and in a dark bedroom."""
    lit = facesig.signature(_photo(900, 600, [BOX + (TEAL,)], bright=1.0), *BOX)
    dim = facesig.signature(_photo(900, 600, [BOX + (TEAL,)], bright=0.45), *BOX)
    other = facesig.signature(_photo(900, 600, [BOX + (ORANGE,)]), *BOX)
    assert facesig.distance(lit, dim) < facesig.distance(lit, other) / 3


def test_two_avatars_are_further_apart_than_two_shots_of_one():
    a1 = facesig.signature(_photo(900, 600, [BOX + (TEAL,)], seed=0), *BOX)
    a2 = facesig.signature(_photo(900, 600, [BOX + (TEAL,)], seed=2), *BOX)
    b = facesig.signature(_photo(900, 600, [BOX + (PURPLE,)], seed=0), *BOX)
    assert facesig.distance(a1, a2) < facesig.distance(a1, b)


def test_a_box_with_nothing_in_it_produces_nothing():
    """Better no signature than one made of four pixels of black."""
    img = QImage(900, 600, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    assert facesig.signature(img, 0.3, 0.3, 0.2, 0.2) is None       # pure black
    lit = _photo(900, 600, [BOX + (TEAL,)])
    assert facesig.signature(lit, 0.3, 0.3, 0.0, 0.0) is not None   # clamped to 4px
    assert facesig.signature(None, 0.3, 0.3, 0.2, 0.2) is None
    assert facesig.signature(QImage(), 0.3, 0.3, 0.2, 0.2) is None


def test_a_box_off_the_edge_of_the_image_is_refused_not_crashed():
    img = _photo(900, 600, [BOX + (TEAL,)])
    assert facesig.signature(img, 1.4, 1.4, 0.2, 0.2) is None


# -------------------------------------------------------------- suggesting

def _sig(rgb, seed=0):
    return facesig.signature(_photo(900, 600, [BOX + (rgb,)], seed=seed), *BOX)


def test_it_picks_the_nearer_of_two_people():
    known = {"Teal": [_sig(TEAL)], "Orange": [_sig(ORANGE)]}
    name, sure = facesig.suggest(_sig(TEAL, seed=3), known)
    assert name == "Teal" and sure


def test_it_is_not_sure_when_two_names_look_the_same():
    """Two people in the same avatar, or one who lent theirs out. Guessing on a
    coin flip and pre-selecting it is worse than staying quiet."""
    known = {"One": [_sig(TEAL, seed=1)], "Two": [_sig(TEAL, seed=1)]}
    _name, sure = facesig.suggest(_sig(TEAL, seed=1), known)
    assert not sure


def test_one_candidate_is_offered_even_though_nothing_confirms_it():
    """Measured at 91% on the real library: the log usually names everyone who
    was there, so the only candidate is usually the answer."""
    name, sure = facesig.suggest(_sig(TEAL), {"Only": [_sig(ORANGE)]})
    assert name == "Only" and sure


def test_nothing_to_go_on_means_no_guess():
    assert facesig.suggest(None, {"A": [_sig(TEAL)]}) == (None, False)
    assert facesig.suggest(_sig(TEAL), {}) == (None, False)
    assert facesig.suggest(_sig(TEAL), {"A": []}) == (None, False)
    assert facesig.suggest(_sig(TEAL), {"A": [b"too short"]}) == (None, False)


def test_the_margin_is_what_decides_whether_it_speaks():
    """A higher bar must make it quieter, never louder -- that is the knob the
    measured 71%-of-boxes-at-94% sits on."""
    known = {"Teal": [_sig(TEAL)], "Purple": [_sig(PURPLE)]}
    probe = _sig(TEAL, seed=4)
    _n, loose = facesig.suggest(probe, known, margin=1.0)
    _n, strict = facesig.suggest(probe, known, margin=99.0)
    assert loose and not strict


# -------------------------------------------------------------- the storage

@pytest.fixture()
def db(tmp_path):
    paths.set_appdir(str(tmp_path / "lib"))
    paths.ensure_dirs()
    from vrgallery.db import Database
    d = Database()
    d.upsert_photos([{
        "path": str(tmp_path / f"p{i}.png"), "folder": str(tmp_path),
        "filename": f"p{i}.png", "taken_at": f"2026-02-0{i}T10:00:00",
        "day": f"2026-02-0{i}", "filesize": 10, "mtime": float(i),
    } for i in range(1, 4)])
    yield d
    d.close()


def _ids(db):
    from vrgallery.db import PhotoFilter
    return [r["id"] for r in db.query_photos(PhotoFilter())]


def test_a_signature_is_stored_with_the_tag_and_comes_back(db):
    pid = _ids(db)[0]
    sig = _sig(TEAL)
    db.set_photo_tag(pid, "Teal", 0.3, 0.25, 0.22, 0.30, sig=sig)
    got = db.tag_sigs_for(["Teal"])
    assert got["Teal"] == [sig]


def test_moving_a_box_does_not_leave_the_old_signature_behind(db):
    """The box no longer covers what the signature describes."""
    pid = _ids(db)[0]
    db.set_photo_tag(pid, "Teal", 0.3, 0.25, 0.22, 0.30, sig=_sig(TEAL))
    db.set_photo_tag(pid, "Teal", 0.7, 0.6, 0.10, 0.10)        # dragged, no sig
    assert db.tag_sigs_for(["Teal"]) == {}
    assert [t[0] for t in db.tags_needing_sig()] == [pid]


def test_a_tag_with_no_signature_is_queued_and_can_be_filled_in(db):
    pid = _ids(db)[0]
    db.set_photo_tag(pid, "Teal", 0.3, 0.25, 0.22, 0.30)
    todo = db.tags_needing_sig()
    assert len(todo) == 1
    assert todo[0][0] == pid and todo[0][1] == "Teal"
    assert todo[0][2:6] == (0.3, 0.25, 0.22, 0.30)
    db.set_tag_sigs([(_sig(TEAL), pid, "Teal")])
    assert db.tags_needing_sig() == []
    assert "Teal" in db.tag_sigs_for(["Teal"])


def test_a_box_that_cannot_be_fingerprinted_is_not_retried_for_ever(db):
    """Stored empty rather than left NULL, or every index pass decodes that
    photo again to fail in exactly the same way."""
    pid = _ids(db)[0]
    db.set_photo_tag(pid, "Teal", 0.3, 0.25, 0.22, 0.30)
    db.set_tag_sigs([(b"", pid, "Teal")])
    assert db.tags_needing_sig() == [], "it will be decoded again next pass"
    assert db.tag_sigs_for(["Teal"]) == {}, "an empty signature was offered as one"


def test_only_the_names_asked_about_come_back(db):
    """The narrowing to who the logs put in the instance is most of why the
    guess is any good; a query that ignored it would undo that."""
    a, b, _c = _ids(db)
    db.set_photo_tag(a, "Teal", *BOX, sig=_sig(TEAL))
    db.set_photo_tag(b, "Orange", *BOX, sig=_sig(ORANGE))
    assert set(db.tag_sigs_for(["Teal"])) == {"Teal"}
    assert set(db.tag_sigs_for(["Teal", "Orange"])) == {"Teal", "Orange"}
    assert db.tag_sigs_for([]) == {}
    assert db.tag_sigs_for([None, ""]) == {}


def test_several_boxes_of_one_person_all_count(db):
    """Somebody photographed twenty times should be twenty chances to match,
    not one."""
    a, b, c = _ids(db)
    for pid, seed in ((a, 0), (b, 1), (c, 2)):
        db.set_photo_tag(pid, "Teal", *BOX, sig=_sig(TEAL, seed=seed))
    assert len(db.tag_sigs_for(["Teal"])["Teal"]) == 3


# ------------------------------------------------- the lightbox's own wiring

@pytest.fixture()
def window(tmp_path):
    """A real window over one real PNG on disk."""
    from PySide6.QtWidgets import QApplication
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])

    shot = tmp_path / "VRChat_2026-02-01_10-00-00.000.png"
    _photo(1200, 800, [BOX + (TEAL,)]).save(str(shot))
    assert shot.exists()

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
        "path": str(shot), "folder": str(tmp_path), "filename": shot.name,
        "taken_at": "2026-02-01T10:00:00", "day": "2026-02-01",
        "filesize": shot.stat().st_size, "mtime": 1.0,
    }])
    win = MainWindow(app, cfg, db, auto_index=False)
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    win.activate("all")
    for _ in range(30):
        app.processEvents()
    yield win, app
    # The lightbox is a window of its own and loads on a thread pool. Left open,
    # or left with a job still running, its C++ half is destroyed at whatever
    # later moment Python collects it -- which is somewhere inside the NEXT
    # test, and lands as an access violation with nobody's name on it.
    from PySide6.QtCore import QThreadPool
    win.lightbox.close_box()
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(4000)
    app.processEvents()
    win._quitting = True
    win.close()
    win.deleteLater()
    app.processEvents()


def _on_screen(win, app, secs=4.0):
    """Spin until the lightbox has actually painted the photo.

    The full-size load runs on a thread pool, so a fixed number of
    processEvents() calls is a race: they can all run before the worker has
    finished, and then there is no image to put a box on.
    """
    import time
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        app.processEvents()
        if win.lightbox.viewer._image_rect() is not None:
            return True
    return False


def _only_photo(win):
    photos = win.page_grid.model.photos()
    assert photos, "the fixture's photo never reached the grid"
    return photos[0]


def test_the_lightbox_can_fingerprint_a_box_it_has_not_got_cached(window):
    """Nothing has been opened, so there is no pixmap to take it off -- it has
    to fall back to reading the file."""
    win, _app = window
    it = _only_photo(win)
    assert not win.lightbox._cache, "this test wanted a cold cache"
    sig = win.lightbox._box_signature(it, *BOX)
    assert sig is not None and len(sig) == facesig.SIG_LEN


def test_the_two_ways_of_fingerprinting_a_box_agree(window):
    """One comes off the pixmap already on screen, the other off the file. If
    they disagreed, a signature stored while browsing would not match one built
    by the index pass, and every comparison across them would be noise."""
    win, app = window
    it = _only_photo(win)
    from_file = win.lightbox._box_signature(it, *BOX)

    win.open_lightbox(win.page_grid, [it], 0)
    assert _on_screen(win, app), "the lightbox never painted the picture"
    assert win.lightbox._cache, "the lightbox never cached the picture"
    from_screen = win.lightbox._box_signature(it, *BOX)
    win.lightbox.close_box()
    app.processEvents()

    apart = facesig.distance(from_file, from_screen)
    assert apart <= facesig.SIG_LEN // 8, (
        f"the two paths are {apart} apart over {facesig.SIG_LEN} bytes")


def test_the_lightbox_names_a_box_from_a_tag_it_has_seen(window):
    win, _app = window
    it = _only_photo(win)
    sig = win.lightbox._box_signature(it, *BOX)
    win.db.set_photo_tag(it.id + 999, "Teal", *BOX, sig=sig)      # some other photo
    win.db.set_photo_tag(it.id + 998, "Orange", *BOX, sig=_sig(ORANGE))
    assert win.lightbox._guess_name(sig, ["Teal", "Orange"]) == "Teal"


def test_the_lightbox_keeps_quiet_when_it_has_nothing(window):
    win, _app = window
    it = _only_photo(win)
    sig = win.lightbox._box_signature(it, *BOX)
    assert win.lightbox._guess_name(sig, []) is None
    assert win.lightbox._guess_name(None, ["Teal"]) is None
    assert win.lightbox._guess_name(sig, ["NobodyTaggedYet"]) is None


def test_a_tag_placed_through_the_window_stores_its_signature(window):
    """act_tag is the one door every tag comes through."""
    win, _app = window
    it = _only_photo(win)
    sig = win.lightbox._box_signature(it, *BOX)
    win.act_tag(it.id, "Teal", *BOX, sig=sig)
    assert win.db.tag_sigs_for(["Teal"]).get("Teal") == [sig]


def test_the_menu_comes_up_with_the_guess_already_picked(window):
    """The whole user-visible half of it: you let go of the mouse and the name
    is already the bold one, one Enter away.

    The menu is built by _who_menu so it can be looked at without being opened
    -- QMenu.exec blocks on a real popup, and a test that fakes that away is
    testing the fake.
    """
    win, _app = window
    menu = win.lightbox._who_menu(["Orange", "Teal"], ["Purple"], "Teal")
    names = [a.text() for a in menu.actions() if a.text()]
    assert names[0] == "Teal", f"the guess was not moved to the top: {names}"
    assert menu.defaultAction() is not None
    assert menu.defaultAction().text() == "Teal", "the guess is not the bold one"
    assert set(names) == {"Teal", "Orange", "Purple"}, "a name went missing"


def test_the_menu_is_plain_when_there_is_no_guess(window):
    """Nothing bold, nothing reordered -- exactly the menu that was there
    before any of this existed."""
    win, _app = window
    menu = win.lightbox._who_menu(["Orange", "Teal"], ["Purple"], None)
    assert menu.defaultAction() is None
    assert [a.text() for a in menu.actions() if a.text()] == ["Orange", "Teal", "Purple"]


def test_a_guess_from_the_recent_list_is_promoted_too(window):
    """Nine per cent of the tagged photos have no log data at all, and there the
    candidates come from who has been tagged lately instead."""
    win, _app = window
    menu = win.lightbox._who_menu([], ["Purple", "Teal"], "Teal")
    names = [a.text() for a in menu.actions() if a.text()]
    assert names[0] == "Teal" and menu.defaultAction().text() == "Teal"
