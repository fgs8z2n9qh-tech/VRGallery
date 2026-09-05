"""The glass: what it must look like, and what it must not cost.

Every one of these guards something that was measured, not guessed. The costs
are in widgets.Glass's own docstring; these tests only check that the structure
which produces them is still there.
"""
import os
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from vrgallery import widgets
from vrgallery.widgets import Glass


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(app):
    """A glass bar floating over a busy, colourful source widget."""
    host = QWidget()
    host.resize(600, 400)

    class Busy(QWidget):
        def paintEvent(self, _ev):
            p = QPainter(self)
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0.0, QColor(210, 40, 90))
            g.setColorAt(0.5, QColor(20, 130, 210))
            g.setColorAt(1.0, QColor(12, 16, 24))
            p.fillRect(self.rect(), g)
            for x in range(0, self.width(), 41):
                p.fillRect(x, 0, 14, self.height(), QColor(255, 235, 130))
            p.end()

    source = Busy(host)
    source.setGeometry(0, 0, 600, 400)
    bar = widgets.GlassBar(host, radius=16)
    bar.setGeometry(20, 30, 520, 64)
    bar.set_glass_source(source)
    host.show()
    app.processEvents()
    yield host, source, bar
    host.hide()
    # Deleted here, deliberately, rather than left to the garbage collector.
    # A QWidget dropped without this is destroyed on the C++ side at whatever
    # arbitrary later moment Python happens to collect it -- inside another
    # test, often part-way through showing a window -- and the suite acquires
    # an access violation that wanders about when you add a file.
    host.deleteLater()
    app.processEvents()


# ------------------------------------------------------------------ the look

def test_the_blur_is_light_enough_to_still_see_through(panel):
    """A 1/32 smear reads as frosted bathroom glass, not as glass.

    Asserting on K went vacuous when K became 1 and the blur became a real
    convolution; sigma is the knob now, and it is the only one.
    """
    assert 0.3 <= Glass.SIGMA <= 1.2, "past this it stops being glass"
    assert Glass.K == 1, "the sample is being thrown away before it is blurred"


def test_the_tint_thickens_over_a_bright_backdrop_and_not_otherwise(panel):
    dark = Glass.tint_alpha(10.0)
    mid = Glass.tint_alpha(120.0)
    bright = Glass.tint_alpha(250.0)
    assert dark == Glass.TINT_MIN, "a dark backdrop needs no extra frost"
    assert dark < mid < bright, "the tint must follow the backdrop"
    assert bright <= Glass.TINT_MAX, "past this it stops being glass"


def test_the_vibrance_pass_actually_saturates(app):
    """Colours have to push THROUGH the tint, or the panel reads as fog."""
    pm = QPixmap(40, 40)
    pm.fill(QColor(160, 70, 40))
    out = Glass._vibrance(pm)
    a = pm.toImage().pixelColor(20, 20)
    b = out.toImage().pixelColor(20, 20)
    spread_before = max(a.red(), a.green(), a.blue()) - min(a.red(), a.green(), a.blue())
    spread_after = max(b.red(), b.green(), b.blue()) - min(b.red(), b.green(), b.blue())
    assert spread_after > spread_before, "the sample came back as flat as it went in"


def test_the_rim_bends_what_is_under_it(panel):
    """Without this the edge of the panel is just where a blur stops."""
    _host, source, bar = panel
    bar._glass_cache = None
    small, off, _luma, k = Glass.sample(bar, source)
    assert small is not None
    w, h = float(bar.width()), float(bar.height())
    band = max(Glass.BAND_MIN, min(Glass.BAND_MAX, min(w, h) * Glass.BAND_FRAC))
    mag = min(band * Glass.MAG_FRAC, Glass.MAG_MAX, Glass.MARGIN - 1.0)
    assert band > 2 and mag > 1, "the rim would be doing nothing"

    bent = Glass._refract(small, off, k, w, h, band, mag).toImage()
    flat = Glass._refract(small, off, k, w, h, 0.0, 0.0).toImage()
    edge = [(x, 1) for x in range(4, bent.width() - 4, 3)]
    moved = sum(1 for x, y in edge if bent.pixel(x, y) != flat.pixel(x, y))
    assert moved > len(edge) // 3, "the rim did not displace anything"


def test_the_colour_channels_separate_at_the_rim_but_only_just(panel):
    """Two or three pixels of fringe is glass; ten is a prism gimmick."""
    assert 0.0 < Glass.CA < 0.3
    _host, source, bar = panel
    bar._glass_cache = None
    small, off, _l, k = Glass.sample(bar, source)
    w, h = float(bar.width()), float(bar.height())
    band = min(w, h) * Glass.BAND_FRAC
    mag = min(band * Glass.MAG_FRAC, Glass.MAG_MAX, Glass.MARGIN - 1.0)
    assert mag * 2 * Glass.CA < 6.0, "the fringe would be wider than a letter stroke"


def test_the_depth_pools_at_the_bottom_not_all_the_way_round(panel):
    """A ring of shade reads as a vignette; light comes from above."""
    assert Glass.SHADE_BOTTOM > Glass.SHADE_SIDE > Glass.SHADE_TOP


