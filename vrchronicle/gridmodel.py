"""Photo grid: model (day headers + photos), thumbnail cache, delegate, view."""
import time
from collections import OrderedDict

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRect, QRectF, QSize,
                            Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QAbstractItemView

from . import fmt, icons, style

KindRole = Qt.UserRole + 1
ItemRole = Qt.UserRole + 2

KIND_HEADER = 0
KIND_PHOTO = 1


class PhotoItem:
    __slots__ = ("id", "path", "taken_at", "day", "world_id", "world_name",
                 "favorite", "width", "height", "filesize", "mtime", "meta_source",
                 "avatar_name", "session_id", "instance_type", "rating", "is_video")

    def __init__(self, row):
        keys = row.keys()
        self.id = row["id"]
        self.path = row["path"]
        self.taken_at = row["taken_at"]
        self.day = row["day"]
        self.world_id = row["world_id"] if "world_id" in keys else None
        self.world_name = row["world_name"]
        self.favorite = bool(row["favorite"])
        self.width = row["width"] if "width" in keys else 0
        self.height = row["height"] if "height" in keys else 0
        self.filesize = row["filesize"]
        self.mtime = row["mtime"]
        self.meta_source = row["meta_source"] if "meta_source" in keys else ""
        self.avatar_name = row["avatar_name"] if "avatar_name" in keys else None
        self.session_id = row["session_id"] if "session_id" in keys else None
        self.instance_type = row["instance_type"] if "instance_type" in keys else ""
        self.rating = (row["rating"] or 0) if "rating" in keys else 0
        self.is_video = bool(row["is_video"]) if "is_video" in keys else False


class MiniItem:
    """Cover thumbnails on cards (worlds/people/albums) reuse the thumb pipeline."""
    __slots__ = ("id", "path", "mtime", "filesize", "scanned")

    def __init__(self, pid, path, mtime, filesize, scanned=1):
        self.id = pid
        self.path = path
        self.mtime = mtime
        self.filesize = filesize
        self.scanned = scanned


class ThumbCache(QObject):
    """GUI-side pixmap LRU on top of ThumbService."""
    ready = Signal(int)

    def __init__(self, svc, bridge, parent=None):
        super().__init__(parent)
        self.svc = svc
        self._mem = OrderedDict()
        self._cap = 320
        self._failed = set()
        self._born = {}          # pid -> monotonic time the pixmap arrived (for fade-in)
        self._watchers = {}      # pid -> [widgets], so one thumb wakes only its own
        bridge.thumb_ready.connect(self._on_ready)

    def watch(self, pid, widget):
        """Register a widget to repaint when this one photo's thumbnail lands."""
        self._watchers.setdefault(pid, []).append(widget)

    def _notify_watchers(self, pid):
        widgets = self._watchers.get(pid)
        if not widgets:
            return
        alive = []
        for w in widgets:
            try:
                w.update()
                alive.append(w)
            except RuntimeError:
                pass          # the C++ widget is gone; drop it from the registry
        if alive:
            self._watchers[pid] = alive
        else:
            self._watchers.pop(pid, None)

    def get(self, item, scanned_hint=1):
        pm = self._mem.get(item.id)
        if pm is not None:
            self._mem.move_to_end(item.id)
            return pm
        if item.id in self._failed:
            return None
        self.svc.request_thumb(item.id, item.path, item.mtime or 0,
                               item.filesize or 0, scanned_hint)
        return None

    def peek(self, pid):
        return self._mem.get(pid)

    def _on_ready(self, pid, image):
        if image.isNull():
            self._failed.add(pid)
        else:
            pm = QPixmap.fromImage(image)
            self._mem[pid] = pm
            self._mem.move_to_end(pid)
            self._born[pid] = time.monotonic()
            while len(self._mem) > self._cap:
                old, _ = self._mem.popitem(last=False)
                self._born.pop(old, None)
        self._notify_watchers(pid)
        self.ready.emit(pid)

    def age_ms(self, pid):
        t = self._born.get(pid)
        return None if t is None else (time.monotonic() - t) * 1000.0

    def invalidate(self, pid):
        self._mem.pop(pid, None)
        self._born.pop(pid, None)
        self._failed.discard(pid)


class GridModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []            # (kind, payload); header payload=(day, count)
        self._by_id = {}           # pid -> model row
        self._photos = []          # PhotoItem list in display order

    def set_photos(self, db_rows, group_by_day=True):
        self.beginResetModel()
        self._rows = []
        self._by_id = {}
        self._photos = []
        if group_by_day:
            counts = {}
            for r in db_rows:
                counts[r["day"]] = counts.get(r["day"], 0) + 1
            last_day = object()
            for r in db_rows:
                if r["day"] != last_day:
                    last_day = r["day"]
                    self._rows.append((KIND_HEADER, (r["day"], counts.get(r["day"], 0))))
                item = PhotoItem(r)
                self._by_id[item.id] = len(self._rows)
                self._photos.append(item)
                self._rows.append((KIND_PHOTO, item))
        else:
            for r in db_rows:
                item = PhotoItem(r)
                self._by_id[item.id] = len(self._rows)
                self._photos.append(item)
                self._rows.append((KIND_PHOTO, item))
        self.endResetModel()

    # ---- access ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        kind, payload = self._rows[index.row()]
        if role == KindRole:
            return kind
        if role == ItemRole:
            return payload
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        kind, _ = self._rows[index.row()]
        if kind == KIND_HEADER:
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def photos(self):
        return self._photos

    def month_marks(self):
        """[(model_row, 'YYYY-MM')] — the first row of each month, for the rail."""
        marks = []
        last = None
        for row, (kind, payload) in enumerate(self._rows):
            day = payload[0] if kind == KIND_HEADER else payload.day
            ym = (day or "")[:7]
            if ym and ym != last:
                marks.append((row, ym))
                last = ym
        return marks

    def photo_pos(self, model_row):
        """Model row -> position within the photo-only list."""
        kind, payload = self._rows[model_row]
        if kind != KIND_PHOTO:
            return -1
        return self._photos.index(payload)

    def row_of_id(self, pid):
        return self._by_id.get(pid, -1)

    def notify_thumb(self, pid):
        r = self._by_id.get(pid)
        if r is not None:
            ix = self.index(r)
            self.dataChanged.emit(ix, ix, [Qt.DecorationRole])

    def set_favorite(self, pids, on):
        for pid in pids:
            r = self._by_id.get(pid)
            if r is not None:
                self._rows[r][1].favorite = on
                ix = self.index(r)
                self.dataChanged.emit(ix, ix, [Qt.DecorationRole])

    def set_rating(self, pids, stars):
        for pid in pids:
            r = self._by_id.get(pid)
            if r is not None:
                self._rows[r][1].rating = stars
                ix = self.index(r)
                self.dataChanged.emit(ix, ix, [Qt.DecorationRole])


