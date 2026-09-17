"""Photo grid: model (day headers + photos), thumbnail cache, delegate, view."""
import time
from collections import OrderedDict

from PySide6.QtCore import (QAbstractListModel, QMimeData, QModelIndex, QObject, QPoint, QPointF,
                            QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QAbstractItemView

from . import fmt, icons, style

KindRole = Qt.UserRole + 1
ItemRole = Qt.UserRole + 2

KIND_HEADER = 0
KIND_PHOTO = 1
KIND_PERIOD = 2       # a year or month card at the zoomed-out browsing levels
KIND_SPACER = 3       # blank full-width row: the content scrolls under a floating
                      # header, so it needs somewhere to start
KIND_BURST = 4        # a run of shots taken seconds apart, shown as one stack


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
    # A burst is a run of shots taken seconds apart: you line a pose up and press
    # the button eight times. Measured on the author's own library -- 108 runs of
    # three or more within 30 seconds, holding 400 photographs, 22% of the whole
    # thing. Collapsed, the visible tiles fall from 1812 to 1520.
    BURST_GAP = 30.0
    BURST_MIN = 3
    # And an upper bound. Without one a long shoot with no pause in it folds into
    # a single tile -- the whole of the All sheet became one, in a test, because
    # that level has no day boundaries to stop a run. Twelve is a stack you can
    # still read the count on; past that it wants to be several.
    BURST_MAX = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []            # (kind, payload); header payload=(day, count)
        self._by_id = {}           # pid -> model row; EVERY photo in a burst
                                   # points at the burst's row, so revealing one
                                   # still finds where it is on screen
        self._photos = []          # PhotoItem list in display order, never folded
        self._expanded = set()     # id of the first photo of each opened burst
        self.collapse = True
        self._shape = (True, 0)    # (group_by_day, top_gap) of the last build

    def set_photos(self, db_rows, group_by_day=True, top_gap=0):
        self._photos = [PhotoItem(r) for r in db_rows]
        self._expanded.clear()     # a new list is a new set of runs
        self._shape = (group_by_day, top_gap)
        self._rebuild()

    def set_collapse_bursts(self, on):
        on = bool(on)
        if on != self.collapse:
            self.collapse = on
            self._expanded.clear()
            self._rebuild()

    def toggle_burst(self, pid):
        """Open or close the run whose first photo this is. -> True if it moved."""
        for kind, payload in self._rows:
            if kind == KIND_BURST and payload[0].id == pid:
                self._expanded.add(pid)
                self._rebuild()
                return True
        if pid in self._expanded:
            self._expanded.discard(pid)
            self._rebuild()
            return True
        return False

    @staticmethod
    def _secs(iso):
        dt = fmt.parse_iso(iso) if iso else None
        return dt.timestamp() if dt else None

    def _run_end(self, secs, i, group_by_day):
        """Where the run starting at i ends. Photos, not rows."""
        n = len(self._photos)
        j = i + 1
        while j < n and j - i < self.BURST_MAX:
            if group_by_day and self._photos[j].day != self._photos[i].day:
                break
            a, b = secs[j - 1], secs[j]
            # An unreadable timestamp ends the run rather than joining anything:
            # a burst is a claim about time, and we have none for that photo.
            if a is None or b is None or abs(b - a) > self.BURST_GAP:
                break
            j += 1
        return j

    def _rebuild(self):
        group_by_day, top_gap = self._shape
        self.beginResetModel()
        self._rows = []
        self._by_id = {}
        if top_gap:
            self._rows.append((KIND_SPACER, top_gap))
        counts = {}
        if group_by_day:
            for it in self._photos:
                counts[it.day] = counts.get(it.day, 0) + 1
        secs = [self._secs(it.taken_at) for it in self._photos]
        last_day = object()
        i, n = 0, len(self._photos)
        while i < n:
            it = self._photos[i]
            if group_by_day and it.day != last_day:
                last_day = it.day
                self._rows.append((KIND_HEADER, (it.day, counts.get(it.day, 0))))
            # Only where there are days to bound a run. The All sheet is
            # deliberately one uninterrupted wall of the whole library, and a
            # burst is a claim about one sitting within one day.
            j = (self._run_end(secs, i, group_by_day)
                 if self.collapse and group_by_day else i + 1)
            run = self._photos[i:j]
            if len(run) >= self.BURST_MIN and run[0].id not in self._expanded:
                row = len(self._rows)
                for m in run:
                    self._by_id[m.id] = row
                self._rows.append((KIND_BURST, run))
            else:
                for m in run:
                    self._by_id[m.id] = len(self._rows)
                    self._rows.append((KIND_PHOTO, m))
            i = j
        self.endResetModel()

    def set_periods(self, rows, level, covers, top_gap=0):
        """Year or month cards. rows: db.period_summary; covers: id -> photo row."""
        self.beginResetModel()
        self._rows = []
        self._by_id = {}
        self._photos = []
        if top_gap:
            self._rows.append((KIND_SPACER, top_gap))
        for r in rows:
            key = r["k"]
            label = key if level == "year" else fmt.month_label(key)
            c = covers.get(r["cover_id"])
            cover = (MiniItem(c["id"], c["path"], c["mtime"], c["filesize"], 1)
                     if c else None)
            self._rows.append((KIND_PERIOD, {
                "key": key, "level": level, "label": label, "count": r["c"],
                "bytes": r["b"], "cover": cover}))
        self.endResetModel()

    # ---- access ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def row_at(self, row):
        """(kind, payload) without a trip through Qt.

        index.data(role) leaves Python, crosses into C++, and comes straight
        back into data() below -- 5.8 microseconds a call, twice per tile, on
        every repaint. The delegate owns this model; it can just ask.
        """
        try:
            return self._rows[row]
        except IndexError:
            return None, None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        kind, payload = self._rows[index.row()]
        if role == KindRole:
            return kind
        if role == ItemRole:
            return payload
        return None

    # Built once. Combining two flags allocates, and flags() is called for
    # every item on every repaint -- it profiled at fifteen microseconds a call.
    _FLAGS_NONE = Qt.NoItemFlags
    _FLAGS_INERT = Qt.ItemIsEnabled
    _FLAGS_ITEM = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
    # A year or month card is a place to go, not a file. Leaving it draggable
    # cost it the single click that opens it: drift ten pixels while pressing
    # and Qt enters its drag branch, clears pressedIndex, and clicked() never
    # fires -- so the year simply would not open, and there is no other way in.
    _FLAGS_PERIOD = Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def flags(self, index):
        if not index.isValid():
            return self._FLAGS_NONE
        kind = self._rows[index.row()][0]
        if kind == KIND_HEADER or kind == KIND_SPACER:
            # NoItemFlags on a row inside an IconMode QListView crashes the
            # native layout; a header is enabled-but-not-selectable and works
            return self._FLAGS_INERT
        if kind == KIND_PERIOD:
            return self._FLAGS_PERIOD
        return self._FLAGS_ITEM

    def day_of_row(self, row):
        """(day, count, header_row) for whatever is at this row, or None."""
        if not (0 <= row < len(self._rows)):
            return None
        kind, payload = self._rows[row]
        if kind in (KIND_PERIOD, KIND_SPACER):
            return None
        day = (payload[0] if kind == KIND_HEADER else
               payload[0].day if kind == KIND_BURST else payload.day)
        if not day:
            return None
        head = row
        while head >= 0:
            k, pl = self._rows[head]
            if k == KIND_HEADER and pl[0] == day:
                return day, pl[1], head
            head -= 1
        return day, 0, -1

    def photos(self):
        return self._photos

    def month_marks(self):
        """[(model_row, 'YYYY-MM')] — the first row of each month, for the rail."""
        marks = []
        last = None
        for row, (kind, payload) in enumerate(self._rows):
            if kind == KIND_SPACER:      # a blank row has no date of its own
                continue
            day = (payload[0] if kind == KIND_HEADER else
                   payload[0].day if kind == KIND_BURST else payload.day)
            ym = (day or "")[:7]
            if ym and ym != last:
                marks.append((row, ym))
                last = ym
        return marks

    def photo_pos(self, model_row):
        """Model row -> position within the photo-only list.

        photos() is never folded, so a collapsed burst opens the lightbox at the
        first shot of the run and the arrow keys walk the rest of it. Opening on
        the tile's own frame -- the LAST one -- would put you at the end of the
        run with nowhere to go but backwards.
        """
        kind, payload = self._rows[model_row]
        if kind == KIND_BURST:
            return self._photos.index(payload[0])
        if kind != KIND_PHOTO:
            return -1
        return self._photos.index(payload)

    def burst_at(self, model_row):
        """The run at this row, or None."""
        kind, payload = self._rows[model_row]
        return payload if kind == KIND_BURST else None

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


# Building a Qt flag combination costs 4 us and testing one costs 2 us -- which
# does not matter anywhere except in a delegate, where it happens for every tile
# on every repaint. Profiled at a hundred thousand enum calls in four seconds of
# scrolling. Built once here; the state tests compare plain ints instead.
ST_HOVER = QStyle.State_MouseOver.value
ST_SELECTED = QStyle.State_Selected.value
AL_LEFT_BOTTOM = Qt.AlignLeft | Qt.AlignBottom
AL_RIGHT_BOTTOM = Qt.AlignRight | Qt.AlignBottom
AL_LEFT_VCENTER = Qt.AlignLeft | Qt.AlignVCenter
AL_RIGHT_VCENTER = Qt.AlignRight | Qt.AlignVCenter
AL_HCENTER_TOP = Qt.AlignHCenter | Qt.AlignTop


class PhotoDelegate(QStyledItemDelegate):
    """Rounded cover-crop thumbnails; day headers span the full row."""

    fav_clicked = Signal(int)

    def __init__(self, view, cache, parent=None):
        super().__init__(parent)
        self.view = view
        self.cache = cache
        self.cell_w = 176
        self.radius = 12
        self.dense = False
        self._tiles = OrderedDict()      # (id, w, h, dpr, radius) -> ready pixmap
        self.blits = 0                   # tiles drawn the cheap way, and not
        self.slow = 0
        self._accent = style.ACCENTS["orchid"]["a"]
        self._f_head = QFont()
        self._f_head.setPointSizeF(10.5)
        self._f_head.setWeight(QFont.DemiBold)
        self._f_small = QFont()
        self._f_small.setPointSizeF(8.5)
        self._f_small.setWeight(QFont.DemiBold)
        self._f_count = QFont(self._f_head)      # built once, not per header
        self._f_count.setWeight(QFont.Normal)
        self._f_count.setPointSizeF(9.5)
        self._heads = OrderedDict()              # rendered day headers
        self._hover_id = None
        self._hover_t = 0.0
        self._size_key = None                    # see _sizes()
        self._sizes_now = None

    def set_accent(self, color):
        self._accent = color

    def set_cell_width(self, w):
        self.cell_w = int(w)
        self._tiles.clear()

    def set_dense(self, on):
        """Continuous mode: square tiles that divide the row exactly."""
        self.dense = bool(on)
        self.radius = 3 if self.dense else 6
        self._tiles.clear()

    def drop_tile(self, pid):
        for key in [k for k in self._tiles if k[0] == pid]:
            self._tiles.pop(key, None)

    def _tile(self, item, pm, w, h):
        """A tile ready to blit: scaled to the cell and already rounded.

        Doing the rounded clip and the downscale inside every paint was most of
        the cost of a scrolling frame, and neither changes between frames.
        """
        dpr = self.view.devicePixelRatioF()
        key = (item.id, w, h, round(dpr, 2), self.radius)
        hit = self._tiles.get(key)
        if hit is not None:
            self._tiles.move_to_end(key)
            return hit
        out = QPixmap(int(w * dpr), int(h * dpr))
        out.setDevicePixelRatio(dpr)
        out.fill(QColor(0, 0, 0, 0))
        q = QPainter(out)
        q.setRenderHint(QPainter.Antialiasing, True)
        q.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rf = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rf, self.radius, self.radius)
        q.setClipPath(path)
        q.fillRect(rf, QColor(style.PAL["surface2"]))
        pw, ph = pm.width(), pm.height()
        scale = max(rf.width() / pw, rf.height() / ph)
        dw, dh = pw * scale, ph * scale
        q.drawPixmap(QRectF((rf.width() - dw) / 2, (rf.height() - dh) / 2, dw, dh),
                     pm, QRectF(0, 0, pw, ph))
        q.end()
        self._tiles[key] = out
        while len(self._tiles) > 600:
            self._tiles.popitem(last=False)
        return out

    # --- geometry ---
    def cell_size(self):
        if getattr(self, "dense", False):
            gap = self.view.spacing() * 2
            vw = max(120, self.view.viewport().width() - gap)
            # as many as fit at roughly the chosen size, then share the row out
            n = max(1, round(vw / max(60, self.cell_w * 0.72)))
            side = int((vw - gap * (n - 1)) / n)
            return QSize(side, side)
        return QSize(self.cell_w, int(self.cell_w * 9 / 16))

    def period_size(self):
        """Zoomed-out cards are big: at these levels the cover IS the content."""
        vw = max(320, self.view.viewport().width() - 24)
        per_row = max(1, min(4, vw // 340))
        w = int((vw - (per_row - 1) * 14) / per_row)
        return QSize(w, int(w * 2 / 3))

    def _sizes(self):
        """The three fixed size hints, worked out once per layout instead of
        once per row.

        Laying the grid out asks for a size hint for every row there is -- two
        and a quarter thousand of them here -- and a live window resize sends
        one of those layouts per compositor frame. Each hint used to cost an
        index.data() round trip into C++ and back (5.8 us, measured), a call to
        viewport().width(), and a fresh QSize; nothing in any of that depends on
        WHICH row is being asked about, only on its kind. Cached against the
        four things they do depend on, a resize step fell from 28 ms to 9.
        """
        key = (self.view.viewport().width(), self.cell_w,
               getattr(self, "dense", False), self.view.spacing())
        if key != self._size_key:
            vw = key[0]
            self._size_key = key
            self._sizes_now = (self.cell_size(), self.period_size(),
                               QSize(max(80, vw - 24), 38), max(80, vw - 24))
        return self._sizes_now

    def sizeHint(self, option, index):
        model = index.model()
        kind, payload = (model.row_at(index.row()) if hasattr(model, "row_at")
                         else (index.data(KindRole), index.data(ItemRole)))
        cell, period, head, full_w = self._sizes()
        if kind in (KIND_PHOTO, KIND_BURST):
            return cell
        if kind == KIND_SPACER:
            return QSize(full_w, max(1, int(payload or 1)))
        if kind == KIND_HEADER:
            return head
        if kind == KIND_PERIOD:
            return period
        return cell

    # --- painting ---
    def paint(self, painter, option, index):
        model = index.model()
        row = index.row()
        kind, payload = (model.row_at(row) if hasattr(model, "row_at")
                         else (index.data(KindRole), index.data(ItemRole)))
        if kind == KIND_SPACER:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if kind == KIND_HEADER:
            self._paint_header(painter, option, payload)
        elif kind == KIND_PERIOD:
            self._paint_period(painter, option, payload)
        elif kind == KIND_BURST:
            self._paint_burst(painter, option, payload)
        else:
            self._paint_photo(painter, option, payload)
        painter.restore()

    def _header_pixmap(self, day, count, w, h):
        """A whole day header, laid out once and then blitted.

        Profiled: this row cost more per second than every photo tile put
        together. Two drawText calls is two text layouts and two rasterizations,
        and building the second QFont hits the font database -- all of it on
        every repaint, for a line that only changes when the day does.
        """
        dpr = self.view.devicePixelRatioF()
        key = (day, count, w, h, round(dpr, 2))
        hit = self._heads.get(key)
        if hit is not None:
            self._heads.move_to_end(key)
            return hit
        out = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        out.setDevicePixelRatio(dpr)
        out.fill(QColor(0, 0, 0, 0))
        q = QPainter(out)
        q.setRenderHint(QPainter.Antialiasing, True)
        base = max(1, h - 6)
        q.setFont(self._f_head)
        fm = q.fontMetrics()
        label = fmt.day_label(day)
        q.setPen(QColor(style.PAL["text"]))
        q.drawText(QRectF(4, 0, max(1, w - 8), base), AL_LEFT_BOTTOM, label)

        # A hairline across the rest of the row. Without it the dates carry the
        # same weight as everything else on a wall of photographs and simply get
        # lost in it; this is what gives a day a top edge.
        chip_w = 0
        if count:
            q.setFont(self._f_count)
            chip_w = max(24, q.fontMetrics().horizontalAdvance(str(count)) + 16)
        x0 = 4 + fm.horizontalAdvance(label) + 14
        x1 = w - 8 - (chip_w + 12 if chip_w else 0)
        if x1 > x0 + 8:
            y = base - fm.height() / 2 + 1.5
            q.setPen(QColor(style.PAL["border"]))
            q.drawLine(QPointF(x0, y), QPointF(x1, y))

        # The count as a chip rather than "23 photos": the word is the same on
        # every row and the number is the only part that differs.
        if chip_w:
            chip = QRectF(w - 8 - chip_w, base - 19, chip_w, 19)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(style.PAL["surface2"]))
            q.drawRoundedRect(chip, 9.5, 9.5)
            q.setPen(QColor(style.PAL["dim"]))
            q.setFont(self._f_count)
            q.drawText(chip, Qt.AlignCenter, str(count))
        q.end()
        self._heads[key] = out
        while len(self._heads) > 96:
            self._heads.popitem(last=False)
        return out

    def _paint_header(self, p, option, payload):
        day, count = payload
        r = option.rect
        p.drawPixmap(r.topLeft(), self._header_pixmap(day, count, r.width(), r.height()))

    def _paint_period(self, p, option, payload):
        """A big cover with the period written across the bottom of it."""
        d = payload
        r = QRectF(option.rect)
        hovered = bool(option.state.value & ST_HOVER)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.save()
        p.setClipPath(path)
        pm = self.cache.get(d["cover"]) if d["cover"] is not None else None
        if pm and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            grow = 1.04 if hovered else 1.0
            scale = max(r.width() / pw, r.height() / ph) * grow
            dw, dh = pw * scale, ph * scale
            p.drawPixmap(QRectF(r.x() + (r.width() - dw) / 2,
                                r.y() + (r.height() - dh) / 2, dw, dh),
                         pm, QRectF(0, 0, pw, ph))
        else:
            p.fillRect(r, QColor(style.PAL["surface2"]))
        # a scrim, so the label is readable over a bright sky as well as a night
        scrim = QLinearGradient(r.left(), r.bottom() - r.height() * 0.55,
                                r.left(), r.bottom())
        scrim.setColorAt(0.0, QColor(0, 0, 0, 0))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 205))
        p.fillRect(QRectF(r.left(), r.bottom() - r.height() * 0.55,
                          r.width(), r.height() * 0.55), scrim)
        p.restore()

        f = QFont()
        f.setPointSizeF(19 if d["level"] == "year" else 15)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        text_r = r.adjusted(18, 0, -18, -14)
        p.drawText(text_r, AL_LEFT_BOTTOM, d["label"])
        f2 = QFont()
        f2.setPointSizeF(10)
        p.setFont(f2)
        p.setPen(QColor(255, 255, 255, 190))
        sub = f"{fmt.count_label(d['count'])} {fmt.plural(d['count'], 'photo')}"
        p.drawText(text_r, AL_RIGHT_BOTTOM, sub)
        if hovered:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 120), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 16, 16)

    def _paint_photo(self, p, option, payload):
        item = payload
        r = option.rect
        rf = QRectF(r)
        st = option.state.value
        hovered = bool(st & ST_HOVER)
        selected = bool(st & ST_SELECTED)
        _path = []

        def path():
            # built only when something actually clips: on a scrolling frame
            # most tiles never touch it, and it is not free to construct
            if not _path:
                pp = QPainterPath()
                pp.addRoundedRect(rf, self.radius, self.radius)
                _path.append(pp)
            return _path[0]

        pm = None if item.is_video else self.cache.get(item)
        # A ready tile is already rounded, so it needs no clip. An antialiased
        # clip path per tile drops the raster engine onto its slow route, and
        # scrolling pays for it on every visible tile of every frame.
        blit = (pm is not None and not pm.isNull() and not item.is_video
                and not hovered
                and (self.cache.age_ms(item.id) or 999.0) >= 220.0)
        # A tile that is only fading in still gets the cached rounded pixmap;
        # the clip and the rescale are only needed by a hovered tile, whose zoom
        # pushes the thumbnail past its own edges.
        cheap = blit or (pm is not None and not pm.isNull()
                         and not item.is_video and not hovered)
        self.blits += bool(cheap)     # watched by a test: this is the fast path
        self.slow += (not cheap)
        if not cheap:
            p.setClipPath(path())
        if item.is_video:
            # no frame is ever decoded from a recording; it gets its own tile
            p.fillRect(r, QColor(style.PAL["surface2"]))
            glyph = icons.pixmap("film", style.PAL["faint"], 30,
                                 self.view.devicePixelRatioF(), width=1.6)
            p.drawPixmap(int(rf.center().x() - 15), int(rf.center().y() - 21), glyph)
            p.setFont(self._f_small)
            p.setPen(QColor(style.PAL["faint"]))
            p.drawText(QRectF(rf.x(), rf.center().y() + 12, rf.width(), 16),
                       AL_HCENTER_TOP, "video")
        elif pm is None or pm.isNull():
            p.fillRect(r, QColor(style.PAL["surface2"]))
            glyph = icons.pixmap("aperture", style.PAL["border2"], 26,
                                 self.view.devicePixelRatioF(), width=1.6)
            gs = 26
            p.drawPixmap(int(rf.center().x() - gs / 2), int(rf.center().y() - gs / 2), glyph)
        else:
            # Freshly loaded thumbs fade in; the hovered tile eases into a
            # gentle zoom. Both ask for the next frame -- but ONLY OVER THIS
            # TILE. Asking the whole viewport was the single most expensive
            # thing in the app: while you scroll, thumbnails are arriving
            # constantly, so there was always a tile younger than 220 ms, so
            # every frame invalidated all fifty visible tiles to animate one.
            # Eighty-three per cent of frames were full-viewport repaints.
            alpha = 1.0
            age = self.cache.age_ms(item.id)
            if age is not None and age < 220.0:
                alpha = max(0.05, age / 220.0)
                self.view.viewport().update(r)
            zoom = 1.0
            if hovered:
                now = time.monotonic()
                if self._hover_id != item.id:
                    self._hover_id = item.id
                    self._hover_t = now
                ht = (now - self._hover_t) * 1000.0
                zoom = 1.0 + 0.045 * min(1.0, ht / 160.0)
                if ht < 170.0:
                    self.view.viewport().update(r)
            pw, ph = pm.width(), pm.height()
            if pw > 0 and ph > 0:
                if cheap:
                    # The common case, and the fading one too. Sending a tile
                    # down the slow path -- an antialiased clip and a rescale of
                    # the whole thumbnail -- for the 220 ms of its fade meant
                    # that while you scrolled, with thumbnails arriving the
                    # whole time, a good share of every frame went on an
                    # animation nobody can follow at that speed.
                    if alpha < 1.0:
                        # The fast path sets no clip, because the cached tile
                        # already carries the rounded corners in its own alpha.
                        # This fill is not that tile: unclipped it puts a square
                        # plate of surface2 under it, and for the 220 ms of the
                        # fade each corner shows a nub of #1c2130 on the page's
                        # #0d0f15. Every thumbnail does it, every time one is
                        # decoded -- which is the whole grid, on any scroll
                        # through photos that are not in the cache yet.
                        p.save()
                        p.setClipPath(path())
                        p.fillRect(r, QColor(style.PAL["surface2"]))
                        p.restore()
                        p.setOpacity(alpha)
                    p.drawPixmap(r.topLeft(), self._tile(item, pm, r.width(), r.height()))
                    p.setOpacity(1.0)
                else:
                    p.fillRect(r, QColor(style.PAL["surface2"]))
                    p.setOpacity(alpha)
                    scale = max(rf.width() / pw, rf.height() / ph) * zoom
                    dw, dh = pw * scale, ph * scale
                    dx = rf.x() + (rf.width() - dw) / 2
                    dy = rf.y() + (rf.height() - dh) / 2
                    p.drawPixmap(QRectF(dx, dy, dw, dh), pm, QRectF(0, 0, pw, ph))
                    p.setOpacity(1.0)
        if hovered or selected:
            # `cheap`, not `blit`: blit is a strict subset of it, and the clip is
            # missing for the whole of `cheap`. A selected tile still fading got
            # its veil filled square for exactly the same reason the plate above
            # did -- select everything, then scroll into rows that have not been
            # decoded yet, and the corners light up.
            if cheap:                     # the overlays do need the rounded shape
                p.setClipPath(path())
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
                           AL_LEFT_VCENTER, name)
            p.setPen(QColor(255, 255, 255, 170))
            p.drawText(QRectF(rf.x() + 9, rf.bottom() - 24, rf.width() - 18, 18),
                       AL_RIGHT_VCENTER, tm)
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

    def _burst_badge_rect(self, r):
        """Where the count sits on a collapsed burst. Also its hit target."""
        return QRect(r.right() - 44, r.bottom() - 26, 36, 18)

    def _paint_burst(self, p, option, run):
        """A run of shots as one tile: the last frame, and how many there are.

        The LAST, not the first: you press the button until you get the one you
        wanted, so the keeper is at the end of the run far more often than at
        the start.

        No stack of offset cards behind it -- at three pixels between tiles they
        would sit on the neighbours. The fold in the corner and the count do the
        same work inside the tile's own bounds.
        """
        self._paint_photo(p, option, run[-1])
        r = option.rect
        badge = self._burst_badge_rect(r)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(QRectF(badge), 9, 9)
        p.setPen(QColor(255, 255, 255, 230))
        p.setFont(self._f_small)
        p.drawText(QRectF(badge), Qt.AlignCenter, f"❐ {len(run)}")
        p.restore()

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
    burst_toggled = Signal(int)      # model row of the stack whose badge was hit
    fav_key = Signal()
    delete_key = Signal()
    context_requested = Signal(object, QModelIndex)   # QPoint, index
    zoom_requested = Signal(int)                      # ctrl+wheel notches

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        # Fixed, and the re-wrap driven by hand from resizeEvent. See there.
        self.setResizeMode(QListView.Fixed)
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
        # Drag photos out to Explorer, Discord, anywhere that takes files.
        # DragOnly and CopyAction, both of them deliberately: see startDrag.
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self._relayout = QTimer(self)          # see resizeEvent
        self._relayout.setSingleShot(True)
        self._relayout.timeout.connect(self.scheduleDelayedItemsLayout)
        self._last_resize = 0.0
        from . import widgets
        self.smooth = widgets.SmoothScroll(self)
        self.doubleClicked.connect(self._maybe_open)
        # a period card is a place to go, not a thing to select: one click
        self.clicked.connect(self._maybe_drill)

    def _maybe_open(self, ix):
        if ix.data(KindRole) in (KIND_PHOTO, KIND_BURST):
            self.open_requested.emit(ix)

    def _maybe_drill(self, ix):
        if ix.data(KindRole) == KIND_PERIOD:
            self.open_requested.emit(ix)

    def wheelEvent(self, ev):
        # ctrl+wheel resizes the thumbnails, the way every photo grid does
        if ev.modifiers() & Qt.ControlModifier:
            notches = ev.angleDelta().y()
            if notches:
                self.zoom_requested.emit(1 if notches > 0 else -1)
            ev.accept()
            return
        super().wheelEvent(ev)

    # NOTE: a scrolled frame repaints the WHOLE viewport here -- measured on a
    # real 180 Hz window: 83% of frames, 27 to 50 tiles each. That is Qt. An
    # icon view will not blit its backing store, because items may sit at
    # arbitrary positions and a scroll cannot be assumed to be a translation.
    # Overriding scrollContentsBy to call viewport().scroll() was tried and
    # changed nothing, with the overlays hidden AND the viewport made opaque.
    # So the lever here is the cost of a TILE, not the number of them.

    def resizeEvent(self, ev):
        """Re-wrap when the drag settles, not on every frame of it.

        Dragging a window edge sends one resize per compositor frame, and
        re-wrapping this grid is not a per-frame job: two thousand rows, each
        one a size hint out to Python and back, and the whole thing has to
        finish before the view can paint. Measured on the real window at 180 Hz
        it was 27 of the 32 ms a resize frame cost -- the window lagging six
        frames behind the edge in your hand, which is what the flicker was.

        ResizeMode.Adjust posts that relayout from QListView's own resizeEvent
        and every paint flushes it, so Qt's own tenth-of-a-second wait never
        got to expire. Fixed stops it posting one at all: the tiles hold the
        wrap they have -- the window simply reveals or hides a column at the
        right edge, which is what you want to SEE while dragging anyway -- and
        the timer re-wraps once, when you stop.
        """
        super().resizeEvent(ev)
        if ev.size().width() == ev.oldSize().width():
            return                # a taller window does not change the wrap
        # One resize on its own is a maximise, a snap to half the screen, or the
        # sidebar folding away, and there is nothing to wait for -- re-wrap now.
        # A resize that follows hard on another one is a drag, and there will be
        # sixty more of them: those wait for the last.
        now = time.perf_counter()
        drag = now - self._last_resize < 0.15
        self._last_resize = now
        if drag:
            self._relayout.start(90)
        else:
            self._relayout.stop()
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

    # ------------------------------------------------------------ dragging
    def drag_order(self, items):
        """The order the drop target receives them in: the order you see.

        selected_photo_items sorts oldest-first, which every other caller wants;
        the grid is usually newest-first, so a drop into Discord stacked the
        attachments backwards. Sorting by model row follows whatever the sort
        box is set to. The photo under the hand leads, so the ghost carries the
        one that was grabbed rather than the far end of the selection.
        """
        model = self.model()
        rows = getattr(model, "_by_id", None)
        if rows:
            items = sorted(items, key=lambda it: rows.get(it.id, 0))
        cur = self.currentIndex()
        if cur.isValid() and cur.data(KindRole) == KIND_PHOTO:
            grabbed = cur.data(ItemRole)
            if grabbed in items:
                items = [grabbed] + [it for it in items if it is not grabbed]
        return items

    def drag_payload(self, items):
        """What leaves the app when you drag photos out. -> (QMimeData, paths)

        Files that are not on disk any more are dropped: a library can outlive
        the folder it points at, and handing a drop target a URL to nothing gets
        an error dialog from Explorer rather than from us. None if nothing is
        left to drag.
        """
        import os
        # One listing per FOLDER, not one stat per photo. A library this size
        # lives in about forty month folders, so a select-all went from 230 ms
        # of frozen window to 23 ms -- and on a sleeping network share the
        # per-file version stalled for twenty-one seconds and then quietly
        # decided every photo was missing.
        seen = {}
        paths = []
        for it in items:
            path = getattr(it, "path", None)
            if not path:
                continue
            folder, name = os.path.split(path)
            listing = seen.get(folder)
            if listing is None:
                try:
                    listing = {n.lower() for n in os.listdir(folder)}
                except OSError:
                    listing = frozenset()
                seen[folder] = listing
            if name.lower() in listing:
                paths.append(path)
        if not paths:
            return None, []
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        # A plain-text list as well, for anything that takes text but not files
        mime.setText("\n".join(paths))
        return mime, paths

    def drag_pixmap(self, items, cache):
        """What the cursor carries: the grabbed thumbnail, and how many there are.

        peek(), not get(): get() REQUESTS a thumbnail when it misses, at a
        priority above the background sweep. Dragging a select-all queued
        fourteen hundred jobs and pushed every on-screen thumbnail out of the
        LRU, so the first repaint after the drop had to decode the whole
        viewport again. The ghost wants one picture that already exists.
        """
        first = None
        for it in items:
            pm = cache.peek(it.id) if cache is not None else None
            if pm is not None and not pm.isNull():
                first = pm
                break
        side, pad = 96, 8
        out = QPixmap(side + pad, side + pad)
        out.fill(QColor(0, 0, 0, 0))
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        body = QRectF(0, 0, side, side)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        p.setClipPath(path)
        if first is not None:
            fw, fh = first.width(), first.height()
            scale = max(side / fw, side / fh)
            dw, dh = fw * scale, fh * scale
            p.drawPixmap(QRectF((side - dw) / 2, (side - dh) / 2, dw, dh),
                         first, QRectF(0, 0, fw, fh))
        else:
            p.fillRect(body, QColor(style.PAL["surface2"]))
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.drawPath(path)
        if len(items) > 1:
            badge = QRectF(side - 30, side - 24, 30 + pad, 24 + pad - 2)
            p.setPen(Qt.NoPen)
            ac = style.accent(self._accent_key())
            p.setBrush(QColor(ac["a"]))
            p.drawRoundedRect(badge, 11, 11)
            f = QFont()
            f.setPointSizeF(9.5)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor("#0b0e14"))
            p.drawText(badge, Qt.AlignCenter, str(len(items)))
        p.end()
        return out

    def _accent_key(self):
        page = self.parent()
        cfg = getattr(page, "cfg", None)
        return cfg.get("accent") if cfg is not None else style.DEFAULT_ACCENT

    def mousePressEvent(self, ev):
        """Decide here whether this gesture is allowed to become a file drag.

        It has to be here rather than in startDrag, because by the time Qt calls
        startDrag it has already cleared pressedIndex -- so refusing there loses
        the click as well, which is how the favourite star turned into a drag on
        a twelve-pixel wobble. Three separate ways a press must not drag:

          * NOT THE LEFT BUTTON. Qt's drag branch tests buttons() != NoButton,
            so a right-press plus a wobble started a drag, and the drag grabbed
            the mouse, and the context menu never opened.
          * NOT ON A PHOTO. A day header keeps ItemIsEnabled, so ctrl-pressing
            one kept the selection, and eight pixels of movement flung every
            selected photo into whatever was under the cursor.
          * NOT ON THE FAVOURITE STAR, which is a 27 px target that has its own
            click.
        """
        ix = self.indexAt(ev.position().toPoint())
        may_drag = (ev.button() == Qt.LeftButton
                    and ix.isValid()
                    and ix.data(KindRole) in (KIND_PHOTO, KIND_BURST)
                    and not self._on_star(ix, ev.position().toPoint())
                    and not self._on_burst_badge(ix, ev.position().toPoint()))
        self._press_draggable = may_drag
        self.setDragEnabled(may_drag)
        if (ev.button() == Qt.LeftButton and ix.isValid()
                and self._on_burst_badge(ix, ev.position().toPoint())):
            # The badge opens the stack where it stands. Handled on the press and
            # not passed on, so it neither changes the selection nor arms a drag.
            self.burst_toggled.emit(ix.row())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def _on_burst_badge(self, index, pos):
        """Is the pointer on the count badge of a collapsed burst?"""
        if index.data(KindRole) != KIND_BURST:
            return False
        delegate = self.itemDelegate()
        rect = getattr(delegate, "_burst_badge_rect", None)
        if rect is None:
            return False
        return rect(self.visualRect(index)).adjusted(-6, -6, 6, 6).contains(pos)

    def _on_star(self, index, pos):
        delegate = self.itemDelegate()
        star = getattr(delegate, "_star_rect", None)
        if star is None:
            return False
        return star(self.visualRect(index)).adjusted(-6, -6, 6, 6).contains(pos)

    def startDrag(self, supported_actions):
        """Hand the selected photos to whatever they are dropped on.

        COPY, AND ONLY COPY. Qt's default for an item view offers whatever the
        caller supports, and a drop onto a folder with MoveAction available
        would MOVE the originals out of the VRChat folder -- the library would
        be pointing at nothing and the user would have no idea why. Nothing this
        app does to a photo happens outside its own delete path, which goes to
        the Recycle Bin.
        """
        if not getattr(self, "_press_draggable", False):
            return                       # see mousePressEvent
        items = self.drag_order(self.selected_photo_items())
        mime, paths = self.drag_payload(items)
        if mime is None:
            return
        # The ghost shows what will actually land, and how much of it: the
        # payload drops photos that are gone, so counting the selection instead
        # promised eight files and delivered five.
        going = [it for it in items if it.path in set(paths)]
        drag = QDrag(self)
        drag.setMimeData(mime)
        delegate = self.itemDelegate()
        pm = self.drag_pixmap(going, getattr(delegate, "cache", None))
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.CopyAction, Qt.CopyAction)

    def selected_photo_items(self):
        """Every photograph the selection stands for.

        A collapsed burst is ONE row carrying a list of photographs, and this is
        the function every destructive path goes through -- delete, the drag to
        Explorer or Discord, favouriting, the selection bar's count. Return the
        representative alone and selecting a stack of eight and dragging it out
        would quietly send one file. So a burst row is expanded here, where all
        of them meet, rather than at each of the call sites.
        """
        out = []
        model = self.model()
        at = getattr(model, "row_at", None)
        for ix in self.selectionModel().selectedIndexes():
            kind, payload = (at(ix.row()) if at is not None
                             else (ix.data(KindRole), ix.data(ItemRole)))
            if kind == KIND_PHOTO:
                out.append(payload)
            elif kind == KIND_BURST:
                out.extend(payload)
        out.sort(key=lambda it: it.taken_at or "")
        return out
