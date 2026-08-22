"""Small reusable UI pieces: flow layout, toast, cards, empty state, buttons."""
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import icons, style


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
