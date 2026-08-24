"""Small reusable UI pieces: flow layout, toast, cards, empty state, buttons."""
import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRegion)
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import icons, style


class Glass:
    """Backdrop-blurred panel background, painted by hand.

    Qt has no backdrop filter, so what is underneath is sampled from a nominated
    source widget, blurred, bent at the rim, tinted and edged. The source is
    named explicitly rather than taken from the parent, because a panel is a
    child of what it floats over and rendering the parent would draw the panel
    into its own backdrop.

    The look follows Mixtape's Glass.cs. What separates glass from fog:

      * a LIGHT blur. Halving the sample five times -- a 1/32 smear -- reads as
        frosted bathroom glass. Liquid glass is sharp: you can still make out
        what is behind it.
      * a VIBRANCE pass, so the colours behind push through the tint instead of
        greying out under it.
      * a TINT that is mostly transparent, and only thickens over a bright
        backdrop, where text would otherwise stop being readable.
      * REFRACTION at the rim: the outer band magnifies what is under it and the
        space curves into the panel, the way it does through a real pane. Each
        colour channel bends by a slightly different amount, which is the faint
        fringe along the edge of real glass. Without any of this the edge is
        just where a blur stops.

    Two things keep that affordable, and they matter more than the average
    cost: what stutters is a burst on one frame in five, not a steady tax.

      * THE FINISHED SURFACE IS CACHED. A frame is one blit -- eight
        microseconds -- however much work went into the glass.
      * IT ONLY REBUILDS WHEN THE BACKDROP MOVED. A panel over a page that is
        sitting still costs nothing at all; it used to re-sample thirty times a
        second to arrive at the same picture.

    The vibrance and the rim still run on the 1/K sample, where there are K^2
    fewer pixels. Rasterizing the sample itself at 1/K was tried too -- a third
    cheaper -- and reverted: Qt samples each thumbnail with four taps at that
    scale and every hard edge came back as a staircase.
    """

    RADIUS = 22          # roughly, in screen pixels
    MARGIN = 14          # sample past the edges, so the rim bends real content
    TTL = 0.033          # seconds between rebuilds while the backdrop is moving
    IDLE_TTL = 0.6       # ...and while it is not

    K = 2                # everything happens at 1/K, and that IS the blur
    SAT = 1.42           # saturation multiplier for the vibrance pass
    LIFT = 1.03          # and a whisper of brightness with it
    TINT_MIN, TINT_MAX = 132, 178
    TINT_FROM = 60.0     # backdrop luma at which the tint starts thickening
    TINT_SLOPE = 0.5

    # the refracting rim
    BAND_FRAC, BAND_MIN, BAND_MAX = 0.34, 10.0, 30.0
    MAG_FRAC, MAG_MAX = 0.62, 18.0
    STRIPS = 5           # sub-steps per edge: the displacement has to fall off
    CA = 0.14            # chromatic aberration, as a share of the displacement
    # Depth pools at the bottom inner edge, under a light from above. A ring all
    # the way round reads as a vignette, and a glowing rim reads as neon.
    SHADE_BOTTOM, SHADE_SIDE, SHADE_TOP = 0.24, 0.10, 0.04

    # ------------------------------------------------------------- sampling
    @staticmethod
    def _vibrance(pm):
        """Push the saturation of the sample, in place of a real filter.

        Done on the 1/K pixmap -- a ninth of the pixels -- so this costs a fifth
        of a millisecond even though it goes out to Pillow and back. If anything
        about the conversion fails the sample comes back untouched: a slightly
        flat panel is a far better outcome than a painter that raises.
        """
        try:
            from PIL import Image, ImageEnhance
            img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
            w, h = img.width(), img.height()
            if w < 2 or h < 2:
                return pm
            # RGBA8888 is 4 bytes a pixel, so the row stride never needs padding
            # and the buffer maps to Pillow one to one.
            src = Image.frombytes("RGBA", (w, h), bytes(img.constBits()))
            src = ImageEnhance.Color(src).enhance(Glass.SAT)
            src = ImageEnhance.Brightness(src).enhance(Glass.LIFT)
            out = QImage(src.tobytes(), w, h, QImage.Format_RGBA8888).copy()
            return QPixmap.fromImage(out)
        except Exception:
            return pm

    @staticmethod
    def _luma(pm):
        """Mean brightness of the sample, from a one-pixel scale of it."""
        try:
            one = pm.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            c = one.toImage().pixelColor(0, 0)
            return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        except Exception:
            return 0.0

    @staticmethod
    def tint_alpha(luma):
        """Thicker frost over a bright backdrop, so labels stay readable."""
        a = Glass.TINT_MIN + Glass.TINT_SLOPE * max(0.0, luma - Glass.TINT_FROM)
        return int(max(Glass.TINT_MIN, min(Glass.TINT_MAX, a)))

    @staticmethod
    def sample(widget, source, ttl=None):
        """What is under `widget`, rasterized at 1/K. -> (pixmap, offset, luma, k)

        `offset` is where the sample starts relative to the widget's own origin,
        in FULL pixels -- negative, because it reaches out past the edges so the
        rim has real content to bend. Divide by k to work in the sample.
        """
        if source is None or not source.isVisible():
            return None, None, 0.0, Glass.K
        ttl = Glass.TTL if ttl is None else ttl
        now = time.perf_counter()
        cached = getattr(widget, "_glass_cache", None)
        if cached is not None:
            when, size, pm, off, luma = cached
            if now - when < ttl and size == widget.size():
                return pm, off, luma, Glass.K
        # Global coordinates, not mapTo: the panel floats over a widget that is
        # usually a sibling's child, and mapTo only works towards an ancestor.
        try:
            top_left = source.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        except RuntimeError:
            return None, None, 0.0, Glass.K
        area = QRect(top_left, widget.size()).adjusted(
            -Glass.MARGIN, -Glass.MARGIN, Glass.MARGIN, Glass.MARGIN)
        area = area.intersected(source.rect())
        if area.width() < 4 or area.height() < 4:
            return None, None, 0.0, Glass.K
        k = Glass.K
        try:
            full = source.grab(area)
        except (RuntimeError, ValueError):
            return None, None, 0.0, k
        if full.isNull():
            return None, None, 0.0, k
        # Grab at full size and shrink with a smooth transform, which is a real
        # area average. Rasterizing straight into a 1/k pixmap is a third
        # cheaper -- and it was, until you look at it: Qt samples each thumbnail
        # with four taps at a third scale, which aliases every hard edge into
        # a staircase. The saving is not worth what is behind the glass turning
        # to gravel.
        small = full.scaled(max(2, -(-area.width() // k)),
                            max(2, -(-area.height() // k)),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        luma = Glass._luma(small)
        small = Glass._vibrance(small)
        off = QPoint(area.x() - top_left.x(), area.y() - top_left.y())
        widget._glass_cache = (now, widget.size(), small, off, luma)
        return small, off, luma, k

    @staticmethod
    def backdrop(widget, source, ttl=None):
        """The sample scaled back up: the plain blurred backdrop, full size."""
        small, off, luma, k = Glass.sample(widget, source, ttl=ttl)
        if small is None:
            return None, None, 0.0
        return small.scaled(small.width() * k, small.height() * k,
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation), off, luma

    # ------------------------------------------------------------ refracting
    @staticmethod
    def _bend(dst, src, w, h, band, mag, vertical):
        """One axis of the rim, as strips that each sample a little inward.

        A convex lens keeps refracted rays inside the shape, so content near an
        edge is displaced TOWARDS the middle and comes out magnified. Each strip
        is one scaled blit, and because the displacement falls to zero at the
        inner boundary the band joins the untouched centre without a seam. Run
        once per axis: two passes compose into a real corner, which one pass
        drawn over the other cannot.
        """
        n = Glass.STRIPS
        for i in range(n):
            a = band * i / n
            b = band * (i + 1) / n
            fa = mag * (1.0 - a / band) ** 2
            fb = mag * (1.0 - b / band) ** 2
            span = (b - a) + (fb - fa)          # narrower than the strip -> magnified
            if span <= 0.02:
                continue
            if vertical:
                dst.drawPixmap(QRectF(0.0, a, w, b - a),
                               src, QRectF(0.0, a + fa, w, span))
                dst.drawPixmap(QRectF(0.0, h - b, w, b - a),
                               src, QRectF(0.0, h - b - fb, w, span))
            else:
                dst.drawPixmap(QRectF(a, 0.0, b - a, h),
                               src, QRectF(a + fa, 0.0, span, h))
                dst.drawPixmap(QRectF(w - b, 0.0, b - a, h),
                               src, QRectF(w - b - fb, 0.0, span, h))

    @staticmethod
    def _channel(pm, rgb):
        """A copy of `pm` with only one colour channel left in it."""
        out = QPixmap(pm.size())
        out.fill(Qt.black)
        p = QPainter(out)
        p.drawPixmap(0, 0, pm)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(out.rect(), QColor(*rgb))
        p.end()
        return out

    @staticmethod
    def _pass(src, w, h, band, mag):
        """Both axes of the rim, into a fresh pixmap the size of `src`."""
        mid = QPixmap(src.size())
        mid.fill(Qt.transparent)
        q = QPainter(mid)
        q.setRenderHint(QPainter.SmoothPixmapTransform, True)
        q.drawPixmap(0, 0, src)
        Glass._bend(q, src, w, h, band, mag, vertical=False)
        q.end()
        out = QPixmap(src.size())
        out.fill(Qt.transparent)
        q = QPainter(out)
        q.setRenderHint(QPainter.SmoothPixmapTransform, True)
        q.drawPixmap(0, 0, mid)
        Glass._bend(q, mid, w, h, band, mag, vertical=True)
        q.end()
        return out

    @staticmethod
    def _refract(small, off, k, w, h, band, mag):
        """The backdrop with its rim bent inward, still at 1/K.

        A couple of pixels of colour separation is all real glass shows; more
        than that is a prism gimmick rather than a window.
        """
        ws, hs = w / k, h / k
        base = QPixmap(max(2, int(math.ceil(ws))), max(2, int(math.ceil(hs))))
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QPointF(off.x() / k, off.y() / k), small)
        p.end()
        bs, ms = band / k, mag / k
        if bs < 1.0 or ms < 0.2:
            return base
        if Glass.CA <= 0.0:
            return Glass._pass(base, ws, hs, bs, ms)

        out = QPixmap(base.size())
        out.fill(Qt.black)
        acc = QPainter(out)
        acc.setCompositionMode(QPainter.CompositionMode_Plus)
        for scale, rgb in ((1.0 - Glass.CA, (255, 0, 0)),
                           (1.0, (0, 255, 0)),
                           (1.0 + Glass.CA, (0, 0, 255))):
            acc.drawPixmap(0, 0, Glass._pass(Glass._channel(base, rgb),
                                             ws, hs, bs, ms * scale))
        acc.end()
        return out

    # ------------------------------------------------------------ compositing
    @staticmethod
    def surface(widget, source, radius=16, tint=None, tint_alpha=None,
                stamp=None, ttl=None):
        """The finished glass for `widget`, composited once and then reused.

        `stamp` is anything that changes when the backdrop could have moved -- a
        scroll position, usually. While it holds still the surface is kept for
        IDLE_TTL instead of TTL, which is the difference between a panel that
        costs nothing when nothing is happening and one that rebuilds itself
        thirty times a second to arrive at the same picture.
        """
        w, h = widget.width(), widget.height()
        if w < 4 or h < 4:
            return None
        key = (widget.size(), radius, tint, tint_alpha)
        now = time.perf_counter()
        cached = getattr(widget, "_glass_surface", None)
        if cached is not None:
            when, ckey, cstamp, pm = cached
            if ckey == key:
                age = now - when
                if age < (Glass.TTL if ttl is None else ttl):
                    return pm
                if stamp is not None and stamp == cstamp and age < Glass.IDLE_TTL:
                    return pm
        small, off, luma, k = Glass.sample(widget, source, ttl=ttl)
        if small is None:
            return None

        band = max(Glass.BAND_MIN, min(Glass.BAND_MAX, min(w, h) * Glass.BAND_FRAC))
        band = min(band, min(w, h) / 2.0 - 1.0)
        mag = min(band * Glass.MAG_FRAC, Glass.MAG_MAX, Glass.MARGIN - 1.0)
        lens = Glass._refract(small, off, k, float(w), float(h), band, mag)

        surf = QPixmap(w, h)
        surf.fill(Qt.transparent)
        p = QPainter(surf)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        # scaled(), not drawPixmap(rect, ...): the painter's bilinear upscale
        # leaves the sample in visible blocks, the smooth transform does not
        big = lens.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.save()
        p.setClipPath(path)
        p.drawPixmap(0, 0, big)
        base = QColor(tint or style.PAL["surface2"])
        base.setAlpha(Glass.tint_alpha(luma) if tint_alpha is None else tint_alpha)
        p.fillRect(r, base)
        Glass._rim_shade(p, r, band)
        p.restore()

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawPath(path)
        # The glint along the top edge is the specular highlight; a bright line
        # all the way round would be neon instead of glass.
        p.save()
        p.setClipRect(QRectF(0, 0, w, max(2.0, radius * 0.9)))
        p.setPen(QPen(QColor(255, 255, 255, 72), 1))
        p.drawPath(path)
        p.restore()
        p.end()

        widget._glass_surface = (now, key, stamp, surf)
        return surf

    @staticmethod
    def _rim_shade(p, r, band):
        """Directional depth: it pools at the bottom, barely touches the top."""
        b = max(3.0, band)
        for rect, grad, strength in (
            (QRectF(r.left(), r.bottom() - b, r.width(), b),
             (r.left(), r.bottom() - b, r.left(), r.bottom()), Glass.SHADE_BOTTOM),
            (QRectF(r.left(), r.top(), r.width(), b),
             (r.left(), r.top() + b, r.left(), r.top()), Glass.SHADE_TOP),
            (QRectF(r.left(), r.top(), b, r.height()),
             (r.left() + b, r.top(), r.left(), r.top()), Glass.SHADE_SIDE),
            (QRectF(r.right() - b, r.top(), b, r.height()),
             (r.right() - b, r.top(), r.right(), r.top()), Glass.SHADE_SIDE),
        ):
            g = QLinearGradient(*grad)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(255 * strength)))
            p.fillRect(rect, g)

    @staticmethod
    def paint(p, widget, source, radius=16, tint=None, tint_alpha=None, stamp=None):
        """Fill `widget`'s whole rect with glass. -> True if a backdrop was used."""
        surf = Glass.surface(widget, source, radius, tint, tint_alpha, stamp=stamp)
        if surf is None:
            return False
        p.drawPixmap(0, 0, surf)
        return True


class SmoothScroll(QObject):
    """Eases a scroll area towards a target instead of jumping to it.

    A wheel notch moves the bar by a fixed number of pixels at once, which on a
    photo grid reads as a stutter. Notches accumulate into a target here and a
    timer walks the bar towards it, so a fast flick glides rather than stepping.
    """

    TAU = 0.085          # seconds: the glide's time constant, not a per-tick share

    def __init__(self, view, step=170, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.step = step
        self._target = None
        self._pos = None          # float, so small per-frame moves do not round to 0
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._retune()
        view.viewport().installEventFilter(self)

    def _retune(self):
        """Run at the display's own rate: 16 ms is a stutter on a 144 Hz panel."""
        hz = 60.0
        try:
            scr = self.view.screen() or QGuiApplication.primaryScreen()
            if scr and scr.refreshRate() > 1:
                hz = float(scr.refreshRate())
        except Exception:
            pass
        self.hz = max(60.0, min(240.0, hz))
        self._timer.setInterval(max(4, int(round(1000.0 / self.hz))))

    def eventFilter(self, obj, ev):
        # The type check first, and nothing else before it. This filter sits on
        # a viewport and sees EVERY event that reaches it -- thousands a second
        # while the pointer is over the grid -- and all but the wheel ones are
        # none of its business. Anything above this line is paid for by all of
        # them.
        if ev.type() != QEvent.Wheel:
            return False
        try:
            mine = obj is self.view.viewport()
        except (RuntimeError, AttributeError):
            # The view went away before its filter did -- RuntimeError when the
            # C++ side is gone, AttributeError when Python has already emptied
            # the instance. Qt calling into a half-torn-down object is how a Qt
            # app dies with an access violation and no traceback.
            try:
                self._timer.stop()
            except (RuntimeError, AttributeError):
                pass
            return False
        if mine:
            if ev.modifiers() & Qt.ControlModifier:
                return False              # ctrl+wheel is a zoom, not a scroll
            if ev.angleDelta().x() and not ev.angleDelta().y():
                return False              # sideways: let the view have it
            if self.wheel(ev.angleDelta().y()):
                ev.accept()
                return True
        return super().eventFilter(obj, ev)

    def bar(self):
        return self.view.verticalScrollBar()

    def wheel(self, angle_delta_y):
        """-> True if the gesture was taken over."""
        if not angle_delta_y:
            return False
        bar = self.bar()
        base = self._target if self._target is not None else bar.value()
        notches = angle_delta_y / 120.0
        self._target = max(bar.minimum(),
                           min(bar.maximum(), int(base - notches * self.step)))
        if self._target == bar.value():
            self._target = None
            return True
        if self._pos is None:
            self._pos = float(bar.value())
        if not self._timer.isActive():
            self._retune()                   # the window may be on another screen
            self._last = time.perf_counter()
            self._timer.start()
        return True

    def stop(self):
        self._timer.stop()
        self._target = None
        self._pos = None

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        self._step(dt)

    def _step(self, dt):
        """One frame of glide. Time-based, so a faster display is smoother
        rather than quicker -- a fixed share per tick would just arrive sooner
        the more often it ran."""
        try:
            bar = self.bar()
        except RuntimeError:
            self._timer.stop()
            return
        if self._target is None or self._pos is None:
            self._timer.stop()
            return
        self._pos += (self._target - self._pos) * (1.0 - math.exp(-dt / self.TAU))
        if abs(self._target - self._pos) < 0.5:
            bar.setValue(self._target)
            self.stop()
            return
        bar.setValue(int(round(self._pos)))


class GlassBar(QFrame):
    """A frosted bar that content scrolls underneath."""

    def __init__(self, parent=None, radius=0, tint=None, tint_alpha=None):
        super().__init__(parent)
        self._glass_source = None
        self._radius = radius
        self._tint = tint
        self._alpha = tint_alpha
        self._stamp = 0

    def set_glass_source(self, w):
        self._glass_source = w
        self.update()

    def set_glass_stamp(self, v):
        """Tell the glass its backdrop moved. Anything comparable will do."""
        if v != self._stamp:
            self._stamp = v
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not Glass.paint(p, self, self._glass_source, radius=self._radius,
                           tint=self._tint or style.PAL["bg"], tint_alpha=self._alpha,
                           stamp=self._stamp):
            p.fillRect(self.rect(), QColor(self._tint or style.PAL["bg"]))
        p.end()


class PageHead(QWidget):
    """The floating glass header every page wears.

    It is not in the page's layout: it hovers over the scrolling surface so the
    content slides underneath and shows through the frosting. The page reserves
    the same amount of room at the top of its content -- which is why
    `reserved()` reports the OPEN height even while the bar is collapsed. If the
    reservation followed the animation, the content would jump while scrolling.
    """

    MARGIN = 8            # leaves the window's own rounded border visible
    COLLAPSE_AT = 60      # px of scroll before the title gives up its room
    PAD_OPEN, PAD_TIGHT = 10, 6

    viewport_resized = Signal()

    def __init__(self, page, title="", sub="", parent=None):
        super().__init__(parent or page)
        self.page = page
        self._scroller = None
        self._extra = None
        self._can_collapse = False
        self._collapsed = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, self.MARGIN)   # room for the shadow
        col.setSpacing(0)
        self.bar = GlassBar(self, radius=16)
        col.addWidget(self.bar)
        self._col = col
        self._shadow = None

        row = QHBoxLayout(self.bar)
        row.setContentsMargins(24, self.PAD_OPEN, 24, self.PAD_OPEN)
        row.setSpacing(10)
        self.row = row
        self.titlecol = QWidget()
        tc = QVBoxLayout(self.titlecol)
        tc.setContentsMargins(0, 0, 0, 0)
        tc.setSpacing(0)
        self.lab_title = QLabel(title)
        self.lab_title.setObjectName("PageHeaderTitle")
        self.lab_sub = QLabel(sub)
        self.lab_sub.setObjectName("PageHeaderSub")
        tc.addWidget(self.lab_title)
        tc.addWidget(self.lab_sub)
        self._title_fx = QGraphicsOpacityEffect(self.titlecol)
        self.titlecol.setGraphicsEffect(self._title_fx)
        row.addWidget(self.titlecol)
        row.addStretch(1)
        self._stretch = row.count() - 1     # left of here is the title side

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self.apply_collapse)

    # ---- filling it ----
    def add_left(self, w, spacing=0):
        """Put a widget between the title and the gap, e.g. a segmented control."""
        if spacing:
            self.row.insertSpacing(self._stretch, spacing)
            self._stretch += 1
        self.row.insertWidget(self._stretch, w)
        self._stretch += 1
        return w

    def insert_front(self, w):
        """Ahead of the title -- a Back button, typically."""
        self.row.insertWidget(0, w)
        self._stretch += 1
        return w

    def add(self, w):
        """Put a widget on the right-hand side."""
        self.row.addWidget(w)
        return w

    def set_extra_row(self, w):
        """A second row that rides with the header, e.g. the filter bar."""
        self._extra = w
        self._col.addWidget(w)
        return w

    def set_title(self, title=None, sub=None):
        if title is not None:
            self.lab_title.setText(title)
        if sub is not None:
            self.lab_sub.setText(sub)

    # ---- binding it to something that scrolls ----
    def attach(self, scroller, reserve_in=None):
        """Float over `scroller`; leave room for that in `reserve_in`.

        Call this once the header is filled: the collapsed height is measured
        from the controls, so it has to happen after they are in.
        """
        self._scroller = scroller
        self.bar.set_glass_source(scroller.viewport())
        scroller.viewport().installEventFilter(self)
        scroller.verticalScrollBar().valueChanged.connect(self._sync)
        scroller.verticalScrollBar().valueChanged.connect(self.bar.set_glass_stamp)
        self.measure()
        if reserve_in is not None:
            m = reserve_in.contentsMargins()
            reserve_in.setContentsMargins(m.left(), self.reserved(),
                                          m.right(), m.bottom())
        self.place()
        return self

    def measure(self):
        """Both heights, taken from the controls themselves.

        The collapsed height has to clear the tallest control plus its padding:
        guessing it as "a bit less than the open one" cut the search box and the
        pills in half. A header with nothing but a title has nothing left to
        show once the title fades, so it does not collapse at all.
        """
        self._open = self.bar.sizeHint().height()
        tall = 0
        for i in range(self.row.count()):
            w = self.row.itemAt(i).widget()
            if w is not None and w is not self.titlecol:
                tall = max(tall, w.sizeHint().height())
        self._can_collapse = tall > 0
        self._tight = min(self._open, tall + self.PAD_TIGHT * 2) if tall else self._open

    def reserved(self):
        """How much room the page must leave free at the top."""
        h = getattr(self, "_open", None) or self.bar.sizeHint().height()
        if self._extra is not None and self._extra.isVisible():
            h += self._extra.sizeHint().height()
        return h + self.MARGIN

    def now(self):
        """How tall it is at this moment, for placing whatever sits under it.

        The widget already includes the gap it casts its shadow into, so this is
        just its height.
        """
        return self.height()

    def paintEvent(self, ev):
        """The shadow the panel casts on the content sliding under it.

        Without one a floating pane reads as painted onto the page rather than
        held above it -- and this is the parent of the glass, so it lands behind
        it without any compositing tricks. Drawn once per size into a pixmap: it
        is repainted on every frame the bar is, because the bar's own corners
        are transparent and Qt has to put something under them.
        """
        shadow = self._shadow_pixmap()
        if shadow is not None:
            QPainter(self).drawPixmap(0, 0, shadow)

    def _shadow_pixmap(self):
        panel = self.bar.geometry()
        if self._extra is not None and self._extra.isVisible():
            panel = panel.united(self._extra.geometry())
        if panel.width() < 8 or panel.height() < 4:
            return None
        key = (self.size(), panel)
        if self._shadow is not None and self._shadow[0] == key:
            return self._shadow[1]
        pm = QPixmap(self.size())
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        n = self.MARGIN
        r = QRectF(panel)
        # Concentric rounded rects, each a little larger, lower and fainter: a
        # blur without the cost of one, and the light is from above so it sits
        # below the panel rather than around it.
        for i in range(n, 0, -1):
            t = i / float(n)
            p.setBrush(QColor(0, 0, 0, int(30 * (1.0 - t) ** 1.6) + 4))
            p.drawRoundedRect(r.adjusted(-i * 0.4, i * 0.25, i * 0.4, i * 0.95),
                              16 + i * 0.4, 16 + i * 0.4)
        p.end()
        self._shadow = (key, pm)
        return pm

    def place(self):
        if self._scroller is None:
            return
        # Bound to the VIEWPORT, so the bar clears the scrollbar and anything
        # else in the gutter rather than lying across it. Flush with the top: an
        # inset leaves a sliver of scrolled content peeking over the bar, which
        # reads as a glitch rather than as depth.
        vp = self._scroller.viewport()
        tl = vp.mapTo(self.page, QPoint(0, 0))
        self.setGeometry(tl.x() + self.MARGIN, 0,
                         max(160, vp.width() - self.MARGIN * 2),
                         self.sizeHint().height())
        self.raise_()

    def apply_collapse(self, t):
        """t: 0 fully open, 1 fully collapsed."""
        w = self.titlecol.sizeHint().width()
        self.titlecol.setMaximumWidth(max(0, int(w * (1 - t))))
        self._title_fx.setOpacity(max(0.0, 1.0 - t * 1.6))
        pad = round(self.PAD_OPEN + (self.PAD_TIGHT - self.PAD_OPEN) * t)
        self.row.setContentsMargins(24, pad, 24, pad)
        h = self._open + (self._tight - self._open) * t
        self.bar.setFixedHeight(int(round(h)))
        self.place()
        self.collapsed_changed()

    def collapsed_changed(self):
        """Hook: the page moves whatever else floats over the same scroller."""

    def _sync(self, _v=0):
        if not self._can_collapse or self._scroller is None:
            return
        want = self._scroller.verticalScrollBar().value() > self.COLLAPSE_AT
        if want == self._collapsed:
            return
        self._collapsed = want
        self._anim.stop()
        start = self._anim.currentValue()
        self._anim.setStartValue(float(start if start is not None
                                       else (0.0 if want else 1.0)))
        self._anim.setEndValue(1.0 if want else 0.0)
        self._anim.start()

    def eventFilter(self, obj, ev):
        # See SmoothScroll.eventFilter: the type check comes first because this
        # one sees every event the viewport does, and cares about one of them.
        if ev.type() != QEvent.Resize:
            return False
        try:
            scroller = getattr(self, "_scroller", None)
            mine = scroller is not None and obj is scroller.viewport()
        except (RuntimeError, AttributeError):
            return False          # the scroller went away before its filter did
        if mine:
            self.place()
            self.viewport_resized.emit()
        return super().eventFilter(obj, ev)


class _PassWheel:
    """Mixin: do not eat the wheel unless you are the thing being aimed at.

    Qt hands a wheel event to whatever sits under the pointer, so flicking down
    a page over a combo box silently changes the setting instead of scrolling --
    and now that every page's header floats over its content, there is always
    something to flick over. Click it first and the wheel works as usual, which
    is the only time turning it was deliberate.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.StrongFocus)      # and never take focus on hover

    def wheelEvent(self, ev):
        if self.hasFocus():
            super().wheelEvent(ev)
        else:
            ev.ignore()


class ComboBox(_PassWheel, QComboBox):
    pass


class SpinBox(_PassWheel, QSpinBox):
    pass


class Slider(_PassWheel, QSlider):
    pass


def scroll_body(page, left=24, right=16, bottom=20, spacing=12):
    """A page's scrolling body, in the shape a floating header expects.

    The margins live on the CONTENT, not on the page, because the header hovers
    over the scroll area and the content has to be able to slide right up under
    it. -> (scroll area, holder widget, holder layout)
    """
    root = QVBoxLayout(page)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(left, 0, right, bottom)
    box.setSpacing(spacing)
    scroll.setWidget(holder)
    root.addWidget(scroll, 1)
    SmoothScroll(scroll)
    return scroll, holder, box


class TitleBar(QFrame):
    """The window's own title bar, so the chrome matches the app.

    Dragging hands off to the compositor with startSystemMove rather than
    moving the window by hand: that is what keeps Aero Snap, the snap layouts
    on the maximise button and the shake gestures working on a frameless
    window.
    """

    HEIGHT = 28          # slim: it holds three buttons, not a title

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.lab = QLabel("")
        self.lab.setObjectName("TitleBarText")
        lay.addWidget(self.lab)
        lay.addStretch(1)
        self.btn_min = self._chrome("win-min", "Minimise", window.showMinimized)
        self.btn_max = self._chrome("win-max", "Maximise", self.toggle_max)
        self.btn_close = self._chrome("x", "Close", window.close, danger=True)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def _chrome(self, icon, tip, slot, danger=False):
        b = QPushButton()
        b.setObjectName("WinCloseBtn" if danger else "WinBtn")
        b.setFixedSize(40, 26)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.ArrowCursor)
        b.setIcon(icons.qicon(icon, style.PAL["dim"], 14))
        b.setIconSize(QSize(14, 14))
        b.clicked.connect(slot)
        return b

    def set_text(self, text):
        self.lab.setText(text)

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()
        self.sync()

    def sync(self):
        maxed = self.win.isMaximized()
        self.btn_max.setIcon(icons.qicon("win-restore" if maxed else "win-max",
                                         style.PAL["dim"], 14))
        self.btn_max.setToolTip("Restore" if maxed else "Maximise")

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.toggle_max()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            handle = self.win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                ev.accept()
                return
        super().mousePressEvent(ev)


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hspace=8, vspace=8):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._h = hspace
        self._v = vspace
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        s += QSize(m.left() + m.right(), m.top() + m.bottom())
        return s

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h + m.bottom() - rect.y()


class Toast(QFrame):
    """One non-blocking toast, bottom-center of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._glass_source = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 16, 9)
        lay.setSpacing(9)
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setObjectName("ToastText")
        lay.addWidget(self._icon)
        lay.addWidget(self._text)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(220)
        self._hide_when_done = False
        self._anim.finished.connect(self._on_anim_done)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def set_glass_source(self, w):
        self._glass_source = w
        self.setAttribute(Qt.WA_StyledBackground, w is None)

    def paintEvent(self, ev):
        if self._glass_source is None:
            return super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        Glass.paint(p, self, self._glass_source, radius=12)
        p.end()

    def _on_anim_done(self):
        if self._hide_when_done:
            self.hide()

    def show_message(self, text, kind="info"):
        color = {"ok": style.PAL["ok"], "err": style.PAL["danger"]}.get(kind, style.PAL["dim"])
        name = {"ok": "check", "err": "info"}.get(kind, "info")
        self._icon.setPixmap(icons.pixmap(name, color, 16, self.devicePixelRatioF()))
        self._text.setText(text)
        self.adjustSize()
        self._replace()
        self.raise_()
        self.show()
        self._fx.setOpacity(0.0)
        self._anim.stop()
        self._hide_when_done = False
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        self._timer.start(2800)

    def _replace(self):
        p = self.parentWidget()
        if p:
            self.move((p.width() - self.width()) // 2, p.height() - self.height() - 26)

    def _fade_out(self):
        self._anim.stop()
        self._hide_when_done = True
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()


class EmptyState(QWidget):
    def __init__(self, icon_name, title, sub="", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        # It is laid over a view, so it must never swallow a click meant for
        # whatever is underneath it.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(icons.pixmap(icon_name, style.PAL["faint"], 46,
                                  self.devicePixelRatioF(), width=1.4))
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:15px; font-weight:600; color:%s;" % style.PAL["dim"])
        lay.addWidget(ic)
        lay.addWidget(t)
        self._sub = QLabel(sub)
        self._sub.setAlignment(Qt.AlignCenter)
        self._sub.setWordWrap(True)
        self._sub.setMaximumWidth(460)      # keeps wrapping predictable in any layout
        self._sub.setStyleSheet("font-size:12px; color:%s;" % style.PAL["faint"])
        lay.addWidget(self._sub, 0, Qt.AlignHCenter)
        self.set_sub(sub)

    def set_text(self, title, sub=""):
        self.layout().itemAt(1).widget().setText(title)
        self.set_sub(sub)

    def set_sub(self, sub):
        self._sub.setText(sub)
        self._sub.setVisible(bool(sub))


