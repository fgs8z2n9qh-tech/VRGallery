"""Custom-painted mini charts (no dependencies): bars, horizontal bars, hour strip."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import fmt, style


def _accent_pair(cfg):
    ac = style.accent(cfg.get("accent"))
    return QColor(ac["a"]), QColor(ac["b"])


class BarChart(QWidget):
    """Vertical bars, e.g. photos per month.

    data: [(label, value)] or [(label, value, anchor)]. An anchor label is
    always drawn and drawn brighter -- with four years of months on one strip
    the January of each year is what makes the whole run readable.
    """

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.data = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data):
        self.data = list(data)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self.data:
            p.setPen(QColor(style.PAL["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            p.end()
            return
        a, b = _accent_pair(self.cfg)
        f = QFont()
        f.setPointSizeF(7.6)
        fm = QFontMetrics(f)
        p.setFont(f)
        bottom = self.height() - 22
        top = 16
        maxv = max(row[1] for row in self.data) or 1
        n = len(self.data)
        gap = 5
        bw = max(4.0, (self.width() - gap * (n + 1)) / n)
        label_every = max(1, int(46 / (bw + gap)) + (0 if bw >= 40 else 1))
        for i, row in enumerate(self.data):
            label, v = row[0], row[1]
            anchor = len(row) > 2 and row[2]
            x = gap + i * (bw + gap)
            h = (bottom - top) * (v / maxv)
            rect = QRectF(x, bottom - h, bw, h)
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            path = QPainterPath()
            r = min(4.0, bw / 2)
            path.addRoundedRect(rect, r, r)
            p.fillPath(path, g)
            count = fmt.count_label(v)
            # only when it fits between its neighbours, or the numbers collide
            if v and fm.horizontalAdvance(count) <= bw + gap - 2:
                p.setPen(QColor(style.PAL["dim"]))
                p.drawText(QRectF(x - 10, rect.top() - 15, bw + 20, 13),
                           Qt.AlignCenter, count)
            if anchor or i % label_every == 0:
                p.setPen(QColor(style.PAL["dim"] if anchor else style.PAL["faint"]))
                p.drawText(QRectF(x - 14, bottom + 5, bw + 28, 14), Qt.AlignCenter, label)
        p.end()


class HBarChart(QWidget):
    """Horizontal top-N bars. data: [(label, value)]."""

    ROW = 30

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.data = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data):
        self.data = list(data)
        self.setMinimumHeight(max(60, len(self.data) * self.ROW + 8))
        self.updateGeometry()
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self.data:
            p.setPen(QColor(style.PAL["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            p.end()
            return
        a, b = _accent_pair(self.cfg)
        f = QFont()
        f.setPointSizeF(9)
        fm = QFontMetrics(f)
        p.setFont(f)
        label_w = min(190, max(fm.horizontalAdvance(l) for l, _v in self.data) + 10)
        val_w = 48
        maxv = max(v for _l, v in self.data) or 1
        for i, (label, v) in enumerate(self.data):
            y = i * self.ROW + 4
            p.setPen(QColor(style.PAL["text"]))
            p.drawText(QRectF(0, y, label_w - 8, self.ROW - 8),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(label, Qt.ElideRight, label_w - 10))
            track = QRectF(label_w, y + (self.ROW - 8 - 10) / 2,
                           max(10.0, self.width() - label_w - val_w), 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(style.PAL["surface2"]))
            p.drawRoundedRect(track, 5, 5)
            w = track.width() * (v / maxv)
            bar = QRectF(track.x(), track.y(), max(6.0, w), track.height())
            g = QLinearGradient(bar.x(), 0, bar.right(), 0)
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            p.setBrush(g)
            p.drawRoundedRect(bar, 5, 5)
            p.setPen(QColor(style.PAL["dim"]))
            p.drawText(QRectF(self.width() - val_w + 6, y, val_w - 6, self.ROW - 8),
                       Qt.AlignVCenter | Qt.AlignRight, fmt.count_label(v))
        p.end()


class HourChart(QWidget):
    """24 thin bars: what hour of the day the camera comes out."""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.counts = [0] * 24
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, rows):
        self.counts = [0] * 24
        for r in rows:
            try:
                self.counts[int(r["h"])] += r["c"]
            except (ValueError, TypeError, IndexError):
                pass
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        a, b = _accent_pair(self.cfg)
        f = QFont()
        f.setPointSizeF(7.6)
        p.setFont(f)
        bottom = self.height() - 18
        top = 10
        maxv = max(self.counts) or 1
        gap = 4
        bw = (self.width() - gap * 25) / 24
        for h in range(24):
            x = gap + h * (bw + gap)
            v = self.counts[h]
            hh = (bottom - top) * (v / maxv)
            rect = QRectF(x, bottom - hh, bw, hh)
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            path = QPainterPath()
            r = min(3.0, bw / 2)
            path.addRoundedRect(rect, r, r)
            p.setOpacity(0.35 + 0.65 * (v / maxv))
            p.fillPath(path, g)
            p.setOpacity(1.0)
            if h % 3 == 0:
                p.setPen(QColor(style.PAL["faint"]))
                p.drawText(QRectF(x - 8, bottom + 3, bw + 16, 13), Qt.AlignCenter, str(h))
        p.end()
