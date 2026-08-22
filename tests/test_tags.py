"""People tagged in the frame: boxes, not points, and stable across zoom."""
import pytest

from vrchronicle.db import Database


def test_a_tag_stores_a_box(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.set_photo_tag(1, "Nova", 0.20, 0.30, 0.10, 0.18, "2026-01-01")
    assert db.photo_tags(1) == [("Nova", 0.20, 0.30, 0.10, 0.18)]
    db.close()


def test_tagging_the_same_person_moves_the_box(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.set_photo_tag(1, "Nova", 0.2, 0.3, 0.1, 0.1)
    db.set_photo_tag(1, "Nova", 0.6, 0.7, 0.2, 0.2)
    assert db.photo_tags(1) == [("Nova", 0.6, 0.7, 0.2, 0.2)]
    db.close()


def test_two_people_on_one_photo_are_independent(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.set_photo_tag(1, "Nova", 0.1, 0.1, 0.1, 0.1)
    db.set_photo_tag(1, "Pixel", 0.5, 0.5, 0.1, 0.1)
    assert [t[0] for t in db.photo_tags(1)] == ["Nova", "Pixel"]
    db.remove_photo_tag(1, "Nova")
    assert [t[0] for t in db.photo_tags(1)] == ["Pixel"]
    db.close()


def test_legacy_point_tags_still_load(tmp_path):
    """Tags written before boxes existed have w/h of 0 and must not break."""
    db = Database(str(tmp_path / "t.db"))
    db._conn.execute("INSERT INTO photo_tags(photo_id, name, x, y) VALUES(1,'Old',.4,.5)")
    db._conn.commit()
    assert db.photo_tags(1) == [("Old", 0.4, 0.5, 0.0, 0.0)]
    db.close()


def test_tags_for_photos_groups_by_photo_and_carries_the_box(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.set_photo_tag(1, "Nova", 0.1, 0.1, 0.3, 0.4)
    db.set_photo_tag(2, "Pixel", 0.2, 0.2, 0.1, 0.1)
    got = db.tags_for_photos([1, 2, 3])
    assert set(got) == {1, 2}
    assert got[1] == [("Nova", 0.1, 0.1, 0.3, 0.4)]     # not just the name
    db.close()


def test_tag_names_are_ordered_by_how_often_they_are_used(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    for pid in range(1, 4):
        db.set_photo_tag(pid, "Often", 0.1, 0.1, 0.1, 0.1)
    db.set_photo_tag(1, "Rare", 0.5, 0.5, 0.1, 0.1)
    assert db.tag_names()[0] == "Often"
    db.close()


# ---------------------------------------------------------------- geometry

@pytest.fixture(scope="module")
def view():
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from vrchronicle.lightbox import ImageView

    QApplication.instance() or QApplication([])
    v = ImageView()
    v.resize(1000, 700)
    pm = QPixmap(1920, 1080)
    pm.fill()
    v.set_pixmap(pm)
    return v


def test_a_box_hit_tests_where_it_is_drawn(view):
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    box = view._tag_box(view._tags[0])
    assert view._tag_at(box.center()) == 0
    assert view._tag_at(box.topLeft() - view._tag_point(0.2, 0.2)) == -1


def test_a_box_follows_the_image_when_zoomed(view):
    """The whole point of storing fractions: zoom must not move the tag."""
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    before = view._tag_box(view._tags[0])
    view._zoom = 2.5
    after = view._tag_box(view._tags[0])
    assert after.width() > before.width()
    # still centred on the same point of the image
    rect = view._image_rect()
    fx = (after.center().x() - rect.x()) / rect.width()
    assert fx == pytest.approx(0.30 + 0.12 / 2, abs=1e-6)
    view._zoom = 1.0


def test_a_legacy_point_becomes_a_centred_default_box(view):
    view.set_tags([("Old", 0.5, 0.5, 0.0, 0.0)])
    box = view._tag_box(view._tags[0])
    rect = view._image_rect()
    cx = (box.center().x() - rect.x()) / rect.width()
    cy = (box.center().y() - rect.y()) / rect.height()
    assert (cx, cy) == pytest.approx((0.5, 0.5), abs=1e-6)
    assert box.width() > 0 and box.height() > 0


def test_the_default_box_is_square_on_screen(view):
    w, h = view.default_box()
    rect = view._image_rect()
    assert w * rect.width() == pytest.approx(h * rect.height(), rel=1e-6)


def test_the_smallest_overlapping_box_wins_the_click(view):
    view.set_tags([("Big", 0.1, 0.1, 0.8, 0.8), ("Small", 0.4, 0.4, 0.1, 0.1)])
    small = view._tag_box(view._tags[1])
    assert view._tags[view._tag_at(small.center())][0] == "Small"


# ------------------------------------------------- reveal on hover, not always

def _move(view, pos):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    p = QPointF(pos)
    view.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p, p, Qt.NoButton,
                                    Qt.NoButton, Qt.NoModifier))


def _click(view, pos):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    p = QPointF(pos)
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p, p,
                                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def test_pointing_at_somebody_names_them(view):
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    assert view._hover_tag == -1                    # nothing shown at rest
    _move(view, view._tag_box(view._tags[0]).center())
    assert view._hover_tag == 0
    _move(view, view.rect().topRight())             # look away again
    assert view._hover_tag == -1


def test_the_badge_only_exists_when_somebody_is_tagged(view):
    view.set_tags([])
    assert view._badge_rect() is None
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    assert view._badge_rect() is not None


def test_clicking_the_badge_shows_everyone(view):
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    view.set_show_all_tags(False)
    _click(view, view._badge_rect().center())
    assert view._show_all_tags
    _click(view, view._badge_rect().center())
    assert not view._show_all_tags


def test_hover_needs_qt_to_send_moves_without_a_button_held(view):
    """Without mouse tracking Qt never delivers the moves, so hover is dead."""
    assert view.hasMouseTracking()


def _crop(view, rect):
    """Render the view and return the pixels where the tag box would be."""
    from PySide6.QtGui import QPixmap
    target = QPixmap(view.size())
    view.render(target)
    return target.toImage().copy(rect)


def test_a_box_is_invisible_until_you_point_at_it(view):
    """The headline of this feature: the photo must look untouched."""
    tag = ("Nova", 0.30, 0.40, 0.12, 0.20)
    view.set_tags([tag])
    view.set_show_all_tags(False)
    where = view._tag_box(view._tags[0]).toRect().adjusted(-6, -6, 6, 6)

    at_rest = _crop(view, where)
    view.set_tags([])                       # nothing tagged at all
    untagged = _crop(view, where)
    assert at_rest == untagged, "a box was painted before anyone pointed at it"

    view.set_tags([tag])
    view._hover_tag = 0
    assert _crop(view, where) != untagged, "pointing at somebody drew nothing"
    view._hover_tag = -1


def test_the_badge_stays_on_screen_once_everyone_is_shown(view):
    """It is the only way back, so it must not vanish when switched on."""
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    view.set_show_all_tags(True)
    assert view._badge_visible()
    assert view._badge_rect() is not None


def test_tagging_survives_an_image_that_had_not_loaded_yet(view):
    """Pressing T on a still-decoding photo used to leave the button stuck on."""
    from PySide6.QtGui import QPixmap
    view.show_message("Loading…")
    view.set_tagging(True)
    assert not view._tagging          # nothing to tag yet
    pm = QPixmap(1920, 1080)
    pm.fill()
    view.set_pixmap(pm)
    assert view._tagging              # the image arrived; tagging is live
    view.set_tagging(False)


def test_a_click_on_a_box_still_lets_you_pan_a_zoomed_photo(view):
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    view._zoom = 4.0
    _click(view, view._tag_box(view._tags[0]).center())
    assert view._dragging
    view._dragging = False
    view._zoom = 1.0


def test_a_drag_that_overshoots_the_photo_is_cropped_to_it(view):
    """Overshooting into the letterbox used to tag the entire photo."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    got = []
    view.tag_placed.connect(lambda *a: got.append(a))
    view.set_tags([])
    view.set_tagging(True)
    rect = view._image_rect()
    start = QPointF(rect.x() + rect.width() * 0.60, rect.y() + rect.height() * 0.50)
    end = QPointF(rect.x() - 400, rect.y() - 400)          # far off the top-left
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, start, start,
                                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, end, end,
                                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.set_tagging(False)
    assert got, "no tag was placed"
    fx, fy, fw, fh = got[-1]
    assert (fx, fy) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert fw == pytest.approx(0.60, abs=0.02)
    assert fh == pytest.approx(0.50, abs=0.02)


def _drag(view, start, end):
    """Press at start, release at end, and return the box that was stored."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    got = []
    view.tag_placed.connect(lambda *a: got.append(a))
    view.set_tagging(True)
    a, b = QPointF(*start), QPointF(*end)
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, a, a,
                                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, b, b,
                                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.set_tagging(False)
    view.tag_placed.disconnect()
    return got[-1] if got else None


def test_a_small_head_keeps_the_box_you_drew(view):
    """A distant face is a small box. It used to snap to the default size,
    which made tagging everybody in a crowded shot impossible."""
    view.set_tags([])
    rect = view._image_rect()
    x, y = rect.x() + rect.width() * 0.4, rect.y() + rect.height() * 0.4
    for px in (12, 20, 28):                     # all below the old threshold
        _fx, _fy, fw, fh = _drag(view, (x, y), (x + px, y + px))
        drawn_w = fw * rect.width()
        assert drawn_w == pytest.approx(px, abs=1.5),             f"a {px}px drag was stored as {drawn_w:.0f}px"
        assert fw < view.DEFAULT_BOX, "it snapped to the default size"


def test_a_real_click_still_gets_a_head_sized_box(view):
    view.set_tags([])
    rect = view._image_rect()
    x, y = rect.x() + rect.width() * 0.4, rect.y() + rect.height() * 0.4
    _fx, _fy, fw, _fh = _drag(view, (x, y), (x + 2, y + 1))    # a click, not a drag
    assert fw == pytest.approx(view.DEFAULT_BOX, abs=1e-6)


def test_a_thin_drag_is_never_stored_as_a_sliver(view):
    view.set_tags([])
    rect = view._image_rect()
    x, y = rect.x() + rect.width() * 0.4, rect.y() + rect.height() * 0.4
    _fx, _fy, fw, fh = _drag(view, (x, y), (x + 60, y + 1))
    assert fh * rect.height() >= view.MIN_DRAWN - 0.5


def test_a_panorama_cannot_get_a_box_taller_than_itself(view):
    from PySide6.QtGui import QPixmap
    wide = QPixmap(4096, 400)
    wide.fill()
    view.set_pixmap(wide)
    w, h = view.default_box()
    assert 0 < w <= 1.0 and 0 < h <= 1.0
    pm = QPixmap(1920, 1080)
    pm.fill()
    view.set_pixmap(pm)


def test_a_legacy_point_at_the_edge_stays_inside_the_image(view):
    view.set_tags([("Edge", 0.0, 0.0, 0.0, 0.0)])
    box = view._tag_box(view._tags[0])
    rect = view._image_rect()
    assert box.left() >= rect.left() - 0.001
    assert box.top() >= rect.top() - 0.001


def test_clicking_a_box_does_not_leave_the_photo(view):
    """Regression: a click used to navigate away and close the lightbox."""
    seen = []
    view.tag_clicked.connect(seen.append)
    view.set_tags([("Nova", 0.30, 0.40, 0.12, 0.20)])
    _click(view, view._tag_box(view._tags[0]).center())
    assert seen == []
    assert view._pinned_tag == 0                    # the name stays on screen
    _click(view, view._tag_box(view._tags[0]).center())
    assert view._pinned_tag == -1                   # and a second click hides it
    view.tag_clicked.disconnect(seen.append)