class PhotoDelegate(QStyledItemDelegate):
    """Rounded cover-crop thumbnails; day headers span the full row."""

    fav_clicked = Signal(int)

    def __init__(self, view, cache, parent=None):
        super().__init__(parent)
        self.view = view
        self.cache = cache
        self.cell_w = 176
        self.radius = 12
        self._accent = style.ACCENTS["orchid"]["a"]
        self._f_head = QFont()
        self._f_head.setPointSizeF(10.5)
        self._f_head.setWeight(QFont.DemiBold)
        self._f_small = QFont()
        self._f_small.setPointSizeF(8.5)
        self._f_small.setWeight(QFont.DemiBold)
        self._hover_id = None
        self._hover_t = 0.0

    def set_accent(self, color):
        self._accent = color

    def set_cell_width(self, w):
        self.cell_w = int(w)

    # --- geometry ---
    def cell_size(self):
        return QSize(self.cell_w, int(self.cell_w * 9 / 16))

    def sizeHint(self, option, index):
        kind = index.data(KindRole)
        if kind == KIND_HEADER:
            vw = self.view.viewport().width()
            return QSize(max(80, vw - 24), 46)
        return self.cell_size()

    # --- painting ---
    def paint(self, painter, option, index):
        kind = index.data(KindRole)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if kind == KIND_HEADER:
            self._paint_header(painter, option, index)
        else:
            self._paint_photo(painter, option, index)
        painter.restore()

    def _paint_header(self, p, option, index):
        day, count = index.data(ItemRole)
        r = option.rect
        p.setFont(self._f_head)
        p.setPen(QColor(style.PAL["text"]))
        text_r = r.adjusted(4, 0, -4, -6)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignBottom, fmt.day_label(day))
        p.setPen(QColor(style.PAL["faint"]))
        f2 = QFont(self._f_head)
        f2.setWeight(QFont.Normal)
        f2.setPointSizeF(9.5)
        p.setFont(f2)
        p.drawText(text_r, Qt.AlignRight | Qt.AlignBottom,
                   f"{count} {fmt.plural(count, 'photo')}")

    def _paint_photo(self, p, option, index):
        item = index.data(ItemRole)
        r = option.rect.adjusted(0, 0, 0, 0)
        rf = QRectF(r)
        path = QPainterPath()
        path.addRoundedRect(rf, self.radius, self.radius)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)

        pm = None if item.is_video else self.cache.get(item)
        p.setClipPath(path)
        if item.is_video:
            # no frame is ever decoded from a recording; it gets its own tile
            p.fillRect(r, QColor(style.PAL["surface2"]))
            glyph = icons.pixmap("film", style.PAL["faint"], 30,
                                 self.view.devicePixelRatioF(), width=1.6)
            p.drawPixmap(int(rf.center().x() - 15), int(rf.center().y() - 21), glyph)
            p.setFont(self._f_small)
            p.setPen(QColor(style.PAL["faint"]))
            p.drawText(QRectF(rf.x(), rf.center().y() + 12, rf.width(), 16),
                       Qt.AlignHCenter | Qt.AlignTop, "video")
        elif pm is None or pm.isNull():
            p.fillRect(r, QColor(style.PAL["surface2"]))
            glyph = icons.pixmap("aperture", style.PAL["border2"], 26,
                                 self.view.devicePixelRatioF(), width=1.6)
            gs = 26
            p.drawPixmap(int(rf.center().x() - gs / 2), int(rf.center().y() - gs / 2), glyph)
        else:
            # freshly loaded thumbs fade in; the hovered tile eases into a gentle zoom
            alpha = 1.0
            age = self.cache.age_ms(item.id)
            if age is not None and age < 220.0:
                alpha = max(0.05, age / 220.0)
                self.view.viewport().update()
            zoom = 1.0
            if hovered:
                now = time.monotonic()
                if self._hover_id != item.id:
                    self._hover_id = item.id
                    self._hover_t = now
                ht = (now - self._hover_t) * 1000.0
                zoom = 1.0 + 0.045 * min(1.0, ht / 160.0)
                if ht < 170.0:
                    self.view.viewport().update()
            pw, ph = pm.width(), pm.height()
            if pw > 0 and ph > 0:
                p.fillRect(r, QColor(style.PAL["surface2"]))
                p.setOpacity(alpha)
                scale = max(rf.width() / pw, rf.height() / ph) * zoom
                dw, dh = pw * scale, ph * scale
                dx = rf.x() + (rf.width() - dw) / 2
                dy = rf.y() + (rf.height() - dh) / 2
                p.drawPixmap(QRectF(dx, dy, dw, dh), pm, QRectF(0, 0, pw, ph))
                p.setOpacity(1.0)
        if hovered or selected:
            veil = QColor(255, 255, 255, 14 if hovered and not selected else 10)
            p.fillRect(r, veil)
        if hovered:
            g = QLinearGradient(rf.x(), rf.bottom() - 54, rf.x(), rf.bottom())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 170))
            p.fillRect(QRectF(rf.x(), rf.bottom() - 54, rf.width(), 54), g)
            p.setFont(self._f_small)
            fm = QFontMetrics(self._f_small)
            tm = fmt.time_label(item.taken_at)
            tw = fm.horizontalAdvance(tm)
            p.setPen(QColor(255, 255, 255, 210))
            if item.world_name:
                name = fm.elidedText(item.world_name, Qt.ElideRight,
                                     int(rf.width()) - tw - 26)
                p.drawText(QRectF(rf.x() + 9, rf.bottom() - 24, rf.width() - 18, 18),
                           Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setPen(QColor(255, 255, 255, 170))
            p.drawText(QRectF(rf.x() + 9, rf.bottom() - 24, rf.width() - 18, 18),
                       Qt.AlignRight | Qt.AlignVCenter, tm)
        # rating: small pips, only when the photo actually has one
        if item.rating:
            p.setPen(Qt.NoPen)
            for i in range(item.rating):
                p.setBrush(QColor(255, 255, 255, 225))
                p.drawEllipse(QRectF(rf.x() + 9 + i * 9, rf.bottom() - 14, 5, 5))
        # favorite star (always when set; on hover as outline hit target)
        if item.favorite or hovered:
            sr = self._star_rect(r)
            if item.favorite:
                p.setBrush(QColor(0, 0, 0, 110))
                p.setPen(Qt.NoPen)
                p.drawEllipse(sr.adjusted(-5, -5, 5, 5))
                pmn = icons.pixmap("star", style.PAL["star"], 15,
                                   self.view.devicePixelRatioF(), width=1.8,
                                   fill=style.PAL["star"])
            else:
                p.setBrush(QColor(0, 0, 0, 80))
                p.setPen(Qt.NoPen)
                p.drawEllipse(sr.adjusted(-5, -5, 5, 5))
                pmn = icons.pixmap("star", "#ffffff", 15,
                                   self.view.devicePixelRatioF(), width=1.8)
            p.drawPixmap(sr.topLeft(), pmn)
        p.setClipping(False)
        if selected:
            pen = QPen(QColor(self._accent), 2.4)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rf.adjusted(1.2, 1.2, -1.2, -1.2), self.radius - 1, self.radius - 1)

    def _star_rect(self, r):
        return QRect(r.right() - 26, r.top() + 11, 15, 15)

    # --- interaction: star hit-test ---
    def editorEvent(self, event, model, option, index):
        if index.data(KindRole) == KIND_PHOTO and event.type() == event.Type.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                sr = self._star_rect(option.rect).adjusted(-6, -6, 6, 6)
                if sr.contains(event.position().toPoint()):
                    item = index.data(ItemRole)
                    self.fav_clicked.emit(item.id)
                    return True
        return super().editorEvent(event, model, option, index)


