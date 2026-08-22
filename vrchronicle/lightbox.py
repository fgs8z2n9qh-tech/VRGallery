"""Full-window photo viewer with metadata panel."""
import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import fmt, icons, style, vrclog, widgets


class _LoaderSignals(QObject):
    loaded = Signal(str, QImage)


class _LoadJob(QRunnable):
    def __init__(self, sig, path):
        super().__init__()
        self.sig = sig
        self.path = path

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        img = reader.read()
        self.sig.loaded.emit(self.path, img if not img.isNull() else QImage())


class ImageView(QWidget):
    """Fit-to-window image with wheel zoom + drag pan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None
        self._zoom = 1.0        # 1.0 == fitted
        self._center = QPointF(0.5, 0.5)   # visible center in image fractions
        self._dragging = False
        self._last = None
        self.setCursor(Qt.ArrowCursor)

    def set_pixmap(self, pm):
        self._pm = pm
        self._zoom = 1.0
        self._center = QPointF(0.5, 0.5)
        self.update()

    def clear(self):
        self._pm = None
        self.update()

    def _fit_scale(self):
        if not self._pm or self._pm.width() == 0:
            return 1.0
        return min(self.width() / self._pm.width(), self.height() / self._pm.height())

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(10, 11, 16))
        if not self._pm:
            p.end()
            return
        s = self._fit_scale() * self._zoom
        dw, dh = self._pm.width() * s, self._pm.height() * s
        cx = self.width() / 2 - (self._center.x() - 0.5) * dw
        cy = self.height() / 2 - (self._center.y() - 0.5) * dh
        p.drawPixmap(QRectF(cx - dw / 2, cy - dh / 2, dw, dh), self._pm,
                     QRectF(0, 0, self._pm.width(), self._pm.height()))
        p.end()

    def wheelEvent(self, ev):
        if not self._pm:
            return
        delta = ev.angleDelta().y()
        factor = 1.18 if delta > 0 else 1 / 1.18
        self._zoom = max(1.0, min(9.0, self._zoom * factor))
        if self._zoom <= 1.001:
            self._zoom = 1.0
            self._center = QPointF(0.5, 0.5)
        self._clamp()
        self.setCursor(Qt.OpenHandCursor if self._zoom > 1 else Qt.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if self._zoom > 1.0:
                self._zoom = 1.0
                self._center = QPointF(0.5, 0.5)
            else:
                self._zoom = 2.2
            self._clamp()
            self.setCursor(Qt.OpenHandCursor if self._zoom > 1 else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._zoom > 1.0:
            self._dragging = True
            self._last = ev.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._dragging and self._pm:
            d = ev.position() - self._last
            self._last = ev.position()
            s = self._fit_scale() * self._zoom
            dw, dh = self._pm.width() * s, self._pm.height() * s
            if dw > 0 and dh > 0:
                self._center -= QPointF(d.x() / dw, d.y() / dh)
                self._clamp()
                self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor if self._zoom > 1 else Qt.ArrowCursor)

    def _clamp(self):
        s = self._fit_scale() * self._zoom
        if not self._pm:
            return
        dw, dh = self._pm.width() * s, self._pm.height() * s
        half_w = min(0.5, self.width() / (2 * dw)) if dw > 0 else 0.5
        half_h = min(0.5, self.height() / (2 * dh)) if dh > 0 else 0.5
        self._center.setX(max(half_w, min(1 - half_w, self._center.x())))
        self._center.setY(max(half_h, min(1 - half_h, self._center.y())))


class Lightbox(QWidget):
    """Covers the whole main window. Arrow keys navigate, Esc closes."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.items = []
        self.pos = 0
        self._cache = OrderedDict()      # path -> QPixmap (few full-size)
        self._pending = set()
        self._sig = _LoaderSignals()
        self._sig.loaded.connect(self._on_loaded)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"Lightbox {{ background: {style.PAL['bg']}; }}")
        self.hide()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- left: viewer column ---
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(16, 10, 16, 10)
        top.setSpacing(8)
        self.lab_name = QLabel("")
        self.lab_name.setObjectName("LbTitle")
        self.lab_count = QLabel("")
        self.lab_count.setObjectName("LbDim")
        top.addWidget(self.lab_name)
        top.addWidget(self.lab_count)
        top.addStretch(1)
        self.btn_info = widgets.icon_btn("info", "Details (I)", checkable=True)
        self.btn_info.setChecked(True)
        self.btn_info.toggled.connect(self._toggle_panel)
        self.btn_close = widgets.icon_btn("x", "Close (Esc)", style.PAL["text"], px=20)
        self.btn_close.clicked.connect(self.close_box)
        top.addWidget(self.btn_info)
        top.addWidget(self.btn_close)
        left.addLayout(top)

        self.viewer = ImageView()
        left.addWidget(self.viewer, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 10, 16, 12)
        bottom.setSpacing(6)
        bottom.addStretch(1)
        self.btn_prev = widgets.icon_btn("chevron-left", "Previous (←)", style.PAL["text"], px=20)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_fav = widgets.icon_btn("star", "Favorite (F)", style.PAL["star"], px=19)
        self.btn_fav.clicked.connect(self._fav)
        self.btn_copy = widgets.icon_btn("copy", "Copy to clipboard (Ctrl+C)")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_folder = widgets.icon_btn("folder", "Show in Explorer")
        self.btn_folder.clicked.connect(self._reveal)
        self.btn_send = widgets.icon_btn("send", "Send to Discord")
        self.btn_send.clicked.connect(self._share)
        self.btn_play = widgets.icon_btn("play", "Slideshow from here")
        self.btn_play.clicked.connect(self._slideshow)
        self.btn_trash = widgets.icon_btn("trash", "Recycle (Del)", style.PAL["danger"])
        self.btn_trash.clicked.connect(self._recycle)
        self.btn_next = widgets.icon_btn("chevron-right", "Next (→)", style.PAL["text"], px=20)
        self.btn_next.clicked.connect(lambda: self.step(1))
        for b in (self.btn_prev, self.btn_fav, self.btn_copy, self.btn_folder,
                  self.btn_send, self.btn_play, self.btn_trash, self.btn_next):
            bottom.addWidget(b)
        bottom.addStretch(1)
        left.addLayout(bottom)
        root.addLayout(left, 1)

        # --- right: info panel ---
        self.panel = QFrame()
        self.panel.setObjectName("LightboxPanel")
        self.panel.setFixedWidth(292)
        pan = QVBoxLayout(self.panel)
        pan.setContentsMargins(18, 18, 18, 18)
        pan.setSpacing(6)

        self.p_world_head = QLabel("WORLD")
        self.p_world_head.setObjectName("SectionLabel")
        self.p_world = QLabel("—")
        self.p_world.setObjectName("LbTitle")
        self.p_world.setWordWrap(True)
        self.p_world.setCursor(Qt.PointingHandCursor)
        self.p_world.mouseReleaseEvent = self._world_clicked
        self.p_world_src = QLabel("")
        self.p_world_src.setObjectName("LbKey")
        self.p_instance = QLabel("")
        self.p_instance.setObjectName("LbKey")
        self.btn_world_link = QPushButton("Open on vrchat.com")
        self.btn_world_link.setObjectName("LinkBtn")
        self.btn_world_link.setCursor(Qt.PointingHandCursor)
        self.btn_world_link.clicked.connect(self._world_link)

        self.p_avatar_head = QLabel("WORN")
        self.p_avatar_head.setObjectName("SectionLabel")
        self.p_avatar = QPushButton("")
        self.p_avatar.setObjectName("Chip")
        self.p_avatar.setCursor(Qt.PointingHandCursor)
        self.p_avatar.clicked.connect(self._avatar_clicked)

        self.p_date_head = QLabel("TAKEN")
        self.p_date_head.setObjectName("SectionLabel")
        self.p_date = QLabel("")
        self.p_date.setObjectName("LbDim")
        self.p_date.setWordWrap(True)

        self.p_file_head = QLabel("FILE")
        self.p_file_head.setObjectName("SectionLabel")
        self.p_file = QLabel("")
        self.p_file.setObjectName("LbDim")
        self.p_file.setWordWrap(True)

        self.p_people_head = QLabel("WHO WAS THERE")
        self.p_people_head.setObjectName("SectionLabel")
        self.chips_holder = QWidget()
        self.chips_lay = widgets.FlowLayout(self.chips_holder, 0, 6, 6)

        pan.addWidget(self.p_world_head)
        pan.addWidget(self.p_world)
        pan.addWidget(self.p_world_src)
        pan.addWidget(self.p_instance)
        pan.addWidget(self.btn_world_link, 0, Qt.AlignLeft)
        pan.addSpacing(10)
        pan.addWidget(self.p_date_head)
        pan.addWidget(self.p_date)
        pan.addSpacing(10)
        pan.addWidget(self.p_avatar_head)
        pan.addWidget(self.p_avatar, 0, Qt.AlignLeft)
        pan.addSpacing(10)
        pan.addWidget(self.p_file_head)
        pan.addWidget(self.p_file)
        pan.addSpacing(10)
        pan.addWidget(self.p_people_head)
        pan.addWidget(self.chips_holder)
        pan.addStretch(1)
        root.addWidget(self.panel)

    # ---------- open / close ----------
    def open(self, items, pos, source_page=None):
        self.items = list(items)
        self.pos = max(0, min(pos, len(self.items) - 1))
        self.source_page = source_page
        self.setGeometry(self.main.centralWidget().rect())
        self.raise_()
        self.show()
        self.setFocus()
        self._fade_in()
        self._show_current()

    def _fade_in(self):
        from PySide6.QtCore import QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(170)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def close_box(self):
        self.hide()
        self.viewer.clear()

    def current(self):
        return self.items[self.pos] if self.items else None

    def step(self, d):
        if not self.items:
            return
        self.pos = (self.pos + d) % len(self.items)
        self._show_current()

    def remove_current(self):
        if not self.items:
            return
        del self.items[self.pos]
        if not self.items:
            self.close_box()
            return
        self.pos %= len(self.items)
        self._show_current()

    # ---------- display ----------
    def _show_current(self):
        it = self.current()
        if not it:
            return
        self.lab_name.setText(os.path.basename(it.path))
        self.lab_count.setText(f"{self.pos + 1} / {len(self.items)}")
        pm = self._get_pixmap(it.path)
        if pm:
            self.viewer.set_pixmap(pm)
        else:
            self.viewer.clear()
        self._refresh_fav_icon()
        self._fill_panel(it)
        for d in (-1, 1):
            if len(self.items) > 1:
                self._prefetch(self.items[(self.pos + d) % len(self.items)].path)

    def _refresh_fav_icon(self):
        it = self.current()
        fav = bool(it and it.favorite)
        self.btn_fav.setIcon(icons.qicon("star", style.PAL["star"], 19, 2.0, 1.9,
                                         style.PAL["star"] if fav else None))

    def _fill_panel(self, it):
        row, players = self.main.db.photo(it.id)
        wname = (row["world_name"] if row else None) or "Unknown world"
        self.p_world.setText(wname)
        src = row["meta_source"] if row else "none"
        self.p_world_src.setText({"vrcx": "source: VRCX metadata",
                                  "log": "source: VRChat log"}.get(src, "no log data"))
        itype = (row["instance_type"] if row else "") or ""
        if itype:
            label = vrclog.INSTANCE_LABELS.get(itype, itype)
            private = itype in vrclog.PRIVATE_INSTANCES
            self.p_instance.setText(("🔒 " if private else "") + label + " instance")
            self.p_instance.setStyleSheet(
                "color:%s; font-size:11px;" % (style.PAL["star"] if private
                                               else style.PAL["faint"]))
        self.p_instance.setVisible(bool(itype))
        self.btn_world_link.setVisible(bool(it.world_id))
        avatar = row["avatar_name"] if row else None
        self.p_avatar_head.setVisible(bool(avatar))
        self.p_avatar.setVisible(bool(avatar))
        if avatar:
            self.p_avatar.setText(avatar)
        self.p_date.setText(fmt.dt_label(it.taken_at) or "—")
        parts = []
        if row and row["width"]:
            parts.append(f'{row["width"]}×{row["height"]}')
        parts.append(fmt.human_size(it.filesize))
        self.p_file.setText("  ·  ".join(parts))
        self.p_file.setToolTip(it.path)
        # people chips
        while self.chips_lay.count():
            w = self.chips_lay.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()
        selfn = self.main.cfg.self_names
        shown = 0
        for name, _uid in players:
            b = QPushButton(name + (" · you" if name in selfn else ""))
            b.setObjectName("ChipSelf" if name in selfn else "Chip")
            b.setCursor(Qt.PointingHandCursor)
            if name not in selfn:
                b.clicked.connect(lambda _c=False, n=name: self._person_clicked(n))
            self.chips_lay.addWidget(b)
            shown += 1
        self.p_people_head.setVisible(shown > 0)
        self.chips_holder.setVisible(shown > 0)

    # ---------- async full-size loading ----------
    def _get_pixmap(self, path):
        pm = self._cache.get(path)
        if pm is not None:
            self._cache.move_to_end(path)
            return pm
        self._prefetch(path)
        return None

    def _prefetch(self, path):
        if path in self._cache or path in self._pending:
            return
        self._pending.add(path)
        QThreadPool.globalInstance().start(_LoadJob(self._sig, path))

    def _on_loaded(self, path, img):
        self._pending.discard(path)
        if img.isNull():
            return
        pm = QPixmap.fromImage(img)
        self._cache[path] = pm
        while len(self._cache) > 5:
            self._cache.popitem(last=False)
        it = self.current()
        if self.isVisible() and it and it.path == path:
            self.viewer.set_pixmap(pm)

    # ---------- actions ----------
    def _fav(self):
        it = self.current()
        if it:
            self.main.act_favorite([it.id])
            self._refresh_fav_icon()

    def _copy(self):
        it = self.current()
        if it:
            self.main.act_copy(it)

    def _reveal(self):
        it = self.current()
        if it:
            self.main.act_reveal(it)

    def _share(self):
        it = self.current()
        if it:
            self.main.act_share(it)

    def _slideshow(self):
        if self.items:
            self.main.start_slideshow(self.items, self.pos)

    def _recycle(self):
        it = self.current()
        if it:
            self.main.act_recycle([it], after=self.remove_current)

    def _world_clicked(self, _ev):
        it = self.current()
        if it and it.world_id:
            self.close_box()
            self.main.push_world(it.world_id, it.world_name)

    def _person_clicked(self, name):
        self.close_box()
        self.main.push_person(name)

    def _avatar_clicked(self):
        name = self.p_avatar.text().strip()
        if name:
            self.close_box()
            self.main.push_avatar(name)

    def _world_link(self):
        it = self.current()
        if it:
            self.main.act_world_link(it)

    def _toggle_panel(self, on):
        self.panel.setVisible(on)

    # ---------- events ----------
    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.close_box()
        elif k in (Qt.Key_Left, Qt.Key_Up):
            self.step(-1)
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.step(1)
        elif k == Qt.Key_F:
            self._fav()
        elif k == Qt.Key_I:
            self.btn_info.toggle()
        elif k == Qt.Key_Delete:
            self._recycle()
        elif k == Qt.Key_C and ev.modifiers() & Qt.ControlModifier:
            self._copy()
        else:
            super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