class Card(QFrame):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(18, 16, 18, 16)
        self.vbox.setSpacing(12)
        self._title = None
        if title:
            self._title = QLabel(title)
            self._title.setObjectName("CardTitle")
            self.vbox.addWidget(self._title)

    def set_title(self, title):
        if self._title is not None:
            self._title.setText(title)


class StatCard(QFrame):
    def __init__(self, icon_name, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        self._ic = QLabel()
        self._ic.setFixedSize(40, 40)
        self._ic.setAlignment(Qt.AlignCenter)
        self._ic.setStyleSheet(
            "background:%s; border-radius:12px;" % style.mix(style.PAL["border2"], 0.5))
        self._ic.setPixmap(icons.pixmap(icon_name, style.PAL["dim"], 20,
                                        self.devicePixelRatioF()))
        col = QVBoxLayout()
        col.setSpacing(0)
        self._num = QLabel("–")
        self._num.setStyleSheet("font-size:20px; font-weight:700;")
        self._lab = QLabel("")
        self._lab.setStyleSheet("font-size:11px; color:%s;" % style.PAL["dim"])
        col.addWidget(self._num)
        col.addWidget(self._lab)
        lay.addWidget(self._ic)
        lay.addLayout(col, 1)

    def set(self, number, label):
        self._num.setText(str(number))
        self._lab.setText(label)


def icon_btn(name, tooltip="", color=None, px=18, checkable=False, parent=None,
             fill=None, width=2.0):
    b = QPushButton(parent)
    b.setObjectName("IconBtn")
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    b.setIcon(icons.qicon(name, color or style.PAL["dim"], px, 2.0, width, fill))
    b.setIconSize(QSize(px, px))
    b.setFixedSize(px + 16, px + 16)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCheckable(checkable)
    return b


ICON_GAP = 7          # blank pixels baked into the icon, to its right


def ghost_btn(text, icon_name=None, parent=None, danger=False, primary=False):
    b = QPushButton(text, parent)
    b.setObjectName("PrimaryBtn" if primary else ("DangerBtn" if danger else "GhostBtn"))
    b.setCursor(Qt.PointingHandCursor)
    if icon_name:
        color = "#ffffff" if primary else (style.PAL["danger"] if danger else style.PAL["dim"])
        b.setIcon(icons.qicon(icon_name, color, 16, pad=ICON_GAP))
        b.setIconSize(QSize(16 + ICON_GAP, 16))
    return b


class SectionLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text.upper(), parent)
        self.setObjectName("SectionLabel")


