"""Full-window photo viewer with metadata panel."""
import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import facesig, fmt, icons, style, vrclog, widgets, winutil


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

    tag_placed = Signal(float, float, float, float)   # box in image fractions
    tag_context = Signal(str)                         # right-clicked somebody's box
    tag_clicked = Signal(str)

    DEFAULT_BOX = 0.11        # fraction of image width when you just click
    DRAG_SLOP = 5             # widget px: below this the gesture was a click
    MIN_DRAWN = 10            # widget px: a stored box is never thinner

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tags = []            # (name, x, y, w, h)
        self._hover_tag = -1
        self._show_all_tags = False
        self._tagging = False
        self._draw_from = None     # drag origin while drawing a box
        self._draw_to = None
        self._pinned_tag = -1      # a tag whose label the user clicked to keep open
        self._pm = None
        self._message = ""
        self._zoom = 1.0        # 1.0 == fitted
        self._center = QPointF(0.5, 0.5)   # visible center in image fractions
        self._dragging = False
        self._last = None
        self._want_tagging = False   # asked for before the image finished loading
        self.setCursor(Qt.ArrowCursor)
        # without this Qt only sends mouseMoveEvent while a button is held, and
        # pointing at somebody would never reveal their name
        self.setMouseTracking(True)

    def set_pixmap(self, pm):
        self._pm = pm
        self._message = ""
        self._zoom = 1.0
        self._center = QPointF(0.5, 0.5)
        if self._want_tagging:       # T was pressed while the photo was decoding
            self.set_tagging(True)
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
        self._pinned_tag = -1
        self._draw_from = self._draw_to = None
        # the pointer has not moved, so nothing will clear a stale one for us
        self.setToolTip("")
        self.update()

    def set_show_all_tags(self, on):
        self._show_all_tags = bool(on)
        self.update()

    def set_tagging(self, on):
        self._want_tagging = bool(on)
        self._tagging = bool(on) and self._pm is not None
        on = self._tagging
        if on:
            self.setToolTip("")     # the badge is gone; its tooltip must go too
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

    def default_box(self):
        """A head-sized box: square on screen, so the fractions differ by aspect.

        Clamped, because on an extreme panorama a square would be taller than
        the photo itself.
        """
        w = self.DEFAULT_BOX
        if self._pm and self._pm.height():
            h = w * (self._pm.width() / self._pm.height())
            if h > 1.0:                      # wider than about 9:1
                return min(1.0, w / h), 1.0
            return w, h
        return w, w

    def _tag_box(self, tag):
        """Widget-space rectangle for a stored tag, tolerating legacy points."""
        r = self._image_rect()
        if r is None:
            return None
        _name, x, y, w, h = tag
        if w <= 0 or h <= 0:                 # written before tags had a size
            w, h = self.default_box()
            x, y = x - w / 2, y - h / 2      # the old value was the centre
            x = max(0.0, min(1.0 - w, x))    # and it could sit near an edge
            y = max(0.0, min(1.0 - h, y))
        return QRectF(r.x() + x * r.width(), r.y() + y * r.height(),
                      w * r.width(), h * r.height())

    def _badge_visible(self):
        """The badge is a real control, so it is on screen whenever it works."""
        return bool(self._tags) and not self._tagging and self._pm is not None

    def _badge_rect(self):
        r = self._image_rect()
        if r is None or not self._badge_visible():
            return None
        w, h = 60, 30
        return QRectF(max(6.0, r.x() + 12),
                      min(self.height() - h - 6, r.bottom() - h - 12), w, h)

    def _paint_tag_badge(self, p, fm):
        box = self._badge_rect()
        if box is None:
            return
        # lit while everyone is shown, so it never looks like it vanished
        on = self._show_all_tags
        p.setPen(QPen(QColor(255, 255, 255, 60), 1) if on else Qt.NoPen)
        p.setBrush(QColor(style.ACTIVE["a"]) if on else QColor(12, 14, 20, 190))
        p.drawRoundedRect(box, 15, 15)
        fg = "#0b0e14" if on else "#e9ecf5"
        glyph = icons.pixmap("users", fg, 15, self.devicePixelRatioF())
        p.drawPixmap(int(box.x() + 11), int(box.center().y() - 7.5), glyph)
        p.setPen(QColor(fg))
        p.drawText(QRectF(box.x() + 30, box.y(), 24, box.height()),
                   Qt.AlignCenter, str(len(self._tags)))

    def _tag_at(self, pos):
        # topmost first, so a small box drawn inside a big one stays reachable
        best, best_area = -1, None
        for i, tag in enumerate(self._tags):
            box = self._tag_box(tag)
            if box is not None and box.adjusted(-4, -4, 4, 4).contains(pos):
                area = box.width() * box.height()
                if best_area is None or area < best_area:
                    best, best_area = i, area
        return best

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
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont()
        f.setPointSizeF(9.5)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        p.setFont(f)

        # the box being dragged out right now
        if self._draw_from is not None and self._draw_to is not None:
            live = QRectF(self._draw_from, self._draw_to).normalized()
            p.setPen(QPen(QColor(255, 255, 255, 230), 2, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 24))
            p.drawRoundedRect(live, 6, 6)

        # Boxes stay out of the way: the photo is the point. A small badge says
        # the photo has tags, and pointing at somebody names them.
        show_all = self._show_all_tags or self._tagging
        for i, tag in enumerate(self._tags):
            box = self._tag_box(tag)
            if box is None or not box.intersects(QRectF(self.rect())):
                continue        # scrolled off: no outline, and no orphan label
            name = tag[0]
            hovered = (i == self._hover_tag) or (i == self._pinned_tag)
            if not (hovered or show_all):
                continue
            # a dark stroke underneath, so the box is still visible against a
            # snowy world or a white sky
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 90 if hovered else 60),
                          4.4 if hovered else 3.4))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(QColor(255, 255, 255, 235 if hovered else 170),
                          2.4 if hovered else 1.6))
            p.setBrush(QColor(255, 255, 255, 22) if hovered else Qt.NoBrush)
            p.drawRoundedRect(box, 6, 6)
            tw = fm.horizontalAdvance(name)
            bw, bh = tw + 20, fm.height() + 10
            bx = min(max(6.0, box.center().x() - bw / 2), self.width() - bw - 6)
            by = box.bottom() + 8
            if by + bh > self.height() - 6:
                by = box.top() - 8 - bh
            # zoomed in far enough, the box swallows the viewport and neither
            # position is on screen — the name still has to be readable
            by = min(max(6.0, by), self.height() - bh - 6)
            label = QRectF(bx, by, bw, bh)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 14, 20, 228))
            p.drawRoundedRect(label, 8, 8)
            p.setPen(QColor(233, 236, 245))
            p.drawText(label, Qt.AlignCenter, name)

        # last, so a box drawn over the corner can never hide the control
        self._paint_tag_badge(p, fm)

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
                self._draw_from = ev.position()
                self._draw_to = ev.position()
                self.update()
            return
        badge = self._badge_rect()
        if badge is not None and badge.contains(ev.position()):
            self.set_show_all_tags(not self._show_all_tags)
            return
        hit = self._tag_at(ev.position())
        if hit >= 0:
            # clicking a box keeps its name on screen — it must not navigate
            # away, which would close the photo you are looking at
            self._pinned_tag = -1 if self._pinned_tag == hit else hit
            self._hover_tag = hit
            self.update()
        else:
            self._pinned_tag = -1
        # panning still has to work: zoomed in far enough a single box can cover
        # the whole viewport, and then every press would land on it
        if self._zoom > 1.0:
            self._dragging = True
            self._last = ev.position()
            self.setCursor(Qt.ClosedHandCursor)

    def contextMenuEvent(self, ev):
        """Right-clicking somebody's box is how you get rid of it."""
        if self._tagging:
            return
        hit = self._tag_at(QPointF(ev.pos()))
        if hit < 0:
            return
        self._hover_tag = hit          # keep the name up while the menu is open
        self.update()
        ev.accept()
        self.tag_context.emit(self._tags[hit][0])

    def mouseMoveEvent(self, ev):
        if self._draw_from is not None:
            self._draw_to = ev.position()
            self.update()
            return
        if not self._dragging:
            hit = self._tag_at(ev.position())
            badge = self._badge_rect()
            over_badge = badge is not None and badge.contains(ev.position())
            if hit != self._hover_tag:
                self._hover_tag = hit
                self.update()
            if not self._tagging:
                self.setCursor(Qt.PointingHandCursor if (hit >= 0 or over_badge) else
                               (Qt.OpenHandCursor if self._zoom > 1
                                else Qt.ArrowCursor))
                self.setToolTip("Hide everyone" if over_badge and self._show_all_tags
                                else "Show everyone tagged" if over_badge else "")
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
        if ev.button() == Qt.LeftButton and self._draw_from is not None:
            start, end = self._draw_from, ev.position()
            self._draw_from = self._draw_to = None
            self.update()
            r = self._image_rect()
            if r is None:
                return
            raw = QRectF(start, end).normalized()
            # Click or drag is a question about the GESTURE, so it is measured
            # in widget pixels. Measuring it as a fraction of the image made
            # every small head snap to the default size -- and zooming in made
            # that worse, because the fraction only got smaller.
            drew = max(raw.width(), raw.height()) >= self.DRAG_SLOP
            if drew:
                # keep the box that was drawn, however small it is on the
                # photo, but never store a sliver
                if raw.width() < self.MIN_DRAWN:
                    g = (self.MIN_DRAWN - raw.width()) / 2
                    raw.adjust(-g, 0, g, 0)
                if raw.height() < self.MIN_DRAWN:
                    g = (self.MIN_DRAWN - raw.height()) / 2
                    raw.adjust(0, -g, 0, g)
                # a drag that overshoots into the letterbox must not become a
                # box covering the whole photo
                box = raw.intersected(r)
                drew = box.width() > 0 and box.height() > 0
            if drew:
                fx = (box.x() - r.x()) / max(1.0, r.width())
                fy = (box.y() - r.y()) / max(1.0, r.height())
                fw = box.width() / max(1.0, r.width())
                fh = box.height() / max(1.0, r.height())
            else:
                # a plain click means "a head goes here", not a zero-size box.
                # anchor on the press, which is always on the image
                dw, dh = self.default_box()
                cx = (start.x() - r.x()) / max(1.0, r.width())
                cy = (start.y() - r.y()) / max(1.0, r.height())
                fx, fy, fw, fh = cx - dw / 2, cy - dh / 2, dw, dh
            # keep the box on the image
            fw = min(fw, 1.0)
            fh = min(fh, 1.0)
            fx = max(0.0, min(1.0 - fw, fx))
            fy = max(0.0, min(1.0 - fh, fy))
            self.tag_placed.emit(fx, fy, fw, fh)
            return
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
        self._retag_name = ""            # whose box is being redrawn, if any
        self._retag_for = None           # ...and on which photo it was started
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
        self.viewer.tag_context.connect(self._tag_menu)
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

        # Only shown when the shot is not yours: on your own library that is
        # every photo, and a "Shot by <you>" on all 1900 of them is noise.
        self.p_shotby_head = QLabel("SHOT BY")
        self.p_shotby_head.setObjectName("SectionLabel")
        self.p_shotby = QPushButton("")
        self.p_shotby.setObjectName("Chip")
        self.p_shotby.setCursor(Qt.PointingHandCursor)
        self.p_shotby.clicked.connect(self._shotby_clicked)

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
        self.p_tags_hint = QLabel("Point at somebody in the photo to see their name. "
                                  "Right-click their box to move or remove it · "
                                  "click a name here to open their photos")
        self.p_tags_hint.setWordWrap(True)
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
        pan.addWidget(self.p_shotby_head)
        pan.addWidget(self.p_shotby)
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

    def _shotby_clicked(self):
        name = self.p_shotby.text().strip()
        if name:
            self.main.push_person(name)
            self.close()

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
        self.p_world_src.setText({"vrchat": "source: VRChat photo metadata",
                                  "vrcx": "source: VRCX metadata",
                                  "log": "source: VRChat log"}.get(src, "no log data"))
        itype = (row["instance_type"] if row else "") or ""
        if itype:
            label = vrclog.INSTANCE_LABELS.get(itype, itype)
            private = itype in vrclog.PRIVATE_INSTANCES
            region = (row["region"] if row else "") or ""
            where = f"  ·  {vrclog.REGION_NAMES.get(region, region.upper())}" if region else ""
            self.p_instance.setText(
                ("🔒 " if private else "") + label + " instance" + where)
            self.p_instance.setStyleSheet(
                "color:%s; font-size:11px;" % (style.PAL["star"] if private
                                               else style.PAL["faint"]))
        self.p_instance.setVisible(bool(itype))
        self.btn_world_link.setVisible(bool(it.world_id))
        shot_by = (row["author_name"] if row and "author_name" in row.keys() else None)
        mine = {n.lower() for n in (self.main.cfg.self_names or [])}
        show_author = bool(shot_by) and shot_by.lower() not in mine
        self.p_shotby_head.setVisible(show_author)
        self.p_shotby.setVisible(show_author)
        if show_author:
            self.p_shotby.setText(shot_by)
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
        for name, _x, _y, _w, _h in tags:
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
        if not on:
            self._retag_name = ""
            self._retag_for = None
        elif self._retag_name:
            self.main.toast(f"Drag the new box for {self._retag_name}.", "info")
        else:
            self.main.toast("Drag a box around someone's head — or just click for a "
                            "default-sized one.", "info")

    def _tag_menu(self, name):
        """Right-clicked a box on the photo: open, redraw, or remove it."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        a_open = m.addAction(icons.qicon("users", style.PAL["dim"], 16),
                             f"Open {name}'s photos")
        a_move = m.addAction(icons.qicon("edit", style.PAL["dim"], 16),
                             "Redraw this box")
        m.addSeparator()
        a_del = m.addAction(icons.qicon("trash", style.PAL["danger"], 16),
                            f"Remove the tag for {name}")
        chosen = m.exec(QCursor.pos())
        if chosen is a_del:
            self._remove_tag(name)
        elif chosen is a_open:
            self._person_clicked(name)
        elif chosen is a_move:
            it = self.current()
            self._retag_name = name
            self._retag_for = it.id if it else None
            self.btn_tag.setChecked(True)

    def _load_tags(self):
        it = self.current()
        self.viewer.set_tags(self.main.db.photo_tags(it.id) if it else [])
        # a half-finished "redraw" must not follow you to the next photo, not
        # even when that photo happens to have somebody of the same name on it
        if self._retag_name and (not it or it.id != self._retag_for):
            self._retag_name = ""
            self._retag_for = None
            self.btn_tag.setChecked(False)

    def _place_tag(self, fx, fy, fw, fh):
        it = self.current()
        if not it or getattr(it, "is_video", False):
            return
        if self._retag_name and it.id == self._retag_for:
            name, self._retag_name = self._retag_name, ""   # name already known
            self._retag_for = None
            self.main.act_tag(it.id, name, fx, fy, fw, fh,
                              sig=self._box_signature(it, fx, fy, fw, fh))
            self._load_tags()
            self._fill_panel(it)
            self.btn_tag.setChecked(False)
            self.main.toast(f"Moved the box for {name}.", "ok")
            return
        anchor = self.viewer._tag_point(fx + fw / 2, fy + fh)
        if anchor is None:            # the image is not on screen yet
            return
        from PySide6.QtWidgets import QInputDialog, QMenu
        taken = {t[0] for t in self.main.db.photo_tags(it.id)}
        # people the logs already say were in this instance come first: usually
        # the answer is one of them, and typing a VRChat name is a chore
        _row, players = self.main.db.photo(it.id)
        known = [n for n, _u in players if n not in taken]
        recent = [n for n in self.main.db.tag_names(24)
                  if n not in taken and n not in known]

        # Who the app thinks is in the box. Only ever a pre-selection: measured
        # on this library it speaks for seven boxes in ten and is right for
        # nineteen in twenty of those, and when it is wrong the menu is still
        # the menu. Restricted to the people the logs put in the instance
        # whenever there are any -- that restriction is most of why it works.
        sig = self._box_signature(it, fx, fy, fw, fh)
        guess = self._guess_name(sig, known or recent)

        menu = self._who_menu(known, recent, guess)
        if menu.actions():
            menu.addSeparator()
        other = menu.addAction(icons.qicon("plus", style.PAL["dim"], 16),
                               "Someone else…")
        chosen = menu.exec(self.viewer.mapToGlobal(anchor.toPoint()))
        if chosen is None:
            return
        if chosen is other:
            name, ok = QInputDialog.getText(self, "Tag someone", "Name:")
            name = (name or "").strip()
            if not (ok and name):
                return
        else:
            name = chosen.data()
        self.main.act_tag(it.id, name, fx, fy, fw, fh, sig=sig)
        self._load_tags()
        self._fill_panel(it)

    def _who_menu(self, known, recent, guess):
        """The who-is-this menu: people the logs put here, then people tagged
        lately, with the guess moved to the top and shown in bold.

        Its own method so it can be looked at without being opened -- QMenu.exec
        blocks on a real popup, and a test that fakes that away is testing the
        fake. It also puts the ordering in one place instead of leaving half of
        it at the call site.
        """
        from PySide6.QtWidgets import QMenu

        def lift(names):
            return ([guess] + [n for n in names if n != guess]
                    if guess in names else list(names))

        known, recent = lift(known), lift(recent)[:8]
        menu = QMenu(self)
        suggested = None
        for i, group in enumerate((known, recent)):
            if i and known and recent:
                menu.addSeparator()
            for name in group:
                act = menu.addAction(name)
                act.setData(name)
                if name == guess:
                    suggested = act
        if suggested is not None:
            menu.setDefaultAction(suggested)     # bold, and the one Enter takes
            menu.setActiveAction(suggested)
        return menu

    def _box_signature(self, it, fx, fy, fw, fh):
        """The colour fingerprint of the box just drawn, or None.

        Off the pixmap already on screen when there is one: decoding the
        original again costs about 90 ms, and this runs between the mouse
        coming up and the menu appearing.
        """
        try:
            pm = self._cache.get(it.path)
            if pm is not None and not pm.isNull():
                return facesig.signature(pm.toImage(), fx, fy, fw, fh)
            return facesig.signature_for_path(it.path, fx, fy, fw, fh)
        except Exception:
            return None           # a suggestion is never worth an exception

    def _guess_name(self, sig, pool):
        """Who that signature looks like, or None when it is not sure enough."""
        if not sig or not pool:
            return None
        try:
            name, sure = facesig.suggest(sig, self.main.db.tag_sigs_for(pool))
            return name if sure else None
        except Exception:
            return None

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
