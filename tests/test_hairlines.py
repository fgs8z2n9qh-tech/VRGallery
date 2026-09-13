"""Things drawn a half pixel out, or with the wrong hint, or with no clip.

None of these is a layout mistake -- every one of them is code that runs, draws
the thing it meant to draw, and puts it slightly in the wrong place or at the
wrong strength. They are the kind of defect that reads as "this app looks a bit
soft" rather than as a bug, which is why they survived so long.
"""
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from vrgallery import gridmodel, gridpage, lightbox, style


@pytest.fixture(scope="module", autouse=True)
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


_KEEP = []          # see tests/test_cards.py: widgets are not dropped mid-run


# ------------------------------------------------------------- the rail ticks

def test_a_rail_tick_is_one_row_at_its_full_colour():
    """A one-pixel pen is centred ON the coordinate it is given, so at a whole y
    it straddles two rows and the antialiaser -- on, for the year labels -- puts
    half the colour in each. Measured on the shipped render before this: every
    month tick was #1f232f over #1e232e, and #303748, the colour it is meant to
    be, appeared nowhere in the rail at all."""
    rail = gridpage.TimelineRail()
    _KEEP.append(rail)
    rail.resize(rail.WIDTH, 600)
    marks = [(0, "2026-01"), (400, "2026-02"), (800, "2026-03"), (1200, "2026-04")]
    rail.set_marks(marks, 2000)
    pm = rail._scale_pixmap()
    img = pm.toImage()

    want = QColor(style.PAL["border2"]).rgb() & 0xFFFFFF
    x = int((rail.WIDTH - 7) * pm.devicePixelRatio())
    hits = [y for y in range(img.height()) if (img.pixel(x, y) & 0xFFFFFF) == want]
    assert hits, (
        "the tick colour never appears at full strength: every tick was split "
        "across two rows")


# --------------------------------------------------- the tile's rounded corner

class _Cache:
    """A ThumbCache that hands back one pixmap and calls everything brand new."""

    def __init__(self, pm, age):
        self.pm = pm
        self.age = age

    def get(self, _item, *a, **k):
        return self.pm

    def peek(self, _pid):
        return self.pm

    def age_ms(self, _pid):
        return self.age

    def watch(self, *a):
        pass


class _Item:
    id = 1
    path = "/nope.png"
    mtime = 0.0
    filesize = 10
    is_video = False
    favorite = 0
    rating = 0
    missing = 0
    day = "2026-02-01"
    taken_at = "2026-02-01T10:00:00"
    world_name = ""
    avatar_name = ""
    filename = "nope.png"


class _View(QWidget):
    """Enough of a QListView for the delegate: it asks its view for a viewport
    to repaint while a thumbnail is fading in, and for the tile spacing."""

    def viewport(self):
        return self

    def spacing(self):
        return 7


def _paint_tile(age_ms, w=180, h=101):
    """One photo tile, painted onto the page's own background colour."""
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    view = _View()
    view.resize(400, 400)
    thumb = QPixmap(320, 180)
    thumb.fill(QColor(255, 0, 0))
    cache = _Cache(thumb, age_ms)
    d = gridmodel.PhotoDelegate(view, cache)
    d.set_cell_width(w)
    _KEEP.append((view, d, thumb))

    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(style.PAL["bg"]))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, w, h)
    opt.state = QStyle.State_None
    try:
        d._paint_photo(p, opt, _Item())
    finally:
        # A QPainter left active on an image is destroyed with a live target,
        # and that takes the process down at the next collection -- long after
        # whatever raised, in somebody else's test.
        p.end()
    return img