class SelectionBar(QFrame):
    """Floating action bar for multi-select (slides up when it appears)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SelBar")
        self._glass_source = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 10, 8)
        lay.setSpacing(4)
        self.count_lab = QLabel("0")
        self.count_lab.setObjectName("SelCount")
        lay.addWidget(self.count_lab)
        self.btn_fav = icon_btn("star", "Add to favorites", style.PAL["star"])
        self.btn_album = icon_btn("layers", "Add to album")
        self.btn_trash = icon_btn("trash", "Move to Recycle Bin", style.PAL["danger"])
        self.btn_close = icon_btn("x", "Clear selection")
        for b in (self.btn_fav, self.btn_album, self.btn_trash, self.btn_close):
            lay.addWidget(b)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(200)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self.hide()

    def set_glass_source(self, w):
        """The widget it floats over, whose content becomes the blurred backdrop."""
        self._glass_source = w
        self.setAttribute(Qt.WA_StyledBackground, w is None)

    def paintEvent(self, ev):
        if self._glass_source is None:
            return super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        Glass.paint(p, self, self._glass_source, radius=16)
        p.end()

    def set_count(self, n, size_text=""):
        t = f"{n} selected"
        if size_text:
            t += f" · {size_text}"
        self.count_lab.setText(t)

    def slide_to(self, x, y):
        self._slide.stop()
        self.move(x, y + 26)
        self._slide.setStartValue(QPoint(x, y + 26))
        self._slide.setEndValue(QPoint(x, y))
        self._slide.start()


class HLine(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background:%s;" % style.PAL["border"])


class GradientDot(QWidget):
    """Accent swatch for the settings page."""

    def __init__(self, a, b, selected=False, on_click=None, parent=None):
        super().__init__(parent)
        self.a, self.b = a, b
        self.selected = selected
        self._on_click = on_click
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(self.a))
        g.setColorAt(1, QColor(self.b))
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawEllipse(4, 4, 26, 26)
        if self.selected:
            pen = p.pen()
            p.setBrush(Qt.NoBrush)
            from PySide6.QtGui import QPen
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawEllipse(2, 2, 30, 30)
        p.end()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._on_click:
            self._on_click()
        super().mouseReleaseEvent(ev)
