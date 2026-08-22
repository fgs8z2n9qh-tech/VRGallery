"""Fullscreen slideshow with crossfade."""
from PySide6.QtCore import QRectF, Qt, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import fmt
from .lightbox import _LoaderSignals, _LoadJob
from PySide6.QtCore import QThreadPool


class Slideshow(QWidget):
    def __init__(self, cfg, parent=None):
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.items = []
        self.pos = 0
        self._pm = None
        self._prev_pm = None
        self._alpha = 1.0
        self._paused = False
        self._pending = {}
        self._sig = _LoaderSignals()
        self._sig.loaded.connect(self._on_loaded)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(420)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade.valueChanged.connect(self._on_fade)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(1800)
        self._cursor_timer.timeout.connect(lambda: self.setCursor(Qt.BlankCursor))
        self.setMouseTracking(True)

    def start(self, items, pos=0):
        if not items:
            return
        self.items = list(items)
        self.pos = max(0, min(pos, len(items) - 1))
        self._pm = None
        self._prev_pm = None
        self._paused = False
        self.showFullScreen()
        self.setCursor(Qt.BlankCursor)
        self._load_current(first=True)
        secs = max(2, int(self.cfg.get("slideshow_secs") or 5))
        self._timer.start(secs * 1000)

    def stop(self):
        self._timer.stop()
        self._fade.stop()
        self.hide()

    # ---- flow ----
    def _advance(self):
        if self._paused or not self.items:
            return
        self.pos = (self.pos + 1) % len(self.items)
        self._load_current()

    def _step_manual(self, d):
        self.pos = (self.pos + d) % len(self.items)
        self._load_current()
        secs = max(2, int(self.cfg.get("slideshow_secs") or 5))
        self._timer.start(secs * 1000)

    def _load_current(self, first=False):
        it = self.items[self.pos]
        self._request(it.path, show=True)
        nxt = self.items[(self.pos + 1) % len(self.items)]
        self._request(nxt.path, show=False)

    def _request(self, path, show):
        if path in self._pending:
            if show:
                self._pending[path] = True
            return
        self._pending[path] = show
        QThreadPool.globalInstance().start(_LoadJob(self._sig, path))

    def _on_loaded(self, path, img):
        show = self._pending.pop(path, False)
        if img.isNull():
            return
        cur = self.items[self.pos] if self.items else None
        if show and cur and cur.path == path and self.isVisible():
            self._prev_pm = self._pm
            self._pm = QPixmap.fromImage(img)
            self._alpha = 0.0 if self._prev_pm else 1.0
            if self._prev_pm:
                self._fade.stop()
                self._fade.setStartValue(0.0)
                self._fade.setEndValue(1.0)
                self._fade.start()
            self.update()

    def _on_fade(self, v):
        self._alpha = float(v)
        if self._alpha >= 1.0:
            self._prev_pm = None
        self.update()

    # ---- paint ----
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        def draw(pm, alpha):
            if not pm:
                return
            s = min(self.width() / pm.width(), self.height() / pm.height())
            dw, dh = pm.width() * s, pm.height() * s
            p.setOpacity(alpha)
            p.drawPixmap(QRectF((self.width() - dw) / 2, (self.height() - dh) / 2, dw, dh),
                         pm, QRectF(0, 0, pm.width(), pm.height()))

        draw(self._prev_pm, 1.0)
        draw(self._pm, self._alpha)
        p.setOpacity(1.0)
        # caption
        if self.items:
            it = self.items[self.pos]
            cap = []
            if it.world_name:
                cap.append(it.world_name)
            d = fmt.dt_label(it.taken_at)
            if d:
                cap.append(d)
            text = "   ·   ".join(cap)
            if text:
                f = QFont()
                f.setPointSizeF(11)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255, 60))
                p.drawText(self.rect().adjusted(28, 0, -28, -22),
                           Qt.AlignLeft | Qt.AlignBottom, text)
            if self._paused:
                p.setPen(QColor(255, 255, 255, 120))
                p.drawText(self.rect().adjusted(28, 0, -28, -22),
                           Qt.AlignRight | Qt.AlignBottom, "⏸ paused")
        p.end()

    # ---- input ----
    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key_Escape, Qt.Key_Q):
            self.stop()
        elif k == Qt.Key_Space:
            self._paused = not self._paused
            self.update()
        elif k in (Qt.Key_Right, Qt.Key_Down):
            self._step_manual(1)
        elif k in (Qt.Key_Left, Qt.Key_Up):
            self._step_manual(-1)

    def mouseMoveEvent(self, ev):
        self.setCursor(Qt.ArrowCursor)
        self._cursor_timer.start()
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, _ev):
        self.stop()
