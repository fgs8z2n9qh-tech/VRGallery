"""Two things that were drawn outside the box they belong in.

Both were visible on every page that has cards, and both had been there long
enough to read as a style rather than a fault:

  * a card's cover is SIZED to the band at the top of the card but was CLIPPED
    only to the card, so any cover that is not 16:9 ran down over the title.
    That is why on Worlds some names sat on the photograph and others sat on
    the plate below it.
  * a thumbnail strip clamped its per-tile width up to a minimum without
    bringing the tile COUNT down, laid the row out wider than the widget, and
    let Qt cut the overflowing tile in half. Memories asks for nine and eight
    fit, so there was always exactly one sliced thumbnail on the page.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from vrgallery import pages


@pytest.fixture(scope="module", autouse=True)
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------- the card's cover

RED = QColor(255, 0, 0)


class _Cache:
    """Stands in for ThumbCache: hands back one pixmap and remembers nothing."""

    def __init__(self, pm=None):
        self.pm = pm
        self.watched = []

    def get(self, _item, *a, **k):
        return self.pm

    def peek(self, _pid):
        return self.pm

    def watch(self, pid, w):
        self.watched.append((pid, w))


def _tall_cover(w=200, h=900):
    """A cover far taller than the band it goes in -- the case that spilled."""
    pm = QPixmap(w, h)
    pm.fill(RED)
    return pm


# Widgets built here are kept for the module's lifetime on purpose: PySide frees
# the C++ half whenever Python drops the last reference, and that lands inside
# whatever test happens to be running when the collector gets round to it.
_KEEP = []


class _Index:
    def __init__(self, card):
        self._card = card

    def data(self, _role=None):
        return self._card


def _paint_card(cache, w=None, h=None, card=None):
    """Paint one card into an image and hand it back."""
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    view = QWidget()
    view.resize(400, 400)
    d = pages.CardDelegate(view, cache)
    _KEEP.append((view, d))
    w = w or d.W
    h = h or d.H
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, w, h)
    opt.state = QStyle.State_None
    d.paint(p, opt, _Index(card or {
        "kind": "card", "title": "A world with quite a long name",
        "sub": "12 photos", "cover": 1, "icon": "image"}))
    p.end()
    return img, d


def test_a_tall_cover_stays_inside_its_band(app):
    """The whole bug in one assertion: no cover pixel below the band."""
    img, d = _paint_card(_Cache(_tall_cover()))
    band = d.COVER_H
    bleed = [y for y in range(band + 4, img.height())
             if any(QColor(img.pixel(x, y)) == RED
                    for x in range(6, img.width() - 6, 7))]
    assert not bleed, (
        f"the cover ran {len(bleed)} rows past its band, down to y={max(bleed)} "
        f"of {img.height()} -- the title sits in there")


def test_the_cover_still_fills_the_band(app):
    """Clipping must not be mistaken for shrinking: the band is still covered
    corner to corner, which is what a cover-fit is for."""
    img, d = _paint_card(_Cache(_tall_cover()))
    mid = d.COVER_H // 2
    for x in (4, img.width() // 2, img.width() - 5):
        assert QColor(img.pixel(x, mid)) == RED, f"a gap in the band at x={x}"


def test_a_card_with_no_cover_is_unchanged(app):
    """The placeholder path shares the band and must not have been clipped out
    of existence."""
    img, d = _paint_card(_Cache(None))
    mid = d.COVER_H // 2
    assert QColor(img.pixel(img.width() // 2, mid)) != QColor(0, 0, 0), \
        "the empty-cover plate was not drawn"


# ---------------------------------------------------------------- the strip

class _Item:
    def __init__(self, i):
        self.id = i
        self.path = f"/nope/{i}.png"
        self.mtime = 0.0
        self.filesize = 0
        self.is_video = False


def _strip(n, width=1160, max_h=240):
    host = QWidget()
    host.resize(width + 40, 400)
    _KEEP.append(host)
    s = pages.ThumbStrip(max_h=max_h, parent=host)
    s.resize(width, max_h)
    cache = _Cache(None)
    for i in range(n):
        s.add(None, cache, _Item(i), lambda: None)
    s.resize(width, s.height())
    return s


def _placed(strip):
    """Every child the strip chose to show, left to right.

    isHidden, not isVisible: the host is never shown in a test, so isVisible is
    false for everything and would make each of these pass on nothing.
    """
    out = [c for c in strip.children()
           if isinstance(c, QWidget) and not c.isHidden()]
    return sorted(out, key=lambda c: c.x())


def test_nothing_is_laid_out_past_the_edge_of_the_strip(app):
    """The row used to be placed wider than the widget, and Qt cut whatever
    hung over. Nine into a row that holds eight was the everyday case."""
    for n in (1, 2, 5, 8, 9, 12, 40):
        s = _strip(n)
        for c in _placed(s):
            assert c.x() + c.width() <= s.width() + 1, (
                f"{n} thumbnails: one is placed at {c.x()}..{c.x() + c.width()} "
                f"in a strip {s.width()} px wide")


def test_when_they_do_not_all_fit_the_last_slot_says_how_many(app):
    s = _strip(12)
    shown = _placed(s)
    more = [c for c in shown if isinstance(c, pages.MoreTile)]
    assert len(more) == 1, "no +N where twelve thumbnails do not fit"
    assert more[0] is shown[-1], "the +N is not in the last slot"
    assert more[0]._count == 12 - (len(shown) - 1), (
        "the +N does not add up to the number left out")


def test_a_strip_that_fits_shows_no_plus(app):
    s = _strip(4)
    assert not [c for c in _placed(s) if isinstance(c, pages.MoreTile)], \
        "a +N appeared where everything already fitted"
    assert len(_placed(s)) == 4


def test_the_tiles_still_share_the_row(app):
    """The point of the strip: two photos fill the card rather than sitting as
    two stamps in a sea of empty."""
    s = _strip(2, width=900)
    tiles = _placed(s)
    assert len(tiles) == 2
    right = max(t.x() + t.width() for t in tiles)
    assert right > 400, f"two thumbnails only reached x={right} of 900"


def test_a_narrow_strip_still_shows_something(app):
    """Narrower than one tile's minimum: it must place one, not zero, and not
    divide by zero working it out."""
    s = _strip(6, width=90)
    shown = _placed(s)
    assert shown, "a narrow strip showed nothing at all"
    assert shown[0].x() == 0


def test_clearing_takes_the_plus_with_it(app):
    """It is built on demand and parented to the strip; a refresh that left it
    behind would stack a +N per rebuild."""
    s = _strip(12)
    assert [c for c in _placed(s) if isinstance(c, pages.MoreTile)]
    s.clear()
    assert not [c for c in _placed(s) if isinstance(c, pages.MoreTile)]
    assert s._more is None


def test_the_title_survives_the_cover_being_clipped(app):
    """The clip has to be put back. Left in place it is the card's own title
    that disappears instead of the cover's overflow -- the same bug with the
    sign flipped, and a clipped-away title looks like missing data."""
    img, d = _paint_card(_Cache(_tall_cover()))
    band = d.COVER_H
    # Against the PLATE, not against the window behind the card. Comparing with
    # the corner outside the rounded rect counts the whole card body as ink and
    # passes whatever happens.
    plate = QColor(img.pixel(img.width() - 6, band + 18))
    ink = sum(1 for y in range(band + 6, img.height() - 6)
              for x in range(13, img.width() - 40)
              if QColor(img.pixel(x, y)) != plate)
    assert ink > 40, f"only {ink} pixels that are not bare plate below the band: no title"


def test_the_plus_goes_away_when_the_room_comes_back(app):
    """A window widened until everything fits must not keep a +0 sitting in the
    last slot. It is built once and reused, so it has to be told to go."""
    s = _strip(12, width=1160)
    assert [c for c in _placed(s) if isinstance(c, pages.MoreTile)], \
        "twelve did not overflow a 1160 px strip; this test proves nothing"
    s.resize(1900, s.height())          # wide enough for all twelve
    s._relayout()
    assert not [c for c in _placed(s) if isinstance(c, pages.MoreTile)], \
        "the +N stayed after the strip grew wide enough for everything"
    assert len(_placed(s)) == 12