def test_a_tile_that_is_still_fading_keeps_its_rounded_corners():
    """The fast path sets no clip, because the cached tile carries its corners
    in its own alpha. The plate drawn UNDER it during the fade is not that tile,
    and unclipped it squares the corners off for the 220 ms a thumbnail takes to
    fade in -- which is every thumbnail, on every scroll through photos that are
    not in the cache yet."""
    bg = QColor(style.PAL["bg"]).rgb() & 0xFFFFFF
    plate = QColor(style.PAL["surface2"]).rgb() & 0xFFFFFF
    img = _paint_tile(age_ms=40.0)          # mid-fade
    corner = img.pixel(0, 0) & 0xFFFFFF
    assert corner != plate, (
        f"the corner is bare surface2 (#{corner:06x}): the fade plate was drawn "
        f"square, outside the tile's rounded shape")
    assert corner == bg, f"the corner is #{corner:06x}, not the page's #{bg:06x}"


def test_a_settled_tile_was_never_the_problem():
    """Once the fade is over nothing draws the plate at all; this is the control,
    and it must not change."""
    bg = QColor(style.PAL["bg"]).rgb() & 0xFFFFFF
    img = _paint_tile(age_ms=9999.0)
    assert img.pixel(0, 0) & 0xFFFFFF == bg


def test_the_middle_of_a_fading_tile_is_still_the_photo():
    """Clipping the plate must not clip the picture with it."""
    img = _paint_tile(age_ms=40.0)
    mid = QColor(img.pixel(img.width() // 2, img.height() // 2))
    assert mid.red() > mid.blue(), "the red test thumbnail is not in the tile"


# -------------------------------------------------- the lightbox's own curves

def _tagged_view(w=420, h=300):
    """A lightbox image view showing one photo with one face box on it."""
    v = lightbox.ImageView()
    _KEEP.append(v)
    v.resize(w, h)
    pm = QPixmap(w, h)
    pm.fill(QColor(20, 20, 20))   # grey, so a white stroke blended over it stays grey
    v.set_pixmap(pm)
    v.set_tags([("Someone", 0.30, 0.28, 0.25, 0.30)])
    v.set_show_all_tags(True)
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    v.render(img)
    return img


def _edge_shades(img):
    """How many distinct greys the white box edge is drawn in.

    A hard-thresholded curve has two: on and off. An antialiased one has a
    spread, because the pixels a curve only partly covers get part of the
    colour. Counting them is the difference, without caring where the box is.
    """
    shades = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if c.red() == c.green() == c.blue() and c.red() > 60:
                shades.add(c.red())
    return shades


def test_the_lightbox_antialiases_what_it_draws_over_the_photo():
    """Face boxes, their name pills, the dashed live box and the people badge
    are all curves on fractional coordinates -- they come off a float fit-scale.
    With the hint off the engine hard-thresholds the coverage and every one of
    them comes out as a staircase.

    Counted in pixels, not read out of the source: the word "Antialiasing"
    appears in the comment that explains the fix, so grepping the function would
    pass with the fix taken back out.
    """
    shades = _edge_shades(_tagged_view())
    assert len(shades) > 8, (
        f"the box edge is drawn in only {len(shades)} shades ({sorted(shades)}): "
        f"that is a hard threshold, not an antialiased curve")


def test_the_photo_itself_is_still_smoothed(app):
    """The two hints do different jobs. Adding one must not have replaced the
    other, or the photograph goes to nearest-neighbour on every zoom."""
    v = lightbox.ImageView()
    _KEEP.append(v)
    v.resize(300, 200)
    # a two-pixel chequer scaled right up: smoothed it blends, unsmoothed it
    # stays two colours
    src = QImage(2, 2, QImage.Format_RGB32)
    src.setPixel(0, 0, QColor(255, 255, 255).rgb())
    src.setPixel(1, 1, QColor(255, 255, 255).rgb())
    src.setPixel(1, 0, QColor(0, 0, 0).rgb())
    src.setPixel(0, 1, QColor(0, 0, 0).rgb())
    v.set_pixmap(QPixmap.fromImage(src))
    img = QImage(300, 200, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    v.render(img)
    greys = {QColor(img.pixel(x, y)).red()
             for y in range(0, 200, 3) for x in range(0, 300, 3)
             if QColor(img.pixel(x, y)).red() == QColor(img.pixel(x, y)).blue()}
    assert len(greys) > 4, (
        f"the photo scaled up into {len(greys)} distinct levels: it is not "
        f"being smoothed")
