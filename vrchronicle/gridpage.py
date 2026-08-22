"""The photo-grid page (used for: all photos, favorites, world/person/album/day drills)."""
from PySide6.QtCore import QDate, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QSlider, QVBoxLayout,
                               QWidget)

from . import fmt, icons, style, vrclog, widgets
from .db import PhotoFilter
from .gridmodel import GridModel, GridView, PhotoDelegate, KIND_PHOTO, ItemRole, KindRole


class TimelineRail(QWidget):
    """A thin month scale beside the grid: click or drag to jump through years."""
    jump_to = Signal(int)

    WIDTH = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self._marks = []          # (model_row, "YYYY-MM")
        self._rows = 0
        self._row = 0.0           # current top row, same scale as the marks
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_marks(self, marks, rows):
        self._marks = marks
        self._rows = max(1, rows)
        self.setVisible(len(marks) > 1)
        self.update()

    def set_row(self, row):
        self._row = max(0.0, min(float(self._rows - 1), float(row)))
        self.update()

    def _y_for(self, row):
        top, bottom = 10, self.height() - 10
        return top + (bottom - top) * (row / max(1, self._rows - 1))

    def _row_at(self, y):
        top, bottom = 10, self.height() - 10
        frac = (y - top) / max(1, bottom - top)
        return int(round(max(0.0, min(1.0, frac)) * max(0, self._rows - 1)))

    def _accent_key(self):
        page = self.parent()
        cfg = getattr(page, "cfg", None)
        return cfg.get("accent") if cfg is not None else style.DEFAULT_ACCENT

    def paintEvent(self, _ev):
        if len(self._marks) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        f = QFont()
        f.setPointSizeF(7.5)
        p.setFont(f)
        fm = QFontMetrics(f)

        last_label_y = -999
        last_year = None
        for row, ym in self._marks:
            y = self._y_for(row)
            year = ym[:4]
            new_year = year != last_year
            p.setPen(QColor(style.PAL["border2"] if not new_year else style.PAL["faint"]))
            p.drawLine(self.WIDTH - 12, int(y), self.WIDTH - (4 if new_year else 8), int(y))
            if y - last_label_y > fm.height() + 5:
                try:
                    text = year if new_year else fmt.MONTHS_SHORT[int(ym[5:7]) - 1]
                except (ValueError, IndexError):
                    text = year
                p.setPen(QColor(style.PAL["dim"] if new_year else style.PAL["faint"]))
                p.drawText(QRectF(0, y - fm.height() / 2, self.WIDTH - 16, fm.height()),
                           Qt.AlignRight | Qt.AlignVCenter, text)
                last_label_y = y
            last_year = year

        ac = style.accent(self._accent_key())
        y = self._y_for(self._row)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ac["a"]))
        p.drawRoundedRect(QRectF(self.WIDTH - 14, y - 2.5, 11, 5), 2.5, 2.5)
        p.end()

    def mousePressEvent(self, ev):
        self.jump_to.emit(self._row_at(ev.position().y()))

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self.jump_to.emit(self._row_at(ev.position().y()))
        if self._marks:                       # tell them where they are about to land
            row = self._row_at(ev.position().y())
            nearest = min(self._marks, key=lambda m: abs(m[0] - row))
            self.setToolTip(fmt.month_label(nearest[1]))