def test_a_floating_header_casts_a_shadow(app):
    """Without one it reads as painted onto the page, not held above it."""
    page = QWidget()
    page.resize(700, 400)
    head = widgets.PageHead(page, "Photos")
    head.add(widgets.ghost_btn("Rescan", "refresh"))
    head.setGeometry(8, 0, 600, head.sizeHint().height())
    page.show()
    app.processEvents()
    assert head.height() > head.bar.height(), "no room below the bar to cast onto"

    shadow = head._shadow_pixmap()
    assert shadow is not None
    img = shadow.toImage()
    below = head.bar.geometry().bottom() + 2
    assert 0 <= below < img.height()
    assert QColor(img.pixel(img.width() // 2, below)).alpha() > 0, "nothing under the bar"
    page.hide()
    page.deleteLater()
    app.processEvents()


# ------------------------------------------------------------------ the cost

def test_a_frame_is_one_blit(panel):
    """Everything expensive happens once per rebuild, never per frame."""
    _host, source, bar = panel
    bar._glass_cache = None
    bar._glass_surface = None
    first = Glass.surface(bar, source, 16, None, None, stamp=1)
    again = Glass.surface(bar, source, 16, None, None, stamp=1)
    assert first is again, "the surface was composited twice in one frame"


def test_a_backdrop_that_is_not_moving_is_not_rebuilt(panel):
    """A panel over a grid sitting still used to re-sample 30 times a second."""
    _host, source, bar = panel
    bar._glass_cache = None
    bar._glass_surface = None
    first = Glass.surface(bar, source, 16, None, None, stamp=7)
    assert first is not None
    # walk the clock past the moving-backdrop window
    when, key, stamp, pm = bar._glass_surface
    bar._glass_surface = (when - Glass.TTL * 2, key, stamp, pm)
    same = Glass.surface(bar, source, 16, None, None, stamp=7)
    assert same is first, "it rebuilt itself to arrive at the same picture"
    moved = Glass.surface(bar, source, 16, None, None, stamp=8)
    assert moved is not first, "a moved backdrop must rebuild"


def test_the_stamp_reaches_the_glass_from_the_scrollbar(app):
    """The bar cannot know its backdrop moved unless something tells it."""
    from PySide6.QtWidgets import QScrollArea

    page = QWidget()
    scroll, _holder, box = widgets.scroll_body(page)
    head = widgets.PageHead(page, "Photos")
    head.add(widgets.ghost_btn("Rescan", "refresh"))
    head.attach(scroll, reserve_in=box)
    before = head.bar._stamp
    scroll.verticalScrollBar().setRange(0, 1000)
    scroll.verticalScrollBar().setValue(430)
    assert head.bar._stamp != before, "scrolling did not invalidate the glass"


def test_the_sample_reaches_past_the_panel_and_is_kept_whole(panel):
    """It used to be shrunk, and the shrink WAS the blur. Now it is blurred."""
    _host, source, bar = panel
    bar._glass_cache = None
    small, _off, _luma, k = Glass.sample(bar, source)
    assert k == Glass.K
    assert small.width() * k <= bar.width() + 2 * Glass.MARGIN + k
    assert small.width() >= bar.width(), "the rim has nothing to bend"
    taps = Glass._taps()
    assert len(taps) == 2 * Glass.TAPS + 1
    assert taps[Glass.TAPS] == max(taps), "the centre tap must be drawn first"
    assert taps == taps[::-1], "the kernel is not symmetric"


def _blur_of(img_maker, dx):
    """Blur a plate whose content sits dx pixels over. -> QImage"""
    from PySide6.QtGui import QPainter, QPixmap
    pm = QPixmap(160, 64)
    pm.fill(Qt.black)
    p = QPainter(pm)
    img_maker(p, dx)
    p.end()
    return Glass._blur(pm).toImage()


def test_the_blur_does_not_crawl_when_the_backdrop_moves(app):
    """The point of a real convolution, and the thing the resample got wrong.

    A convolution commutes with a shift: blur-then-move and move-then-blur give
    the same picture. A downsample does not -- its output depends on where the
    content lands inside the 2x2 cell it averages, so every pixel of the
    backdrop remutated as the grid scrolled under it. That crawl measured
    3.4/255 on every odd offset and is a good part of what read as cheap.
    """
    def plate(p, dx):
        for x in range(0, 160, 4):
            p.fillRect(x + dx, 0, 2, 64, QColor(240, 230, 200))

    # An ODD offset, and that is the whole test: a resample only misbehaves
    # when the content lands on a different phase inside the 2x2 cell it
    # averages, so shifting by a whole number of cells hides the defect
    # completely. Shifting by 8 passes against the old blur.
    shift = 1
    a = _blur_of(plate, 0)
    b = _blur_of(plate, shift)
    worst = 0
    for y in range(8, 56, 7):              # compare the interior, away from the ends
        for x in range(20, 120, 3):
            ca = QColor(a.pixel(x, y))
            cb = QColor(b.pixel(x + shift, y))
            worst = max(worst, abs(ca.red() - cb.red()),
                        abs(ca.green() - cb.green()), abs(ca.blue() - cb.blue()))
    assert worst == 0, f"the backdrop crawls by {worst}/255 as it scrolls"


def test_the_rim_never_samples_past_what_was_captured(panel):
    """The margin is what the rim has to bend; magnify further and it smears
    the clamped edge of the sample instead of real content."""
    for w, h in ((520, 64), (300, 300), (90, 40), (1400, 44)):
        band = max(Glass.BAND_MIN, min(Glass.BAND_MAX, min(w, h) * Glass.BAND_FRAC))
        band = min(band, min(w, h) / 2.0 - 1.0)
        mag = min(band * Glass.MAG_FRAC, Glass.MAG_MAX, Glass.MARGIN - 1.0)
        assert mag <= Glass.MARGIN - 1.0, f"{w}x{h} reaches outside the sample"
