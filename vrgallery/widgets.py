"""Small reusable UI pieces: flow layout, toast, cards, empty state, buttons."""
import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import icons, style


class Glass:
    """Backdrop-blurred panel background, painted by hand.

    Qt has no backdrop filter, so what is underneath is grabbed from a nominated
    source widget, blurred, tinted and edged. The source is named explicitly
    rather than taken from the parent, because a panel is a child of what it
    floats over and rendering the parent would draw the panel into its own
    backdrop.

    The numbers come from Mixtape's Glass.cs, which is the look this is meant to
    match. Three of them are what separate glass from fog:

      * a LIGHT blur. This used to halve the sample up to five times -- a 1/32
        smear -- and the result read as frosted bathroom glass. Liquid glass is
        sharp: you can still make out what is behind it.
      * a VIBRANCE pass, so the colours behind push through the tint instead of
        greying out under it.
      * a TINT that is mostly transparent, and only thickens over a bright
        backdrop, where text would otherwise stop being readable.
    """

    RADIUS = 22          # roughly, in screen pixels
    MARGIN = 20          # sample past the edges, so they blur from real content
    TTL = 0.033          # seconds a sampled backdrop may be reused

    BLUR_K = 3           # one downsample to 1/k and back, nothing more
    SAT = 1.42           # saturation multiplier for the vibrance pass
    LIFT = 1.03          # and a whisper of brightness with it
    TINT_MIN, TINT_MAX = 132, 178
    TINT_FROM = 60.0     # backdrop luma at which the tint starts thickening
    TINT_SLOPE = 0.5

    @staticmethod
    def _blur(pm, k=None):
        """One trip down to 1/k and back, with a smooth transform both ways."""
        k = k or Glass.BLUR_K
        w, h = max(1, pm.width()), max(1, pm.height())
        small = pm.scaled(max(2, w // k), max(2, h // k),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        small = Glass._vibrance(small)
        return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    @staticmethod
    def _vibrance(pm):
        """Push the saturation of the small sample, in place of a real filter.

        Done on the DOWNSAMPLED pixmap -- a ninth of the pixels -- and the
        upsample afterwards spreads the boosted colour, so this costs a fraction
        of a millisecond even though it goes out to Pillow and back. If anything
        about the conversion fails the sample is returned untouched: a slightly
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
    def backdrop(widget, source, ttl=None):
        """Sample and blur what is under `widget`. -> (pixmap, offset, luma)

        Cached for a few tens of milliseconds: while the grid is scrolling this
        runs on every frame, and re-grabbing and re-blurring each time cost more
        than everything else on the frame put together.
        """
        if source is None or not source.isVisible():
            return None, None, 0.0
        ttl = Glass.TTL if ttl is None else ttl
        now = time.perf_counter()
        cached = getattr(widget, "_glass_cache", None)
        if cached is not None:
            when, size, pm, off, luma = cached
            if now - when < ttl and size == widget.size():
                return pm, off, luma
        # Global coordinates, not mapTo: the panel floats over a widget that is
        # usually a sibling's child, and mapTo only works towards an ancestor.
        try:
            top_left = source.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        except RuntimeError:
            return None, None, 0.0
        area = QRect(top_left, widget.size()).adjusted(
            -Glass.MARGIN, -Glass.MARGIN, Glass.MARGIN, Glass.MARGIN)
        area = area.intersected(source.rect())
        if area.width() < 4 or area.height() < 4:
            return None, None, 0.0
        pm = source.grab(area)
        if pm.isNull():
            return None, None, 0.0
        luma = Glass._luma(pm)
        blurred = Glass._blur(pm)
        # where the sample sits relative to the widget's own origin
        off = QPoint(area.x() - top_left.x(), area.y() - top_left.y())
        widget._glass_cache = (now, widget.size(), blurred, off, luma)
        return blurred, off, luma

    @staticmethod
    def paint(p, widget, source, radius=16, tint=None, tint_alpha=None):
        """Fill `widget`'s whole rect with glass. -> True if a backdrop was used."""
        r = QRectF(widget.rect())
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.save()
        p.setClipPath(path)
        blurred, offset, luma = Glass.backdrop(widget, source)
        base = QColor(tint or style.PAL["surface2"])
        if blurred is not None:
            p.drawPixmap(offset, blurred)
            base.setAlpha(Glass.tint_alpha(luma) if tint_alpha is None else tint_alpha)
        p.fillRect(r, base)

        # Depth pools at the BOTTOM inner edge, the way it does under a real
        # pane lit from above. The old version laid a sheen across the whole
        # panel instead, which is what made the middle look milky.
        band = max(6.0, min(14.0, r.height() * 0.28))
        shade = QLinearGradient(r.left(), r.bottom() - band, r.left(), r.bottom())
        shade.setColorAt(0.0, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 48))
        p.fillRect(QRectF(r.left(), r.bottom() - band, r.width(), band), shade)
        p.restore()

        p.setBrush(Qt.NoBrush)
        # A hairline, and a brighter one along the top edge only: that glint is
        # the specular highlight. A glow around the whole rim reads as neon.
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)
        p.save()
        p.setClipRect(QRectF(r.left(), r.top(), r.width(), max(2.0, radius * 0.9)))
        p.setPen(QPen(QColor(255, 255, 255, 64), 1))
        p.drawPath(path)
        p.restore()
        return blurred is not None


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
        try:
            mine = obj is self.view.viewport()
        except RuntimeError:      # the view went away before its filter did
            self._timer.stop()
            return False
        if mine and ev.type() == QEvent.Wheel:
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

    def __init__(self, parent=None, radius=0, tint=None, tint_alpha=175):
        super().__init__(parent)
        self._glass_source = None
        self._radius = radius
        self._tint = tint
        self._alpha = tint_alpha

    def set_glass_source(self, w):
        self._glass_source = w
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not Glass.paint(p, self, self._glass_source, radius=self._radius,
                           tint=self._tint or style.PAL["bg"], tint_alpha=self._alpha):
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
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.bar = GlassBar(self, radius=16)
        col.addWidget(self.bar)
        self._col = col

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
        """How tall it is at this moment, for placing whatever sits under it."""
        return self.height() + self.MARGIN

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
        try:
            mine = self._scroller is not None and obj is self._scroller.viewport()
        except RuntimeError:      # the scroller went away before its filter did
            return False
        if mine and ev.type() == QEvent.Resize:
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