class GridView(QListView):
    open_requested = Signal(QModelIndex)
    fav_key = Signal()
    delete_key = Signal()
    context_requested = Signal(object, QModelIndex)   # QPoint, index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setSpacing(7)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(48)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.NoFrame)
        self.doubleClicked.connect(self._maybe_open)

    def _maybe_open(self, ix):
        if ix.data(KindRole) == KIND_PHOTO:
            self.open_requested.emit(ix)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.scheduleDelayedItemsLayout()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            ix = self.currentIndex()
            if ix.isValid() and ix.data(KindRole) == KIND_PHOTO:
                self.open_requested.emit(ix)
            return
        if ev.key() == Qt.Key_F and not ev.modifiers():
            self.fav_key.emit()
            return
        if ev.key() == Qt.Key_Delete:
            self.delete_key.emit()
            return
        super().keyPressEvent(ev)

    def contextMenuEvent(self, ev):
        ix = self.indexAt(ev.pos())
        self.context_requested.emit(ev.globalPos(), ix)

    def selected_photo_items(self):
        out = []
        for ix in self.selectionModel().selectedIndexes():
            if ix.data(KindRole) == KIND_PHOTO:
                out.append(ix.data(ItemRole))
        out.sort(key=lambda it: it.taken_at or "")
        return out
