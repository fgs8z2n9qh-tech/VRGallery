"""Small reusable UI pieces: flow layout, toast, cards, empty state, buttons."""
import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer)
from PySide6.QtGui import (QColor, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import icons, style


class Glass:
    """Backdrop-blurred panel background, painted by hand.

    Qt has no backdrop filter, so what is underneath is grabbed from a nominated
    source widget, shrunk hard and scaled back up smoothly -- a cheap blur that
    costs one small pixmap -- then tinted, edged with a hairline and given a soft
    highlight along the top. The source is named explicitly rather than taken
    from the parent, because a panel is a child of what it floats over and
    rendering the parent would draw the panel into its own backdrop.
    """

    RADIUS = 22          # roughly, in screen pixels
    MARGIN = 20          # sample past the edges, so they blur from real content
    TTL = 0.033          # seconds a sampled backdrop may be reused

    @staticmethod
    def _blur(pm, radius=RADIUS):
        """Halve, then double back.

        Halving with a smooth transform is a true 2x2 average, so a few of them
        in a row approximate a gaussian. One hard shrink and one hard blow-up
        does not: it leaves the sample in visible square blocks.
        """
        w, h = max(1, pm.width()), max(1, pm.height())
        small, steps = pm, 0
        while steps < 5 and (1 << steps) < radius and small.width() > 6 and small.height() > 6:
            small = small.scaled(max(1, small.width() // 2), max(1, small.height() // 2),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            steps += 1
        for _ in range(steps):       # back up the same way, so nothing steps
            small = small.scaled(min(w, max(1, small.width() * 2)),
                                 min(h, max(1, small.height() * 2)),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    @staticmethod
    def backdrop(widget, source, ttl=None):
        """Sample and blur what is under `widget`.

        Cached for a few tens of milliseconds: while the grid is scrolling this
        runs on every frame, and re-grabbing and re-blurring each time cost more
        than everything else on the frame put together. A backdrop this heavily
        blurred does not read as stale at 30 samples a second.
        """
        if source is None or not source.isVisible():
            return None, None
        ttl = Glass.TTL if ttl is None else ttl
        now = time.perf_counter()
        cached = getattr(widget, "_glass_cache", None)
        if cached is not None:
            when, size, pm, off = cached
            if now - when < ttl and size == widget.size():
                return pm, off
        # Global coordinates, not mapTo: the panel floats over a widget that is
        # usually a sibling's child, and mapTo only works towards an ancestor.
        try:
            top_left = source.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        except RuntimeError:
            return None, None
        area = QRect(top_left, widget.size()).adjusted(
            -Glass.MARGIN, -Glass.MARGIN, Glass.MARGIN, Glass.MARGIN)
        area = area.intersected(source.rect())
        if area.width() < 4 or area.height() < 4:
            return None, None
        pm = source.grab(area)
        if pm.isNull():
            return None, None
        blurred = Glass._blur(pm)
        # where the sample sits relative to the widget's own origin
        off = QPoint(area.x() - top_left.x(), area.y() - top_left.y())
        widget._glass_cache = (now, widget.size(), blurred, off)
        return blurred, off

    @staticmethod
    def paint(p, widget, source, radius=16, tint=None, tint_alpha=150):
        """Fill `widget`'s whole rect with glass. -> True if a backdrop was used."""
        r = QRectF(widget.rect())
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.save()
        p.setClipPath(path)
        blurred, offset = Glass.backdrop(widget, source)
        base = QColor(tint or style.PAL["surface2"])
        if blurred is not None:
            p.drawPixmap(offset, blurred)
            base.setAlpha(tint_alpha)          # let the blur show through the tint
        p.fillRect(r, base)
        # the specular sheen that makes it read as glass rather than as fog
        sheen = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 6))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 22))
        p.fillRect(r, sheen)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1))
        p.drawPath(path)
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


def ghost_btn(text, icon_name=None, parent=None, danger=False, primary=False):
    b = QPushButton(text, parent)
    b.setObjectName("PrimaryBtn" if primary else ("DangerBtn" if danger else "GhostBtn"))
    b.setCursor(Qt.PointingHandCursor)
    if icon_name:
        color = "#ffffff" if primary else (style.PAL["danger"] if danger else style.PAL["dim"])
        b.setIcon(icons.qicon(icon_name, color, 16))
        b.setIconSize(QSize(16, 16))
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
