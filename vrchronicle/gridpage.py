"""The photo-grid page (used for: all photos, favorites, world/person/album/day drills)."""
from PySide6.QtCore import (QDate, QEvent, QPoint, QPointF, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDateEdit,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from . import fmt, icons, style, vrclog, widgets
from .db import PhotoFilter
from .gridmodel import (GridModel, GridView, PhotoDelegate, KIND_PERIOD,
                        KIND_PHOTO, ItemRole, KindRole)


class _RailBubble(QWidget):
    """The month label the timeline rail shows while you drag it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._accent = "#3d8bff"
        self._glass = None

    def set_text(self, text, accent):
        self._text, self._accent = text, accent
        f = QFont()
        f.setPointSizeF(9.0)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        self.resize(fm.horizontalAdvance(text) + 22, fm.height() + 12)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        f = QFont()
        f.setPointSizeF(9.0)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not widgets.Glass.paint(p, self, self._glass, radius=9,
                                   tint="#0c0e14", tint_alpha=165):
            p.setBrush(QColor(12, 14, 20, 242))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 9, 9)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(self._accent), 1))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QColor(style.PAL["text"]))
        p.drawText(r, Qt.AlignCenter, self._text)
        p.end()


class TimelineRail(QWidget):
    """A thin month scale beside the grid: click or drag to jump through years.

    Everything here is in CONTENT PIXELS, not model rows. A day header is one
    row and a whole band; twenty photos are twenty rows in three bands. Placing
    the marks by row index therefore put the year labels well away from where
    that year actually starts.
    """
    jump_to = Signal(int)         # a vertical scrollbar value

    WIDTH = 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self._marks = []          # (content_y_px, "YYYY-MM")
        self._total = 1           # full content height in px
        self._pos = 0.0           # current scroll value in px
        self._hover_y = None      # where the pointer is, for the month bubble
        self._bubble = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_marks(self, marks, total):
        self._marks = marks
        self._total = max(1, total)
        self.setVisible(len(marks) > 1)
        self.update()

    def set_pos(self, px):
        self._pos = max(0.0, min(float(self._total), float(px)))
        self.update()

    def _y_for(self, px):
        top, bottom = 10, self.height() - 10
        return top + (bottom - top) * (min(px, self._total) / self._total)

    def _px_at(self, y):
        top, bottom = 10, self.height() - 10
        frac = (y - top) / max(1, bottom - top)
        return int(round(max(0.0, min(1.0, frac)) * self._total))

    def _accent_key(self):
        page = self.parent()
        cfg = getattr(page, "cfg", None)
        return cfg.get("accent") if cfg is not None else style.DEFAULT_ACCENT

    def _month_at(self, px):
        """The month whose start is the last one at or above this point."""
        if not self._marks:
            return ""
        best = self._marks[0][1]
        for mark_px, ym in self._marks:
            if mark_px <= px:
                best = ym
            else:
                break
        return best

    def paintEvent(self, _ev):
        if len(self._marks) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        f = QFont()
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        right = self.WIDTH - 5

        # Months are ticks only. Spelling every month out turned the rail into a
        # column of tiny words with no hierarchy; the year is what you navigate by.
        last_year = None
        year_ys = []
        for px, ym in self._marks:
            y = self._y_for(px)
            year = ym[:4]
            if year != last_year:
                year_ys.append((y, year))
            else:
                p.setPen(QColor(style.PAL["border2"]))
                p.drawLine(right - 5, int(y), right, int(y))
            last_year = year

        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        last_label = -999
        for y, year in year_ys:
            p.setPen(QColor(style.PAL["border"]))
            p.drawLine(right - 9, int(y), right, int(y))
            if y - last_label > fm.height() + 4:
                p.setPen(QColor(style.PAL["dim"]))
                p.drawText(QRectF(0, y - fm.height() / 2, right - 12, fm.height()),
                           Qt.AlignRight | Qt.AlignVCenter, year)
                last_label = y

        ac = style.accent(self._accent_key())
        y = self._y_for(self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ac["a"]))
        p.drawRoundedRect(QRectF(right - 11, y - 2.5, 11, 5), 2.5, 2.5)

        p.end()

    # The bubble lives on the page, not on the rail: the rail is 54 px wide and
    # anything wider than that is simply clipped away by its own bounds.
    def _show_bubble(self, y):
        label = fmt.month_label(self._month_at(self._px_at(y)))
        page = self.parentWidget()
        if not label or page is None:
            return self._hide_bubble()
        if self._bubble is None:
            self._bubble = _RailBubble(page)
            self._bubble._glass = getattr(page, "view", None)
        self._bubble.set_text(label, style.accent(self._accent_key())["a"])
        w, h = self._bubble.width(), self._bubble.height()
        top_left = self.mapTo(page, QPoint(0, 0))
        x = max(4, top_left.x() - w - 8)
        by = min(max(4, top_left.y() + int(y) - h // 2), page.height() - h - 4)
        self._bubble.move(x, by)
        self._bubble.raise_()
        self._bubble.show()

    def _hide_bubble(self):
        if self._bubble is not None:
            self._bubble.hide()

    def leaveEvent(self, ev):
        self._hover_y = None
        self._hide_bubble()
        self.update()
        super().leaveEvent(ev)

    def hideEvent(self, ev):
        self._hide_bubble()
        super().hideEvent(ev)

    def mousePressEvent(self, ev):
        self.jump_to.emit(self._px_at(ev.position().y()))

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self.jump_to.emit(self._px_at(ev.position().y()))
        self._hover_y = ev.position().y()     # names the month you are aiming at
        self._show_bubble(self._hover_y)
        self.update()


class StickyDay(QWidget):
    """The day you are inside, pinned to the top of the grid while you scroll.

    It is the grid's own day header, frozen -- not a card of its own. So it
    keeps that row's exact left inset: made into a floating pill it sat 21px
    further right, and the text jumped sideways the moment a day pinned.
    """

    HEIGHT = 40
    PAD = 11          # where the grid draws its day headers, measured

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._day = ""
        self._count = 0
        self._glass = None
        self.hide()

    def set_day(self, day, count):
        if (day, count) != (self._day, self._count):
            self._day, self._count = day, count
            self.update()

    def set_glass_source(self, w):
        self._glass = w

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        # Solid and square: it spans the whole width while the photos under it
        # only reach partway across, so glass here would be half smeared
        # picture and half flat background.
        p.fillRect(r, QColor(style.PAL["bg"]))
        p.setPen(QPen(QColor(style.PAL["border"]), 1))
        p.drawLine(QPointF(r.left(), r.bottom() - 0.5),
                   QPointF(r.right(), r.bottom() - 0.5))
        f = QFont()
        f.setPointSizeF(10.5)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        text_r = r.adjusted(self.PAD, 0, -self.PAD, 0)
        p.setPen(QColor(style.PAL["text"]))
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter, fmt.day_label(self._day))
        f2 = QFont(f)
        f2.setWeight(QFont.Normal)
        f2.setPointSizeF(9.5)
        p.setFont(f2)
        p.setPen(QColor(style.PAL["faint"]))
        p.drawText(text_r, Qt.AlignRight | Qt.AlignVCenter,
                   f"{self._count} {fmt.plural(self._count, 'photo')}")
        p.end()


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
        self.level = "day"          # 'year' | 'month' | 'day'
        self._level_year = ""       # which year the Months level is showing
        self._levels_on = False     # only the Photos page browses by period

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The header floats over the grid so the photos scroll underneath it and
        # show through the glass. The grid gets a spacer row of the same height
        # so nothing starts life hidden behind it.
        self.headbar = widgets.GlassBar(self, radius=16)
        head = QHBoxLayout(self.headbar)
        head.setContentsMargins(24, 10, 24, 10)
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
        head.addSpacing(18)

        # Years / Months / Days, the way a photo library is normally browsed:
        # zoom out to find the stretch of time, then zoom in on it.
        self.levels = QWidget()
        lv = QHBoxLayout(self.levels)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.level_group = QButtonGroup(self)
        self.level_group.setExclusive(True)
        for key, label in (("year", "Years"), ("month", "Months"), ("day", "Days")):
            b = QPushButton(label)
            b.setObjectName("PillBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("level", key)
            b.setChecked(key == "day")
            self.level_group.addButton(b)
            lv.addWidget(b)
        self.level_group.buttonClicked.connect(
            lambda b: self._level_clicked(b.property("level")))
        head.addWidget(self.levels)
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
        self.sort_box.setObjectName("OnGlass")
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

        self.btn_filter = widgets.icon_btn("filter", "More filters", style.PAL["dim"],
                                           checkable=True)
        self.btn_filter.toggled.connect(self._toggle_filters)
        head.addWidget(self.btn_filter)
        self.btn_play = widgets.icon_btn("play", "Slideshow", style.PAL["dim"])
        self.btn_play.clicked.connect(self._start_slideshow)
        head.addWidget(self.btn_play)
        # header + filter bar ride together as one floating overlay
        self.headwrap = QWidget(self)
        hw = QVBoxLayout(self.headwrap)
        hw.setContentsMargins(0, 0, 0, 0)
        hw.setSpacing(0)
        hw.addWidget(self.headbar)
        hw.addWidget(self._build_filter_bar())

        # --- grid ---
        self.model = GridModel(self)
        self.view = GridView(self)
        self.view.setModel(self.model)
        self.delegate = PhotoDelegate(self.view, cache, self)
        self.delegate.set_cell_width(self.slider.value())
        self.delegate.set_accent(style.accent(self.cfg.get("accent"))["a"])
        self.view.setItemDelegate(self.delegate)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(6)
        body.addWidget(self.view, 1)
        self.rail = TimelineRail(self)
        self.rail.jump_to.connect(self._scroll_to_px)
        body.addWidget(self.rail)
        root.addLayout(body, 1)
        self.view.verticalScrollBar().valueChanged.connect(self._sync_rail)
        # The floating bars are bound to the viewport, and the viewport shrinks
        # whenever the scrollbar or the rail appears -- which the page's own
        # resizeEvent never hears about.
        self.view.viewport().installEventFilter(self)

        cache.ready.connect(self.model.notify_thumb)
        self.delegate.fav_clicked.connect(lambda pid: self.main.act_favorite([pid]))
        self.view.open_requested.connect(self._open_from_index)
        self.view.fav_key.connect(self._fav_selection)
        self.view.delete_key.connect(self._delete_selection)
        self.view.context_requested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)
        self.view.zoom_requested.connect(self._zoom_by)

        # --- empty state + selection bar (floating) ---
        self.empty = widgets.EmptyState("image", "Nothing here",
                                        "Your VRChat shots will show up here.", self.view)
        self.empty.hide()
        self.headbar.set_glass_source(self.view.viewport())
        self.sticky = StickyDay(self)
        self.sticky.set_glass_source(self.view.viewport())
        self.selbar = widgets.SelectionBar(self)
        self.selbar.set_glass_source(self.view.viewport())
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
    def configure(self, f: PhotoFilter, title, back=False, levels=False):
        self.filter = f
        self.title_text = title
        self.lab_title.setText(title)
        self.btn_back.setVisible(back)
        self._levels_on = levels
        self.levels.setVisible(levels)
        if not levels:
            self.level = "day"
            self._level_year = ""
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

    def _level_clicked(self, level):
        """Picking a level from the control, rather than drilling into a card."""
        if level == "day":
            # a month card narrows the dates; asking for Days means all of them
            self.filter.date_from = self.filter.date_to = ""
            self._sync_filter_bar(self.filter)
        elif level == "year":
            self._level_year = ""
        self.set_level(level, self._level_year if level == "month" else "")

    def set_level(self, level, year=""):
        """Zoom the library: 'year' -> 'month' -> 'day'."""
        self.level = level
        if level != "month" or year:
            self._level_year = year
        for b in self.level_group.buttons():
            b.setChecked(b.property("level") == level)
        self.refresh()
        self.view.verticalScrollBar().setValue(0)

    def _period_widgets_visible(self, periods):
        """Sorting, thumbnail size, filters and the rail are about photos."""
        for w in (self.sort_box, self.slider, self.btn_filter, self.btn_fav, self.btn_play):
            w.setVisible(not periods)
        if periods:
            self.btn_filter.setChecked(False)
        self.rail.setVisible(not periods and self.rail_has_marks())

    def rail_has_marks(self):
        return len(getattr(self.rail, "_marks", [])) > 1

    def refresh(self):
        periods = self._levels_on and self.level in ("year", "month")
        self._period_widgets_visible(periods)
        if periods:
            rows = self.db.period_summary(self.level, self._level_year)
            covers = self.db.photos_by_ids([r["cover_id"] for r in rows])
            self.model.set_periods(rows, self.level, covers,
                                   top_gap=self.head_height())
            n = sum(r["c"] for r in rows)
            total = sum(r["b"] or 0 for r in rows)
            what = "year" if self.level == "year" else "month"
            head = f"{len(rows)} {fmt.plural(len(rows), what)}"
            if self._level_year:
                head = f"{self._level_year} · {head}"
            self.lab_sub.setText(
                f"{head} · {fmt.count_label(n)} {fmt.plural(n, 'photo')} · "
                f"{fmt.human_size(total)}" if rows else "No photos to show")
            self.empty.setVisible(not rows)
            self._position_overlays()
            return
        self.filter.sort_desc = self.sort_box.currentIndex() == 0
        self._rows = self.db.query_photos(self.filter)
        self.model.set_photos(self._rows, group_by_day=True,
                              top_gap=self.head_height())
        n = len(self._rows)
        total = sum((r["filesize"] or 0) for r in self._rows)
        self.lab_sub.setText(f"{fmt.count_label(n)} {fmt.plural(n, 'photo')} · "
                             f"{fmt.human_size(total)}" if n else "No photos to show")
        self.empty.setVisible(n == 0)
        QTimer.singleShot(0, self._refresh_rail)   # after the view lays out
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
        # a different cell size wraps differently, so every month moves
        QTimer.singleShot(0, self._refresh_rail)

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

    def _scroll_to_px(self, px):
        bar = self.view.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), int(px))))

    def rail_marks(self):
        """[(content_y_px, 'YYYY-MM')], full content height -- what the rail draws.

        visualRect is in viewport coordinates, so adding the current scroll
        value turns it into a position in the whole scrolled content.
        """
        bar = self.view.verticalScrollBar()
        off = bar.value()
        marks = []
        for row, ym in self.model.month_marks():
            r = self.view.visualRect(self.model.index(row, 0))
            marks.append((max(0, r.y() + off), ym))
        marks.sort()
        total = bar.maximum() + self.view.viewport().height()
        return marks, max(1, total)

    def _refresh_rail(self):
        self.rail.set_marks(*self.rail_marks())
        self._sync_rail()

    def _sync_rail(self, _v=0):
        self.rail.set_pos(self.view.verticalScrollBar().value())
        self._sync_sticky()

    def _top_index(self):
        """First item under the floating header, skipping the layout gaps."""
        w = self.view.viewport().width()
        start = self.head_height() + 2
        for y in range(start, start + 60, 4):
            for x in (8, w // 2, max(8, w - 14)):
                ix = self.view.indexAt(QPoint(x, y))
                if ix.isValid():
                    return ix
        return None

    def _sync_sticky(self):
        """Pin the day you are inside, but not while its real header is visible."""
        if self.level in ("year", "month") or not self.model.rowCount():
            self.sticky.hide()
            return
        ix = self._top_index()
        info = self.model.day_of_row(ix.row()) if ix is not None else None
        if info is None:
            self.sticky.hide()
            return
        day, count, head_row = info
        if head_row >= 0:
            real = self.view.visualRect(self.model.index(head_row, 0))
            # While ANY of the real header is still on screen, do not pin: the
            # pinned copy would sit on top of it and its own text would ghost
            # through the glass.
            if real.bottom() > 0:
                self.sticky.hide()
                return
        self.sticky.set_day(day, count)
        self._place_sticky()
        self.sticky.show()
        self.sticky.raise_()

    def _place_sticky(self):
        # the viewport, not the view: it must not lie across the scrollbar, and
        # the glass under it can only be sampled from the viewport anyway
        vp = self.view.viewport()
        pos = vp.mapTo(self, QPoint(0, 0))
        self.sticky.setGeometry(pos.x(), pos.y() + self.head_height(),
                                vp.width(), StickyDay.HEIGHT)

    def _zoom_by(self, steps):
        """Ctrl+wheel: resize the thumbnails and stay where you were."""
        ix = self._top_index()
        row = ix.row() if ix is not None else -1
        before = self.slider.value()
        self.slider.setValue(max(self.slider.minimum(),
                                 min(self.slider.maximum(), before + steps * 16)))
        if self.slider.value() == before or row < 0:
            return

        def keep_place():
            target = self.model.index(row, 0)
            if target.isValid():
                self.view.scrollTo(target, QAbstractItemView.PositionAtTop)
            self._refresh_rail()
        QTimer.singleShot(0, keep_place)

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
        if ix.data(KindRole) == KIND_PERIOD:
            d = ix.data(ItemRole)
            if d["level"] == "year":
                self.set_level("month", d["key"])
            else:
                self.show_month(d["key"])
            return
        pos = self.model.photo_pos(ix.row())
        if pos >= 0:
            self.main.open_lightbox(self, self.model.photos(), pos)

    def show_month(self, ym):
        """Drill from a month card into that month's days."""
        year, month = int(ym[:4]), int(ym[5:7])
        last = QDate(year, month, 1).daysInMonth()
        self.filter.date_from = f"{ym}-01"
        self.filter.date_to = f"{ym}-{last:02d}"
        self._sync_filter_bar(self.filter)
        self.set_level("day")

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
        QTimer.singleShot(0, self._refresh_rail)   # rewrapping moves every month

    HEAD_MARGIN = 8       # the floating header keeps the window's own border

    def eventFilter(self, obj, ev):
        if obj is self.view.viewport() and ev.type() == QEvent.Resize:
            self._position_overlays()
        return super().eventFilter(obj, ev)

    def head_height(self):
        """What the grid has to leave free at the top, margins included."""
        if not hasattr(self, "headwrap"):
            return 0
        return self.headwrap.sizeHint().height() + self.HEAD_MARGIN

    def _position_overlays(self, animate_selbar=False):
        if hasattr(self, "headwrap"):
            # Bound to the VIEWPORT, so the bar clears the scrollbar and the
            # timeline rail rather than lying across either of them.
            m = self.HEAD_MARGIN
            vp = self.view.viewport()
            tl = vp.mapTo(self, QPoint(0, 0))
            # Flush with the top: an inset there leaves a sliver of scrolled
            # photo peeking over the bar, which reads as a glitch rather than
            # as depth.
            self.headwrap.setGeometry(tl.x() + m, 0,
                                      max(160, vp.width() - m * 2),
                                      self.headwrap.sizeHint().height())
            self.headwrap.raise_()
        if self.sticky.isVisible():
            self._place_sticky()
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
