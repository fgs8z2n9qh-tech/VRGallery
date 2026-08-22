"""Full-window photo viewer with metadata panel."""
import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import fmt, icons, style, vrclog, widgets, winutil


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
    """Fit-to-window image with wheel zoom, drag pan, and people tags.

    A tag is a name at a fraction of the image, so it stays put at any zoom or
    window size. Hovering near one names the person, the way a photo tag works
    on any social app; in tagging mode a click places one instead.
    """

    tag_placed = Signal(float, float)     # image-space fraction
    tag_clicked = Signal(str)

    HIT_PX = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tags = []            # (name, x, y)
        self._hover_tag = -1
        self._show_all_tags = False
        self._tagging = False
        self._pm = None
        self._message = ""
        self._zoom = 1.0        # 1.0 == fitted
        self._center = QPointF(0.5, 0.5)   # visible center in image fractions
        self._dragging = False
        self._last = None
        self.setCursor(Qt.ArrowCursor)

    def set_pixmap(self, pm):
        self._pm = pm
        self._message = ""
        self._zoom = 1.0
        self._center = QPointF(0.5, 0.5)
        self.update()

    def show_message(self, text):
        self._pm = None
        self._message = text
        self.update()

    def clear(self):
        self._pm = None
        self._message = ""
        self.update()

    def set_tags(self, tags):
        self._tags = list(tags or [])
        self._hover_tag = -1
        self.update()

    def set_show_all_tags(self, on):
        self._show_all_tags = bool(on)
        self.update()

    def set_tagging(self, on):
        self._tagging = bool(on)
        self.setCursor(Qt.CrossCursor if on else
                       (Qt.OpenHandCursor if self._zoom > 1 else Qt.ArrowCursor))
        self.update()

    def _fit_scale(self):
        if not self._pm or self._pm.width() == 0:
            return 1.0
        return min(self.width() / self._pm.width(), self.height() / self._pm.height())

    def _image_rect(self):
        """Where the image is actually painted, in widget coordinates."""
        if not self._pm:
            return None
        s = self._fit_scale() * self._zoom
        dw, dh = self._pm.width() * s, self._pm.height() * s
        cx = self.width() / 2 - (self._center.x() - 0.5) * dw
        cy = self.height() / 2 - (self._center.y() - 0.5) * dh
        return QRectF(cx - dw / 2, cy - dh / 2, dw, dh)

    def _tag_point(self, x, y):
        r = self._image_rect()
        if r is None:
            return None
        return QPointF(r.x() + x * r.width(), r.y() + y * r.height())

    def _tag_at(self, pos):
        for i, (_name, x, y) in enumerate(self._tags):
            pt = self._tag_point(x, y)
            if pt is not None and (pt - pos).manhattanLength() <= self.HIT_PX:
                return i
        return -1

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(10, 11, 16))
        if not self._pm:
            if self._message:
                from PySide6.QtGui import QFont
                f = QFont()
                f.setPointSizeF(11)
                p.setFont(f)
                p.setPen(QColor(style.PAL["dim"]))
                p.drawText(self.rect(), Qt.AlignCenter, self._message)
            p.end()
            return
        rect = self._image_rect()
        p.drawPixmap(rect, self._pm, QRectF(0, 0, self._pm.width(), self._pm.height()))
        self._paint_tags(p)
        p.end()

    def _paint_tags(self, p):
        if not self._tags:
            return
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont()
        f.setPointSizeF(9.5)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        p.setFont(f)
        show_all = self._show_all_tags or self._tagging
        for i, (name, x, y) in enumerate(self._tags):
            pt = self._tag_point(x, y)
            if pt is None:
                continue
            hovered = (i == self._hover_tag)
            # the dot is always there so a photo announces it has tags
            p.setPen(QPen(QColor(255, 255, 255, 230), 2))
            p.setBrush(QColor(0, 0, 0, 110))
            r = 9 if hovered else 6
            p.drawEllipse(pt, r, r)
            if not (hovered or show_all):
                continue
            tw = fm.horizontalAdvance(name)
            bw, bh = tw + 20, fm.height() + 12
            bx = min(max(6.0, pt.x() - bw / 2), self.width() - bw - 6)
            by = pt.y() + 16
            if by + bh > self.height() - 6:
                by = pt.y() - 16 - bh
            box = QRectF(bx, by, bw, bh)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 14, 20, 225))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(233, 236, 245))
            p.drawText(box, Qt.AlignCenter, name)

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
        if ev.button() != Qt.LeftButton:
            return
        if self._tagging and self._pm:
            r = self._image_rect()
            if r is not None and r.contains(ev.position()):
                fx = (ev.position().x() - r.x()) / max(1.0, r.width())
                fy = (ev.position().y() - r.y()) / max(1.0, r.height())
                self.tag_placed.emit(fx, fy)
            return
        hit = self._tag_at(ev.position())
        if hit >= 0:
            self.tag_clicked.emit(self._tags[hit][0])
            return
        if self._zoom > 1.0:
            self._dragging = True
            self._last = ev.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if not self._dragging:
            hit = self._tag_at(ev.position())
            if hit != self._hover_tag:
                self._hover_tag = hit
                if not self._tagging:
                    self.setCursor(Qt.PointingHandCursor if hit >= 0 else
                                   (Qt.OpenHandCursor if self._zoom > 1
                                    else Qt.ArrowCursor))
                self.update()
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
        self.btn_tag = widgets.icon_btn("users", "Tag someone in the photo (T)",
                                        checkable=True)
        self.btn_tag.toggled.connect(self._toggle_tagging)
        top.addWidget(self.btn_tag)
        self.btn_info = widgets.icon_btn("info", "Details (I)", checkable=True)
        self.btn_info.setChecked(True)
        self.btn_info.toggled.connect(self._toggle_panel)
        self.btn_close = widgets.icon_btn("x", "Close (Esc)", style.PAL["text"], px=20)
        self.btn_close.clicked.connect(self.close_box)
        top.addWidget(self.btn_info)
        top.addWidget(self.btn_close)
        left.addLayout(top)

        self.viewer = ImageView()
        self.viewer.tag_placed.connect(self._place_tag)
        self.viewer.tag_clicked.connect(self._person_clicked)
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

        self.p_rating_head = QLabel("RATING")
        self.p_rating_head.setObjectName("SectionLabel")
        self.rating_row = QWidget()
        rl = QHBoxLayout(self.rating_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self._stars = []
        for i in range(1, 6):
            b = widgets.icon_btn("star", f"Rate {i} (press {i})", style.PAL["faint"],
                                 px=17)
            b.clicked.connect(lambda _c=False, n=i: self._rate(n))
            self._stars.append(b)
            rl.addWidget(b)
        rl.addStretch(1)

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

        self.p_tags_head = QLabel("TAGGED IN FRAME")
        self.p_tags_head.setObjectName("SectionLabel")
        self.tags_holder = QWidget()
        self.tags_lay = widgets.FlowLayout(self.tags_holder, 0, 6, 6)
        self.p_tags_hint = QLabel("Right-click a tag to remove it")
        self.p_tags_hint.setObjectName("LbKey")

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
        pan.addWidget(self.p_rating_head)
        pan.addWidget(self.rating_row)
        pan.addSpacing(10)
        pan.addWidget(self.p_avatar_head)
        pan.addWidget(self.p_avatar, 0, Qt.AlignLeft)
        pan.addSpacing(10)
        pan.addWidget(self.p_file_head)
        pan.addWidget(self.p_file)
        pan.addSpacing(10)
        pan.addWidget(self.p_tags_head)
        pan.addWidget(self.tags_holder)
        pan.addWidget(self.p_tags_hint)
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
        if getattr(it, "is_video", False):
            # recordings are never decoded here; the system player owns them
            self.viewer.show_message("Recording — press Enter to open it in your player")
        else:
            pm = self._get_pixmap(it.path)
            if pm:
                self.viewer.set_pixmap(pm)
            else:
                self.viewer.clear()
        self._refresh_fav_icon()
        self.refresh_rating()
        self._load_tags()
        self._fill_panel(it)
        for d in (-1, 1):
            if len(self.items) > 1:
                self._prefetch(self.items[(self.pos + d) % len(self.items)].path)

    def _refresh_fav_icon(self):
        it = self.current()
        fav = bool(it and it.favorite)
        self.btn_fav.setIcon(icons.qicon("star", style.PAL["star"], 19, 2.0, 1.9,
                                         style.PAL["star"] if fav else None))

    def refresh_rating(self):
        it = self.current()
        stars = getattr(it, "rating", 0) or 0
        for i, b in enumerate(self._stars, start=1):
            lit = i <= stars
            b.setIcon(icons.qicon("star", style.PAL["star"] if lit else style.PAL["faint"],
                                  17, 2.0, 1.8, style.PAL["star"] if lit else None))

    def _rate(self, stars):
        it = self.current()
        if it:
            # clicking the star that is already the rating clears it
            self.main.act_rate([it.id], 0 if (it.rating or 0) == stars else stars)

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
        # tags placed in the frame
        while self.tags_lay.count():
            w = self.tags_lay.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()
        tags = self.main.db.photo_tags(it.id)
        for name, _x, _y in tags:
            b = QPushButton(name)
            b.setObjectName("Chip")
            b.setCursor(Qt.PointingHandCursor)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.clicked.connect(lambda _c=False, n=name: self._person_clicked(n))
            b.customContextMenuRequested.connect(
                lambda _p, n=name: self._remove_tag(n))
            self.tags_lay.addWidget(b)
        self.p_tags_head.setVisible(bool(tags))
        self.tags_holder.setVisible(bool(tags))
        self.p_tags_hint.setVisible(bool(tags))

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

    # ---------- in-frame tags ----------
    def _toggle_tagging(self, on):
        self.viewer.set_tagging(on)
        if on:
            self.main.toast("Click where somebody is in the photo.", "info")

    def _load_tags(self):
        it = self.current()
        self.viewer.set_tags(self.main.db.photo_tags(it.id) if it else [])

    def _place_tag(self, fx, fy):
        it = self.current()
        if not it:
            return
        from PySide6.QtWidgets import QInputDialog, QMenu
        taken = {n for n, _x, _y in self.main.db.photo_tags(it.id)}
        # people the logs already say were in this instance come first: usually
        # the answer is one of them, and typing a VRChat name is a chore
        _row, players = self.main.db.photo(it.id)
        known = [n for n, _u in players if n not in taken]
        recent = [n for n in self.main.db.tag_names(24)
                  if n not in taken and n not in known]

        menu = QMenu(self)
        for name in known:
            menu.addAction(name).setData(name)
        if known and recent:
            menu.addSeparator()
        for name in recent[:8]:
            menu.addAction(name).setData(name)
        if menu.actions():
            menu.addSeparator()
        other = menu.addAction(icons.qicon("plus", style.PAL["dim"], 16),
                               "Someone else…")
        chosen = menu.exec(self.viewer.mapToGlobal(
            self.viewer._tag_point(fx, fy).toPoint()))
        if chosen is None:
            return
        if chosen is other:
            name, ok = QInputDialog.getText(self, "Tag someone", "Name:")
            name = (name or "").strip()
            if not (ok and name):
                return
        else:
            name = chosen.data()
        self.main.act_tag(it.id, name, fx, fy)
        self._load_tags()

    def _remove_tag(self, name):
        it = self.current()
        if it:
            self.main.db.remove_photo_tag(it.id, name)
            self._load_tags()
            self._fill_panel(it)
            self.main.toast(f"Removed the tag for {name}.", "ok")

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
        if k in (Qt.Key_Return, Qt.Key_Enter):
            it = self.current()
            if it and getattr(it, "is_video", False):
                winutil.open_file(it.path)
            return
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
        elif k == Qt.Key_T:
            self.btn_tag.toggle()
        elif k == Qt.Key_Delete:
            self._recycle()
        elif k == Qt.Key_C and ev.modifiers() & Qt.ControlModifier:
            self._copy()
        elif Qt.Key_0 <= k <= Qt.Key_5:
            it = self.current()
            if it:
                self.main.act_rate([it.id], k - Qt.Key_0)
        else:
            super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