class GridPage(QWidget):
    back_requested = Signal()

    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.db = main.db
        self.cfg = main.cfg
        self.filter = PhotoFilter()
        self.title_text = "Photos"
        self._rows = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 0)
        root.setSpacing(12)

        # --- header ---
        head = QHBoxLayout()
        head.setSpacing(10)
        self.btn_back = widgets.icon_btn("arrow-left", "Back", style.PAL["text"], px=19)
        self.btn_back.clicked.connect(self.back_requested)
        self.btn_back.hide()
        head.addWidget(self.btn_back)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.lab_title = QLabel(self.title_text)
        self.lab_title.setObjectName("PageHeaderTitle")
        self.lab_sub = QLabel("")
        self.lab_sub.setObjectName("PageHeaderSub")
        tcol.addWidget(self.lab_title)
        tcol.addWidget(self.lab_sub)
        head.addLayout(tcol)
        head.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("Search world, person, file…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.addAction(icons.qicon("search", style.PAL["faint"], 15),
                              QLineEdit.LeadingPosition)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        head.addWidget(self.search)

        self.btn_fav = widgets.icon_btn("heart", "Favorites only", style.PAL["dim"],
                                        checkable=True)
        self.btn_fav.toggled.connect(self._on_fav_toggle)
        head.addWidget(self.btn_fav)

        self.sort_box = QComboBox()
        self.sort_box.addItems(["Newest first", "Oldest first"])
        self.sort_box.currentIndexChanged.connect(self._on_sort)
        head.addWidget(self.sort_box)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(128, 264)
        self.slider.setValue(int(self.cfg.get("thumb_px") or 176))
        self.slider.setFixedWidth(110)
        self.slider.setToolTip("Thumbnail size")
        self.slider.valueChanged.connect(self._on_slider)
        head.addWidget(self.slider)

        self.btn_filter = widgets.icon_btn("settings", "More filters", style.PAL["dim"],
                                           checkable=True)
        self.btn_filter.toggled.connect(self._toggle_filters)
        head.addWidget(self.btn_filter)
        self.btn_play = widgets.icon_btn("play", "Slideshow", style.PAL["dim"])
        self.btn_play.clicked.connect(self._start_slideshow)
        head.addWidget(self.btn_play)
        root.addLayout(head)
        root.addWidget(self._build_filter_bar())

        # --- grid ---
        self.model = GridModel(self)
        self.view = GridView(self)
        self.view.setModel(self.model)
        self.delegate = PhotoDelegate(self.view, cache, self)
        self.delegate.set_cell_width(self.slider.value())
        self.delegate.set_accent(style.accent(self.cfg.get("accent"))["a"])
        self.view.setItemDelegate(self.delegate)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        body.addWidget(self.view, 1)
        self.rail = TimelineRail(self)
        self.rail.jump_to.connect(self._scroll_to_row)
        body.addWidget(self.rail)
        root.addLayout(body, 1)
        self.view.verticalScrollBar().valueChanged.connect(self._sync_rail)

        cache.ready.connect(self.model.notify_thumb)
        self.delegate.fav_clicked.connect(lambda pid: self.main.act_favorite([pid]))
        self.view.open_requested.connect(self._open_from_index)
        self.view.fav_key.connect(self._fav_selection)
        self.view.delete_key.connect(self._delete_selection)
        self.view.context_requested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)

        # --- empty state + selection bar (floating) ---
        self.empty = widgets.EmptyState("image", "Nothing here",
                                        "Your VRChat shots will show up here.", self.view)
        self.empty.hide()
        self.selbar = widgets.SelectionBar(self)
        self.selbar.btn_fav.clicked.connect(self._fav_selection)
        self.selbar.btn_album.clicked.connect(self._album_selection)
        self.selbar.btn_trash.clicked.connect(self._delete_selection)
        self.selbar.btn_close.clicked.connect(lambda: self.view.clearSelection())

    def _build_filter_bar(self):
        """A second row that stays out of the way until it is asked for."""
        bar = QFrame()
        bar.setObjectName("Card")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        lay.addWidget(QLabel("From"))
        self.ed_from = QDateEdit()
        self.ed_from.setCalendarPopup(True)
        self.ed_from.setDisplayFormat("yyyy-MM-dd")
        self.ed_from.setSpecialValueText("—")
        self.ed_from.setMinimumDate(QDate(2017, 1, 1))
        self.ed_from.setDate(self.ed_from.minimumDate())
        lay.addWidget(self.ed_from)
        lay.addWidget(QLabel("to"))
        self.ed_to = QDateEdit()
        self.ed_to.setCalendarPopup(True)
        self.ed_to.setDisplayFormat("yyyy-MM-dd")
        # mirrors "from": the minimum doubles as "no upper bound", which also
        # means the default cannot go stale when the app outlives the day
        self.ed_to.setSpecialValueText("—")
        self.ed_to.setMinimumDate(QDate(2016, 12, 31))
        self.ed_to.setDate(self.ed_to.minimumDate())
        lay.addWidget(self.ed_to)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Instance"))
        self.cb_instance = QComboBox()
        self.cb_instance.addItem("Any", "")
        for key, label in vrclog.INSTANCE_LABELS.items():
            if key:
                self.cb_instance.addItem(label, key)
        lay.addWidget(self.cb_instance)

        lay.addWidget(QLabel("Rating ≥"))
        self.cb_rating = QComboBox()
        for n in range(6):
            self.cb_rating.addItem("Any" if n == 0 else "★" * n, n)
        lay.addWidget(self.cb_rating)

        lay.addWidget(QLabel("Media"))
        self.cb_media = QComboBox()
        for label, key in (("All", ""), ("Photos", "photo"), ("Videos", "video")):
            self.cb_media.addItem(label, key)
        lay.addWidget(self.cb_media)

        lay.addStretch(1)
        btn_apply = widgets.ghost_btn("Apply", "check", primary=True)
        btn_apply.clicked.connect(self._apply_filters)
        btn_clear = widgets.ghost_btn("Clear")
        btn_clear.clicked.connect(self._clear_filters)
        lay.addWidget(btn_clear)
        lay.addWidget(btn_apply)
        bar.setVisible(False)
        self.filter_bar = bar
        return bar

    def _toggle_filters(self, on):
        self.filter_bar.setVisible(on)

    def _apply_filters(self):
        f = self.filter
        f.date_from = ("" if self.ed_from.date() == self.ed_from.minimumDate()
                       else self.ed_from.date().toString("yyyy-MM-dd"))
        f.date_to = ("" if self.ed_to.date() == self.ed_to.minimumDate()
                     else self.ed_to.date().toString("yyyy-MM-dd"))
        f.instance_type = self.cb_instance.currentData() or ""
        f.min_rating = int(self.cb_rating.currentData() or 0)
        f.media = self.cb_media.currentData() or ""
        self.refresh()

    def _clear_filters(self):
        self.ed_from.setDate(self.ed_from.minimumDate())
        self.ed_to.setDate(self.ed_to.minimumDate())
        self.cb_instance.setCurrentIndex(0)
        self.cb_rating.setCurrentIndex(0)
        self.cb_media.setCurrentIndex(0)
        self._apply_filters()

    # ------- state -------
    def configure(self, f: PhotoFilter, title, back=False):
        self.filter = f
        self.title_text = title
        self.lab_title.setText(title)
        self.btn_back.setVisible(back)
        blocked = self.search.blockSignals(True)
        self.search.setText(f.text)
        self.search.blockSignals(blocked)
        b2 = self.btn_fav.blockSignals(True)
        self.btn_fav.setChecked(f.favorites)
        self.btn_fav.blockSignals(b2)
        b3 = self.sort_box.blockSignals(True)
        self.sort_box.setCurrentIndex(0 if f.sort_desc else 1)
        self.sort_box.blockSignals(b3)
        self._sync_filter_bar(f)
        self.refresh()
        self.view.setFocus()

    def _sync_filter_bar(self, f):
        """The bar must show what is actually applied, or Apply is a surprise."""
        d = QDate.fromString(f.date_from, "yyyy-MM-dd")
        self.ed_from.setDate(d if d.isValid() else self.ed_from.minimumDate())
        d = QDate.fromString(f.date_to, "yyyy-MM-dd")
        self.ed_to.setDate(d if d.isValid() else self.ed_to.minimumDate())
        for cb, val in ((self.cb_instance, f.instance_type),
                        (self.cb_rating, f.min_rating),
                        (self.cb_media, f.media)):
            ix = cb.findData(val)
            cb.setCurrentIndex(ix if ix >= 0 else 0)

    def refresh(self):
        self.filter.sort_desc = self.sort_box.currentIndex() == 0
        self._rows = self.db.query_photos(self.filter)
        self.model.set_photos(self._rows, group_by_day=True)
        n = len(self._rows)
        total = sum((r["filesize"] or 0) for r in self._rows)
        self.lab_sub.setText(f"{fmt.count_label(n)} {fmt.plural(n, 'photo')} · "
                             f"{fmt.human_size(total)}" if n else "No photos to show")
        self.empty.setVisible(n == 0)
        self.rail.set_marks(self.model.month_marks(), self.model.rowCount())
        self._position_overlays()

    def refresh_soft(self):
        """Re-query without resetting scroll if nothing structural changed upstream."""
        self.refresh()

    # ------- header handlers -------
    def _apply_search(self):
        self.filter.text = self.search.text().strip()
        self.refresh()

    def _on_fav_toggle(self, on):
        self.filter.favorites = on
        self.refresh()

    def _on_sort(self, _i):
        self.refresh()

    def _on_slider(self, v):
        self.delegate.set_cell_width(v)
        self.cfg.set("thumb_px", v, save=False)
        self.view.scheduleDelayedItemsLayout()
        self.view.viewport().update()

    def _start_slideshow(self):
        photos = self.model.photos()
        if photos:
            pos = 0
            sel = self.view.selected_photo_items()
            if sel:
                try:
                    pos = photos.index(sel[0])
                except ValueError:
                    pos = 0
            self.main.start_slideshow(photos, pos)

    def _scroll_to_row(self, row):
        ix = self.model.index(max(0, min(row, self.model.rowCount() - 1)))
        if ix.isValid():
            self.view.scrollTo(ix, QAbstractItemView.PositionAtTop)

    def _sync_rail(self, _v=0):
        """Report the position as a MODEL ROW, not a pixel fraction.

        The rail draws its month ticks at row positions; a scrollbar fraction is
        a pixel fraction, and the two are not proportional because day headers
        are full-width rows among small square cells. Asking the view which item
        is at the top keeps the marker on the tick it belongs to.
        """
        ix = self.view.indexAt(self.view.viewport().rect().topLeft())
        if not ix.isValid():
            bar = self.view.verticalScrollBar()
            span = max(1, bar.maximum() - bar.minimum())
            frac = (bar.value() - bar.minimum()) / span
            self.rail.set_row(frac * max(0, self.model.rowCount() - 1))
            return
        self.rail.set_row(ix.row())

    # ------- selection / actions -------
    def _selected_items(self):
        return self.view.selected_photo_items()

    def _sel_changed(self, *_a):
        items = self._selected_items()
        if len(items) >= 2:
            total = sum(i.filesize or 0 for i in items)
            was_hidden = not self.selbar.isVisible()
            self.selbar.set_count(len(items), fmt.human_size(total))
            self.selbar.adjustSize()
            self.selbar.show()
            self._position_overlays(animate_selbar=was_hidden)
            self.selbar.raise_()
        else:
            self.selbar.hide()

    def _open_from_index(self, ix):
        pos = self.model.photo_pos(ix.row())
        if pos >= 0:
            self.main.open_lightbox(self, self.model.photos(), pos)

    def _fav_selection(self):
        items = self._selected_items()
        if items:
            self.main.act_favorite([i.id for i in items])

    def _album_selection(self):
        items = self._selected_items()
        if items:
            self.main.act_album_menu([i.id for i in items], self.selbar.btn_album)

    def _delete_selection(self):
        items = self._selected_items()
        if items:
            self.main.act_recycle(items, after=self.refresh)

    def _context_menu(self, gpos, ix):
        items = self._selected_items()
        if ix.isValid() and ix.data(KindRole) == KIND_PHOTO:
            it = ix.data(ItemRole)
            if it not in items:
                items = [it]
        if not items:
            return
        self.main.show_photo_menu(gpos, items, self)

    # ------- layout of floating overlays -------
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._position_overlays()

    def _position_overlays(self, animate_selbar=False):
        if self.empty.isVisible():
            self.empty.resize(self.view.size())
            self.empty.move(0, 0)
        if self.selbar.isVisible():
            x = (self.width() - self.selbar.width()) // 2
            y = self.height() - self.selbar.height() - 18
            if animate_selbar:
                self.selbar.slide_to(x, y)
            else:
                self.selbar.move(x, y)
