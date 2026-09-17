"""Secondary pages: worlds/people/albums cards, memories, stats, cleanup, settings."""
import os
from datetime import date, datetime

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QThread,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListView, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from . import (backup, charts, fmt, icons, imaging, moments, paths, questimport, style,
               vrclog, widgets, winutil)
from .db import PhotoFilter
from .gridmodel import MiniItem

CardRole = Qt.UserRole + 1

# Lives with parse_instance, which is where regions are read out of an
# instance id; re-exported here because the charts have always used this name.
REGION_NAMES = vrclog.REGION_NAMES


def page_header(title, sub=""):
    box = QVBoxLayout()
    box.setSpacing(0)
    t = QLabel(title)
    t.setObjectName("PageHeaderTitle")
    s = QLabel(sub)
    s.setObjectName("PageHeaderSub")
    box.addWidget(t)
    box.addWidget(s)
    return box, t, s


# ---------------------------------------------------------------- card pages

class CardModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards = []   # dicts: kind('item'|'new'), title, sub, cover(MiniItem|None), payload

    def set_cards(self, cards):
        self.beginResetModel()
        self.cards = cards
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cards)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == CardRole:
            return self.cards[index.row()]
        return None

    def flags(self, index):
        card = index.data(CardRole)
        if card and card["kind"] == "spacer":
            return Qt.NoItemFlags       # nothing to click, hover or arrow onto
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class CardDelegate(QStyledItemDelegate):
    W, H, COVER_H = 230, 192, 130

    def __init__(self, view, cache, parent=None):
        super().__init__(parent)
        self.view = view
        self.cache = cache
        self._f_title = QFont()
        self._f_title.setPointSizeF(10)
        self._f_title.setWeight(QFont.DemiBold)
        self._f_sub = QFont()
        self._f_sub.setPointSizeF(8.5)

    def sizeHint(self, option, index):
        card = index.data(CardRole)
        # The first row is a blank the height of the floating header, so the
        # cards can scroll underneath it instead of starting behind it. Made as
        # wide as the viewport, which is what pushes the real cards onto the
        # next line.
        if card and card["kind"] == "spacer":
            return QSize(max(80, self.view.viewport().width() - 24),
                         max(1, card["height"]))
        return QSize(self.W, self.H)

    def paint(self, p, option, index):
        card = index.data(CardRole)
        if not card or card["kind"] == "spacer":
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(option.rect).adjusted(0, 0, 0, 0)
        hovered = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        if card["kind"] == "new":
            pen = QPen(QColor(style.PAL["border2"]), 1.6, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(style.PAL["surface"]) if hovered else Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 14, 14)
            glyph = icons.pixmap("plus", style.PAL["dim"], 24, self.view.devicePixelRatioF())
            p.drawPixmap(int(r.center().x() - 12), int(r.center().y() - 26), glyph)
            p.setFont(self._f_title)
            p.setPen(QColor(style.PAL["dim"]))
            p.drawText(QRectF(r.x(), r.center().y() + 4, r.width(), 22),
                       Qt.AlignCenter, card["title"])
            p.restore()
            return
        p.setClipPath(path)
        p.fillRect(r, QColor(style.PAL["hover"] if hovered else style.PAL["surface"]))
        cover_r = QRectF(r.x(), r.y(), r.width(), self.COVER_H)
        pm = self.cache.get(card["cover"]) if card["cover"] else None
        if pm and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            scale = max(cover_r.width() / pw, cover_r.height() / ph)
            dw, dh = pw * scale, ph * scale
            # Clipped to the BAND, not just to the card. The cover is sized to
            # fill cover_r, so anything not 16:9 is taller than the band and the
            # overflow used to run straight down over the title -- which is why
            # some Worlds cards had their name sitting on the photo and others
            # had it on the plate below. The clip is what makes them agree.
            p.save()
            p.setClipRect(cover_r, Qt.IntersectClip)
            p.drawPixmap(QRectF(cover_r.x() + (cover_r.width() - dw) / 2,
                                cover_r.y() + (cover_r.height() - dh) / 2, dw, dh),
                         pm, QRectF(0, 0, pw, ph))
            p.restore()
            g = QLinearGradient(0, cover_r.bottom() - 34, 0, cover_r.bottom())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 60))
            p.fillRect(QRectF(cover_r.x(), cover_r.bottom() - 34, cover_r.width(), 34), g)
        else:
            p.fillRect(cover_r, QColor(style.PAL["surface2"]))
            glyph = icons.pixmap(card.get("icon", "image"), style.PAL["border2"], 30,
                                 self.view.devicePixelRatioF(), width=1.5)
            p.drawPixmap(int(cover_r.center().x() - 15), int(cover_r.center().y() - 15), glyph)
        fm = QFontMetrics(self._f_title)
        p.setFont(self._f_title)
        p.setPen(QColor(style.PAL["text"]))
        p.drawText(QRectF(r.x() + 13, cover_r.bottom() + 8, r.width() - 26, 20),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(card["title"], Qt.ElideRight, int(r.width()) - 26))
        p.setFont(self._f_sub)
        p.setPen(QColor(style.PAL["dim"]))
        p.drawText(QRectF(r.x() + 13, cover_r.bottom() + 30, r.width() - 26, 16),
                   Qt.AlignLeft | Qt.AlignVCenter, card["sub"])
        p.setClipping(False)
        if hovered:
            p.setPen(QPen(QColor(style.PAL["border2"]), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.7, 0.7, -0.7, -0.7), 14, 14)
        p.restore()


class CardsPage(QWidget):
    """Generic card grid: worlds, people, albums."""

    def __init__(self, main, cache, title, icon_name, searchable=True, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self.icon_name = icon_name
        self._all_cards = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.head = widgets.PageHead(self, title)
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("Filter…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.qicon("search", style.PAL["faint"], 15),
                              QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._apply_filter)
        if searchable:
            self.head.add_flexible(self.search, 120, 220)
        else:
            self.search.hide()
        self.model = CardModel(self)
        self.view = QListView()
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setWrapping(True)
        self.view.setSpacing(9)
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.verticalScrollBar().setSingleStep(48)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFrameShape(QListView.NoFrame)
        self.view.setModel(self.model)
        self.delegate = CardDelegate(self.view, cache, self)
        self.view.setItemDelegate(self.delegate)
        self.smooth = widgets.SmoothScroll(self.view)
        self.view.clicked.connect(self._clicked)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context)
        cache.ready.connect(lambda _pid: self.view.viewport().update())
        body = QHBoxLayout()
        body.setContentsMargins(24, 0, 8, 0)
        body.addWidget(self.view, 1)
        root.addLayout(body, 1)
        self.head.attach(self.view)
        self.head.viewport_resized.connect(self.view.scheduleDelayedItemsLayout)
        self.empty = widgets.EmptyState(icon_name, "Nothing here yet", "", self.view)
        self.empty.hide()

    # override points
    def build_cards(self):
        return []

    def card_activated(self, card):
        pass

    def card_context(self, card, gpos):
        pass

    def refresh(self):
        self._all_cards = self.build_cards()
        self._apply_filter()
        self.view.setFocus()      # don't hand the caret to the filter box on arrival

    def _apply_filter(self):
        t = self.search.text().strip().lower()
        cards = [c for c in self._all_cards
                 if not t or t in c["title"].lower() or c["kind"] == "new"]
        spacer = {"kind": "spacer", "title": "", "sub": "",
                  "cover": None, "height": self.head.reserved()}
        self.model.set_cards([spacer] + cards)
        n = sum(1 for c in cards if c["kind"] != "new")
        self.lab_sub.setText(f"{fmt.count_label(n)} {fmt.plural(n, 'item')}")
        # A page holding an action card ("New album") is not empty: covering it
        # with the empty state would hide the one thing there is to click.
        self.empty.setVisible(not cards)
        self.empty.resize(self.view.size())

    def _clicked(self, ix):
        card = ix.data(CardRole)
        if card and card["kind"] != "spacer":
            self.card_activated(card)

    def _context(self, pos):
        ix = self.view.indexAt(pos)
        card = ix.data(CardRole) if ix.isValid() else None
        if card and card["kind"] != "spacer":
            self.card_context(card, self.view.viewport().mapToGlobal(pos))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.empty.isVisible():
            self.empty.resize(self.view.size())


class WorldsPage(CardsPage):
    def __init__(self, main, cache, parent=None):
        super().__init__(main, cache, "Worlds", "globe", parent=parent)
        self.empty.set_text("No world data yet",
                            "Worlds attach to your photos from VRCX metadata and "
                            f"the VRChat logs — keep {paths.APP_NAME} running while you play.")

    def build_cards(self):
        rows = self.main.db.worlds_summary()
        covers = self.main.db.photos_by_ids([r["cover_id"] for r in rows])
        cards = []
        for r in rows:
            c = covers.get(r["cover_id"])
            mini = MiniItem(c["id"], c["path"], c["mtime"], c["filesize"], c["scanned"]) if c else None
            last = fmt.date_short(r["last"]) if r["last"] else ""
            cards.append({"kind": "item", "title": r["name"] or "?", "icon": "globe",
                          "sub": f'{r["cnt"]} {fmt.plural(r["cnt"], "photo")} · {last}',
                          "cover": mini,
                          "payload": (r["world_id"], r["name"])})
        return cards

    def card_activated(self, card):
        wid, name = card["payload"]
        self.main.push_world(wid, name)


class PeoplePage(CardsPage):
    def __init__(self, main, cache, parent=None):
        super().__init__(main, cache, "People", "users", parent=parent)
        self.empty.set_text("No people data yet",
                            f"{paths.APP_NAME} learns who was in the instance with you "
                            "from VRCX metadata and the VRChat logs.")

    def build_cards(self):
        rows = self.main.db.people_summary(sorted(self.main.cfg.self_names))
        covers = self.main.db.photos_by_ids([r["cover_id"] for r in rows])
        cards = []
        for r in rows:
            c = covers.get(r["cover_id"])
            mini = MiniItem(c["id"], c["path"], c["mtime"], c["filesize"], c["scanned"]) if c else None
            last = fmt.date_short(r["last"]) if r["last"] else ""
            cards.append({"kind": "item", "title": r["name"], "icon": "users",
                          "sub": f'{r["cnt"]} {fmt.plural(r["cnt"], "photo")} · {last}',
                          "cover": mini,
                          "payload": r["name"]})
        return cards

    def card_activated(self, card):
        self.main.show_person(card["payload"])


class AvatarsPage(CardsPage):
    def __init__(self, main, cache, parent=None):
        super().__init__(main, cache, "Avatars", "user-check", parent=parent)
        self.empty.set_text("No avatar data yet",
                            "The VRChat log records every avatar switch, so each photo "
                            "can remember which avatar you were wearing.")

    def build_cards(self):
        rows = self.main.db.avatars_summary()
        covers = self.main.db.photos_by_ids([r["cover_id"] for r in rows])
        cards = []
        for r in rows:
            c = covers.get(r["cover_id"])
            mini = MiniItem(c["id"], c["path"], c["mtime"], c["filesize"], c["scanned"]) if c else None
            last = fmt.date_short(r["last"]) if r["last"] else ""
            cards.append({"kind": "item", "title": r["name"], "icon": "user-check",
                          "sub": f'{r["cnt"]} {fmt.plural(r["cnt"], "photo")} · {last}',
                          "cover": mini, "payload": r["name"]})
        return cards

    def card_activated(self, card):
        self.main.push_avatar(card["payload"])


class SessionsPage(QWidget):
    """Every play session that produced photos, as a little diary."""

    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self._stamp = None
        self.scroll, self.holder, self.vbox = widgets.scroll_body(self)
        self.head = widgets.PageHead(self, "Sessions")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.head.attach(self.scroll, reserve_in=self.vbox)

    @staticmethod
    def _empty_state():
        # see MemoriesPage._empty_state — refresh() destroys the layout's children
        return widgets.EmptyState(
            "film", "No sessions yet",
            "A session is one visit to one world. They come from the VRChat logs, "
            f"so keep {paths.APP_NAME} running while you play.")

    def refresh(self, force=False):
        # Same guard MomentsPage has had all along: rebuilding 160 session
        # cards, their people chips and their thumbnail strips took 93 ms, and
        # it ran on every single visit whether or not anything had changed.
        selfn = sorted(self.main.cfg.self_names)
        stamp = self.main.db.sessions_stamp(selfn)
        if not force and stamp == self._stamp and self.vbox.count():
            return
        self._stamp = stamp
        while self.vbox.count():
            it = self.vbox.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = self.main.db.sessions_with_photos(200)
        if not rows:
            self.vbox.addWidget(self._empty_state())
            self.vbox.addStretch(1)
            self.lab_sub.setText("Nothing recorded yet")
            return
        self.lab_sub.setText(f"{len(rows)} {fmt.plural(len(rows), 'session')} with photos")
        covers = self.main.db.photos_by_ids([r["cover_id"] for r in rows])
        widgets.fill_progressively(
            self, self.vbox, rows, lambda r: self._session_card(r, selfn, covers))

    def _session_card(self, r, selfn, covers):
        sid = r["id"]
        card = widgets.Card()
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(r["world_name"] or "Unknown world")
        title.setStyleSheet("font-size:14px; font-weight:600;")
        top.addWidget(title)
        when = QLabel(fmt.dt_label(r["start_at"]) + self._duration(r))
        when.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
        top.addWidget(when)
        itype = r["instance_type"] or ""
        if itype:
            from . import vrclog
            private = itype in vrclog.PRIVATE_INSTANCES
            badge = QLabel(("🔒 " if private else "") +
                           vrclog.INSTANCE_LABELS.get(itype, itype))
            badge.setStyleSheet(
                "color:%s; font-size:11px;" % (style.PAL["star"] if private
                                               else style.PAL["faint"]))
            top.addWidget(badge)
        top.addStretch(1)
        cnt = QLabel(f'{r["cnt"]} {fmt.plural(r["cnt"], "photo")} · {fmt.human_size(r["bytes"])}')
        cnt.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
        top.addWidget(cnt)
        btn = QPushButton("Open all")
        btn.setObjectName("LinkBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, s=sid, n=r["world_name"]:
                            self.main.push_session(s, n))
        top.addWidget(btn)
        btn_sheet = QPushButton("Contact sheet")
        btn_sheet.setObjectName("LinkBtn")
        btn_sheet.setCursor(Qt.PointingHandCursor)
        btn_sheet.clicked.connect(
            lambda _c=False, s=sid, n=r["world_name"], st=r["start_at"], c=r["cnt"]:
            self.main.act_contact_sheet(
                [x["id"] for x in self.main.db.query_photos(
                    PhotoFilter(session_id=s, sort_desc=False))],
                n or "VRChat", f"{c} photos · {fmt.dt_label(st)}"))
        top.addWidget(btn_sheet)
        card.vbox.addLayout(top)

        people = self.main.db.session_people(sid, selfn)
        if people:
            chips = QWidget()
            flow = widgets.FlowLayout(chips, 0, 6, 6)
            for name in people[:12]:
                b = QPushButton(name)
                b.setObjectName("Chip")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, n=name: self.main.push_person(n))
                flow.addWidget(b)
            if len(people) > 12:
                more = QLabel(f"+{len(people) - 12}")
                more.setStyleSheet("color:%s; font-size:12px;" % style.PAL["faint"])
                flow.addWidget(more)
            card.vbox.addWidget(chips)

        f = PhotoFilter(session_id=sid, sort_desc=False)
        photos = self.main.db.query_photos(f)[:9]
        if photos:
            strip = ThumbStrip()
            for prow in photos:
                mini = MiniItem(prow["id"], prow["path"], prow["mtime"], prow["filesize"], 1)
                strip.add(self.main, self.cache, mini,
                          lambda s=sid, n=r["world_name"]: self.main.push_session(s, n))
            card.vbox.addWidget(strip)
        return card

    @staticmethod
    def _duration(r):
        a, b = fmt.parse_iso(r["start_at"]), fmt.parse_iso(r["end_at"])
        if not a or not b:
            return ""
        mins = max(0, int((b - a).total_seconds() // 60))
        if mins < 1:
            return ""
        if mins < 60:
            return f"  ·  {mins} min"
        return f"  ·  {mins // 60} h {mins % 60:02d} min"


class PersonPage(QWidget):
    """One person: when you met, how often, where, and who else was around."""

    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self.name = ""
        self.scroll, holder, v = widgets.scroll_body(self)
        self.head = widgets.PageHead(self, "")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.btn_back = widgets.icon_btn("arrow-left", "Back", style.PAL["text"], px=19)
        self.btn_back.clicked.connect(lambda: self.main.activate("people"))
        self.head.insert_front(self.btn_back)
        self.btn_all = widgets.ghost_btn("All photos", "image", primary=True)
        self.btn_all.clicked.connect(lambda: self.main.push_person(self.name))
        self.head.add(self.btn_all)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_photos = widgets.StatCard("image")
        self.t_worlds = widgets.StatCard("globe")
        self.t_first = widgets.StatCard("clock")
        self.t_last = widgets.StatCard("calendar")
        for t in (self.t_photos, self.t_worlds, self.t_first, self.t_last):
            tiles.addWidget(t)
        v.addLayout(tiles)

        self.card_strip = widgets.Card("RECENT TOGETHER")
        self.strip = ThumbStrip()
        self.card_strip.vbox.addWidget(self.strip)
        v.addWidget(self.card_strip)

        row = QHBoxLayout()
        row.setSpacing(12)
        c1 = widgets.Card("WHERE YOU MEET")
        self.chart_worlds = charts.HBarChart(self.main.cfg)
        c1.vbox.addWidget(self.chart_worlds)
        c2 = widgets.Card("USUALLY ALSO THERE")
        self.chart_together = charts.HBarChart(self.main.cfg)
        c2.vbox.addWidget(self.chart_together)
        row.addWidget(c1, 1)
        row.addWidget(c2, 1)
        v.addLayout(row)

        c3 = widgets.Card("PHOTOS TOGETHER, BY MONTH")
        self.chart_months = charts.BarChart(self.main.cfg)
        c3.vbox.addWidget(self.chart_months)
        v.addWidget(c3)
        v.addStretch(1)
        self.head.attach(self.scroll, reserve_in=v)

    def show_person(self, name):
        self.name = name
        self.lab_title.setText(name)
        selfn = sorted(self.main.cfg.self_names)
        s = self.main.db.person_stats(name, selfn)
        b = s["basic"]
        n = b["photos"] if b else 0
        self.t_photos.set(fmt.count_label(n), f"{fmt.plural(n, 'photo')} together")
        nw = (b["worlds"] or 0) if b else 0
        self.t_worlds.set(fmt.count_label(nw), f"{fmt.plural(nw, 'world')} together")

        # Session records only reach back as far as the logs VRGallery has seen,
        # while photos go back to the start of the library — so the earliest solid
        # evidence is whichever of the two is older.
        first_photo = (b["first_at"] if b else "") or ""
        sess = s["first_session"]
        first_sess = (sess["start_at"] if sess else "") or ""
        candidates = [c for c in (first_photo, first_sess) if c]
        first = min(candidates) if candidates else ""
        self.t_first.set(fmt.date_short(first) or "–", "first met")
        self.t_last.set(fmt.date_short((b["last_at"] if b else "") or "") or "–",
                        "last seen")
        if first_sess and first_sess == first and sess["world_name"]:
            self.lab_sub.setText(f"You first ran into each other in {sess['world_name']}")
        else:
            self.lab_sub.setText("Seen together in your photos")

        self.chart_worlds.set_data([(w["name"] or "?", w["c"]) for w in s["worlds"]])
        self.chart_together.set_data([(t["name"], t["c"]) for t in s["together"]])
        self.chart_months.set_data([(fmt.month_label(m["m"]), m["c"])
                                    for m in s["months"][-24:]])

        self.strip.clear()
        rows = self.main.db.query_photos(PhotoFilter(person=name))[:9]
        for prow in rows:
            mini = MiniItem(prow["id"], prow["path"], prow["mtime"], prow["filesize"], 1)
            self.strip.add(self.main, self.cache, mini,
                           lambda nm=name: self.main.push_person(nm))
        self.card_strip.setVisible(bool(rows))


class MomentsPage(QWidget):
    """Events the app found on its own — a night out, a party, a trip."""

    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self._moments = []
        self._stamp = None
        self.scroll, self.holder, self.vbox = widgets.scroll_body(self)
        self.head = widgets.PageHead(self, "Moments")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.btn_rescan = widgets.ghost_btn("Rescan", "refresh")
        self.btn_rescan.clicked.connect(lambda: self.refresh(force=True))
        self.head.add(self.btn_rescan)
        self.head.attach(self.scroll, reserve_in=self.vbox)

    @staticmethod
    def _empty_state():
        return widgets.EmptyState(
            "award", "No moments found yet",
            "A moment is a run of photos taken close together — a party, a meetup, "
            "a night out. Six or more shots in one sitting and it shows up here.")

    def refresh(self, force=False):
        # Detection walks the whole library, so re-running it on every index pass
        # would stall the UI during a play session. Nothing relevant changed ->
        # nothing to rebuild.
        selfn = sorted(self.main.cfg.self_names)
        stamp = self.main.db.moments_stamp(selfn)
        if not force and stamp == self._stamp and self.vbox.count():
            return
        self._stamp = stamp
        while self.vbox.count():
            it = self.vbox.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = self.main.db.moment_rows()
        by_photo = self.main.db.players_by_photo(selfn)
        self._moments = moments.detect(rows, by_photo)
        if not self._moments:
            self.vbox.addWidget(self._empty_state())
            self.vbox.addStretch(1)
            self.lab_sub.setText("Nothing clustered yet")
            return
        self.lab_sub.setText(f"{len(self._moments)} found automatically · "
                             "turn any of them into an album")
        widgets.fill_progressively(self, self.vbox, self._moments[:120], self._card)

    def _card(self, m):
        card = widgets.Card()
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(m["title"])
        title.setStyleSheet("font-size:14px; font-weight:600;")
        top.addWidget(title)
        span = QLabel(f'{fmt.time_label(m["start"])}–{fmt.time_label(m["end"])}')
        span.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
        top.addWidget(span)
        top.addStretch(1)
        cnt = QLabel(f'{m["count"]} {fmt.plural(m["count"], "photo")}')
        cnt.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
        top.addWidget(cnt)
        btn_album = QPushButton("Save as album")
        btn_album.setObjectName("LinkBtn")
        btn_album.setCursor(Qt.PointingHandCursor)
        btn_album.clicked.connect(lambda _c=False, mm=m: self._save_album(mm))
        top.addWidget(btn_album)
        btn_sheet = QPushButton("Contact sheet")
        btn_sheet.setObjectName("LinkBtn")
        btn_sheet.setCursor(Qt.PointingHandCursor)
        btn_sheet.clicked.connect(lambda _c=False, mm=m: self.main.act_contact_sheet(
            mm["ids"], mm["title"],
            f'{mm["count"]} photos · {fmt.dt_label(mm["start"])}'))
        top.addWidget(btn_sheet)
        card.vbox.addLayout(top)

        if m["people"]:
            chips = QWidget()
            flow = widgets.FlowLayout(chips, 0, 6, 6)
            for name in m["people"][:10]:
                b = QPushButton(name)
                b.setObjectName("Chip")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, n=name: self.main.push_person(n))
                flow.addWidget(b)
            card.vbox.addWidget(chips)

        strip = ThumbStrip(max_h=240)
        for prow in self.main.db.photos_by_ids_full(m["ids"][:9]):
            mini = MiniItem(prow["id"], prow["path"], prow["mtime"], prow["filesize"], 1)
            strip.add(self.main, self.cache, mini, lambda mm=m: self.main.push_moment(mm))
        card.vbox.addWidget(strip)
        return card

    def _save_album(self, m):
        name, ok = QInputDialog.getText(self, "Save as album", "Album name:",
                                        text=m["title"])
        name = (name or "").strip()
        if not (ok and name):
            return
        aid = self.main.db.create_album(name, datetime.now().isoformat(timespec="seconds"))
        if aid:
            self.main.db.album_add(aid, m["ids"],
                                   datetime.now().isoformat(timespec="seconds"))
            self.main.toast(f"Album “{name}” created with {len(m['ids'])} photos.", "ok")


class AlbumsPage(CardsPage):
    def __init__(self, main, cache, parent=None):
        super().__init__(main, cache, "Albums", "layers", searchable=False, parent=parent)

    def build_cards(self):
        cards = [{"kind": "new", "title": "New album", "sub": "", "cover": None,
                  "payload": None}]
        rows = self.main.db.albums()
        covers = self.main.db.photos_by_ids([r["cover_id"] for r in rows])
        for r in rows:
            c = covers.get(r["cover_id"])
            mini = MiniItem(c["id"], c["path"], c["mtime"], c["filesize"], c["scanned"]) if c else None
            cards.append({"kind": "item", "title": r["name"], "icon": "layers",
                          "sub": f'{r["cnt"]} {fmt.plural(r["cnt"], "photo")}', "cover": mini,
                          "payload": (r["id"], r["name"])})
        return cards

    def card_activated(self, card):
        if card["kind"] == "new":
            name, ok = QInputDialog.getText(self, "New album", "Album name:")
            name = (name or "").strip()
            if ok and name:
                self.main.db.create_album(name, datetime.now().isoformat(timespec="seconds"))
                self.refresh()
            return
        aid, name = card["payload"]
        self.main.push_album(aid, name)

    def card_context(self, card, gpos):
        if card["kind"] != "item":
            return
        aid, name = card["payload"]
        m = QMenu(self)
        act_open = m.addAction(icons.qicon("image", style.PAL["dim"], 16), "Open")
        act_ren = m.addAction(icons.qicon("edit", style.PAL["dim"], 16), "Rename…")
        m.addSeparator()
        act_del = m.addAction(icons.qicon("trash", style.PAL["danger"], 16), "Delete album")
        chosen = m.exec(gpos)
        if chosen == act_open:
            self.main.push_album(aid, name)
        elif chosen == act_ren:
            new, ok = QInputDialog.getText(self, "Rename album", "New name:", text=name)
            new = (new or "").strip()
            if ok and new and not self.main.db.rename_album(aid, new):
                self.main.toast("An album with that name already exists.", "err")
            self.refresh()
        elif chosen == act_del:
            if QMessageBox.question(
                    self, "Delete album",
                    f"Delete the album “{name}”? Your photos stay untouched.",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.main.db.delete_album(aid)
                self.refresh()


# ---------------------------------------------------------------- memories

class ThumbStripLabel(QWidget):
    """One clickable thumbnail in a memories strip."""

    def __init__(self, main, cache, item, on_click, w=158, h=88, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self.item = item
        self._on_click = on_click
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self._hover = False
        # Connecting every strip thumbnail to cache.ready would make one arriving
        # image wake all of them; the cache keeps a per-photo registry instead.
        cache.watch(item.id, self)

    def set_tile(self, w, h):
        self.setFixedSize(int(w), int(h))

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def _maybe_update(self, pid):
        if pid == self.item.id:
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        pm = self.cache.get(self.item)
        if pm and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            scale = max(r.width() / pw, r.height() / ph)
            dw, dh = pw * scale, ph * scale
            p.drawPixmap(QRectF(r.x() + (r.width() - dw) / 2, r.y() + (r.height() - dh) / 2,
                                dw, dh), pm, QRectF(0, 0, pw, ph))
        else:
            p.fillRect(r, QColor(style.PAL["surface2"]))
        if self._hover:                       # it is clickable, so it must say so
            p.setClipping(False)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 150), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)
        p.end()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._on_click:
            self._on_click()
        super().mouseReleaseEvent(ev)


class MoreTile(QWidget):
    """The "+7" standing in for the thumbnails a strip had no room for.

    A strip that simply laid out more tiles than it had width for did not look
    like "there are more": Qt cut the overflowing one down the middle and it
    read as a rendering fault. This takes the last slot instead and says the
    number out loud, and clicking it goes where the row goes.
    """

    def __init__(self, count, on_click, parent=None):
        super().__init__(parent)
        self._count = count
        self._on_click = on_click
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def set_tile(self, w, h):
        self.setFixedSize(int(w), int(h))

    def set_count(self, n):
        if n != self._count:
            self._count = n
            self.update()

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, QColor(style.PAL["surface2"]))
        f = QFont()
        f.setPointSizeF(12.5 if self.height() > 70 else 10.5)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(style.PAL["text"] if self._hover else style.PAL["dim"]))
        p.drawText(r, Qt.AlignCenter, f"+{self._count}")
        if self._hover:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 150), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)
        p.end()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._on_click:
            self._on_click()
        super().mouseReleaseEvent(ev)


class ThumbStrip(QWidget):
    """A row of thumbnails that sizes its tiles to what there is to show.

    Fixed 158x88 stamps left a card with two photos looking 90% empty, because
    the card is as wide as the window whatever it holds. The tiles now grow to
    fill the row, up to a height that keeps a single photo from becoming a
    billboard.

    And it never lays out more than it has room for. It used to: the per-tile
    width was clamped up to MIN_W without the COUNT coming down, so the row was
    placed wider than the widget and Qt cut the last tile in half. Memories asks
    for nine and eight fit, so there was always exactly one sliced thumbnail on
    the page.
    """

    GAP = 8
    MIN_W = 132
    RATIO = 16 / 9

    def __init__(self, max_h=150, parent=None):
        super().__init__(parent)
        self._tiles = []
        self._max_h = max_h        # a dense list stays compact; a highlight row
        self._h = 88               # can afford to be tall
        self._more = None          # the "+N" in the last slot, built on demand
        self._on_more = None       # where it goes: wherever the row goes

    def add(self, main, cache, item, on_click):
        self._tiles.append(ThumbStripLabel(main, cache, item, on_click, parent=self))
        if self._on_more is None:
            self._on_more = on_click
        self._relayout()

    def clear(self):
        for t in self._tiles:
            t.setParent(None)
            t.deleteLater()
        self._tiles = []
        if self._more is not None:
            self._more.setParent(None)
            self._more.deleteLater()
            self._more = None
        self._on_more = None

    def count(self):
        return len(self._tiles)

    def _relayout(self):
        n = len(self._tiles)
        if not n:
            self._h = 0
            self.setFixedHeight(0)
            if self._more is not None:
                self._more.hide()
            return
        avail = max(self.MIN_W, self.width() or self.MIN_W * n)
        # How many slots there are at the smallest a tile is allowed to be. Work
        # this out FIRST: clamping the width without clamping the count is what
        # made the row overflow its own widget.
        slots = max(1, int((avail + self.GAP) // (self.MIN_W + self.GAP)))
        show = n if n <= slots else max(1, slots - 1)   # the last slot says "+N"
        hidden = n - show
        cells = show + (1 if hidden else 0)
        fill = (avail - self.GAP * (cells - 1)) / cells
        # enough photos and the row fills exactly; a lone one grows only to the
        # row height, instead of becoming a billboard
        w = max(self.MIN_W, min(fill, self._max_h * self.RATIO))
        h = round(w / self.RATIO)
        x = 0
        for i, t in enumerate(self._tiles):
            if i >= show:
                t.hide()
                continue
            t.set_tile(round(w), h)
            t.move(round(x), 0)
            t.show()
            x += w + self.GAP
        if hidden:
            if self._more is None:
                self._more = MoreTile(hidden, self._on_more, self)
            self._more.set_count(hidden)
            self._more.set_tile(round(w), h)
            self._more.move(round(x), 0)
            self._more.show()
        elif self._more is not None:
            self._more.hide()
        self._h = h
        self.setFixedHeight(h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def sizeHint(self):
        return QSize(self.MIN_W, self._h)


class MemoriesPage(QWidget):
    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self.scroll, self.holder, self.vbox = widgets.scroll_body(self)
        self.head = widgets.PageHead(self, "Memories")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        btn_rand = widgets.ghost_btn("Random day", "shuffle")
        btn_rand.clicked.connect(self._random_day)
        self.head.add(btn_rand)
        self.head.attach(self.scroll, reserve_in=self.vbox)

    @staticmethod
    def _empty_state():
        # built per refresh: refresh() deleteLater()s everything in the layout,
        # so a shared instance would be a dangling C++ object the second time
        return widgets.EmptyState(
            "clock", "No memories for today",
            "Photos taken on this exact day in past years will show up here. "
            "Meanwhile, try the Random day button!")

    def refresh(self):
        while self.vbox.count():
            it = self.vbox.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        today = date.today()
        mmdd = f"{today.month:02d}-{today.day:02d}"
        self.lab_sub.setText(f"On this day · {fmt.MONTHS[today.month - 1]} "
                             f"{today.day}, {today.year}")
        rows = self.main.db.memories(mmdd, today.year)
        if not rows:
            self.vbox.addWidget(self._empty_state())
            self.vbox.addStretch(1)
            return
        for r in rows:
            year = int(r["y"])
            day = f"{r['y']}-{mmdd}"
            card = widgets.Card()
            top = QHBoxLayout()
            lab = QLabel(f"{fmt.years_ago_label(today.year - year)} · "
                         f"{fmt.MONTHS[today.month - 1]} {today.day}, {year}")
            lab.setStyleSheet("font-size:14px; font-weight:600;")
            cnt = QLabel(f"{r['cnt']} {fmt.plural(r['cnt'], 'photo')}")
            cnt.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
            btn = QPushButton("Open all")
            btn.setObjectName("LinkBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, d=day: self.main.push_day(d))
            top.addWidget(lab)
            top.addWidget(cnt)
            top.addStretch(1)
            top.addWidget(btn)
            card.vbox.addLayout(top)
            strip = ThumbStrip(max_h=240)
            f = PhotoFilter(day=day, sort_desc=False)
            photos = self.main.db.query_photos(f)[:9]
            for prow in photos:
                mini = MiniItem(prow["id"], prow["path"], prow["mtime"],
                                prow["filesize"], 1)
                strip.add(self.main, self.cache, mini,
                          lambda d=day: self.main.push_day(d))
            card.vbox.addWidget(strip)
            self.vbox.addWidget(card)
        self.vbox.addStretch(1)

    def _random_day(self):
        r = self.main.db.random_rich_day()
        if r:
            self.main.push_day(r["day"])
        else:
            self.main.toast("Not enough photos for that yet.", "info")


# ---------------------------------------------------------------- stats

class StatsPage(QWidget):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.scroll, holder, v = widgets.scroll_body(self)
        self.head = widgets.PageHead(self, "Statistics")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.cb_year = widgets.ComboBox()
        self.cb_year.setObjectName("OnGlass")
        self.cb_year.setToolTip("Narrow every chart on this page to one year")
        self.cb_year.currentIndexChanged.connect(self._year_changed)
        self.head.add(self.cb_year, drop=2)
        self.btn_year = widgets.ghost_btn("Year in review", "award", primary=True)
        self.btn_year.clicked.connect(self._year_review)
        self.head.add(self.btn_year, drop=1)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.c_total = widgets.StatCard("image")
        self.c_size = widgets.StatCard("film")
        self.c_worlds = widgets.StatCard("globe")
        self.c_people = widgets.StatCard("users")
        self.c_day = widgets.StatCard("calendar")
        for c in (self.c_total, self.c_size, self.c_worlds, self.c_people, self.c_day):
            cards.addWidget(c)
        v.addLayout(cards)
        self.card_months = widgets.Card("PHOTOS PER MONTH")
        self.chart_months = charts.BarChart(self.main.cfg)
        self.card_months.vbox.addWidget(self.chart_months)
        v.addWidget(self.card_months)
        row = QHBoxLayout()
        row.setSpacing(12)
        card_w = widgets.Card("TOP WORLDS")
        self.chart_worlds = charts.HBarChart(self.main.cfg)
        card_w.vbox.addWidget(self.chart_worlds)
        card_p = widgets.Card("TOP PEOPLE")
        self.chart_people = charts.HBarChart(self.main.cfg)
        card_p.vbox.addWidget(self.chart_people)
        row.addWidget(card_w, 1)
        row.addWidget(card_p, 1)
        v.addLayout(row)
        card_h = widgets.Card("TIME OF DAY — when the camera comes out")
        self.chart_hours = charts.HourChart(self.main.cfg)
        card_h.vbox.addWidget(self.chart_hours)
        v.addWidget(card_h)
        card_av = widgets.Card("MOST WORN AVATARS")
        self.chart_avatars = charts.HBarChart(self.main.cfg)
        card_av.vbox.addWidget(self.chart_avatars)
        v.addWidget(card_av)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        card_inst = widgets.Card("INSTANCE TYPES")
        self.chart_instances = charts.HBarChart(self.main.cfg)
        card_inst.vbox.addWidget(self.chart_instances)
        card_reg = widgets.Card("REGIONS")
        self.chart_regions = charts.HBarChart(self.main.cfg)
        card_reg.vbox.addWidget(self.chart_regions)
        row2.addWidget(card_inst, 1)
        row2.addWidget(card_reg, 1)
        v.addLayout(row2)
        card_fc = widgets.Card("STORAGE")
        self.lab_forecast = QLabel("")
        self.lab_forecast.setWordWrap(True)
        self.lab_forecast.setStyleSheet("font-size:13px; color:%s;" % style.PAL["dim"])
        card_fc.vbox.addWidget(self.lab_forecast)
        v.addWidget(card_fc)
        v.addStretch(1)
        self.head.attach(self.scroll, reserve_in=v)

    def _year_changed(self, _ix):
        self.refresh()

    def selected_year(self):
        """'' for the whole library, else the four-digit year as a string."""
        return self.cb_year.currentData() or ""

    def refresh(self):
        self._fill_years()
        year = self.selected_year()
        s = self.main.db.stats(sorted(self.main.cfg.self_names), year)
        self.c_total.set(fmt.count_label(s["total"]), "photos total")
        self.c_size.set(fmt.human_size(s["bytes"]), "disk space")
        self.c_worlds.set(fmt.count_label(s["worlds"]), "known worlds")
        self.c_people.set(fmt.count_label(s["people"]), "people with you")
        if s["busiest"]:
            d = s["busiest"]["day"]
            self.c_day.set(f'{s["busiest"]["c"]} photos', f"busiest day · {d}")
        else:
            self.c_day.set("–", "busiest day")
        # Every month there is, whichever level you are on. The January of each
        # year carries the year instead of a month name, so a run of four years
        # of bars still tells you where you are.
        self.card_months.set_title("PHOTOS PER MONTH")
        bars = []
        for m in s["months"]:
            try:
                mon = int(m["m"][5:7])
            except ValueError:
                bars.append((m["m"], m["c"], False))
                continue
            jan = mon == 1
            bars.append((m["m"][:4] if jan else fmt.MONTHS_SHORT[mon - 1],
                         m["c"], bool(jan)))
        if bars and not bars[0][2]:
            # the run does not start in January, so say which year it starts in
            bars[0] = (fmt.month_label(s["months"][0]["m"]), bars[0][1], True)
        self.chart_months.set_data(bars)
        self.chart_worlds.set_data([(w["name"] or "?", w["c"]) for w in s["top_worlds"]])
        self.chart_people.set_data([(p["name"], p["c"]) for p in s["top_people"]])
        self.chart_hours.set_data(s["hours"])
        self.chart_avatars.set_data([(av["name"], av["c"]) for av in s["top_avatars"]])
        from . import vrclog
        self.chart_instances.set_data([
            (vrclog.INSTANCE_LABELS.get(r["instance_type"], r["instance_type"]), r["c"])
            for r in self.main.db.instance_summary(year)])
        self.chart_regions.set_data([(REGION_NAMES.get(r["region"], r["region"].upper()),
                                      r["c"]) for r in self.main.db.region_summary(year)])
        self._set_forecast()
        where = year if year else "Across your whole library"
        self.lab_sub.setText(f'{where} · {fmt.count_label(s["sessions"])} sessions')

    def _fill_years(self):
        """Rebuild the year list, keeping whatever the user had chosen."""
        years = self.main.db.years()
        want = self.cb_year.currentData()
        self.cb_year.blockSignals(True)
        self.cb_year.clear()
        self.cb_year.addItem("All time", "")
        for y in years:
            self.cb_year.addItem(str(y), str(y))
        ix = self.cb_year.findData(want)
        self.cb_year.setCurrentIndex(ix if ix >= 0 else 0)
        self.cb_year.blockSignals(False)
        self.cb_year.setEnabled(bool(years))
        # the poster is always about one year, so say which one it will be
        poster = self.poster_year()
        self.btn_year.setText(f"{poster} in review" if poster else "Year in review")
        self.btn_year.setEnabled(bool(years))

    def poster_year(self):
        """The year the poster button will build: the chosen one, else the latest."""
        year = self.selected_year()
        if year:
            return year
        years = self.main.db.years()
        return str(years[0]) if years else ""

    def _set_forecast(self):
        f = self.main.db.storage_forecast()
        bits = []
        # Rows exist only for months that had photos, so averaging the last six
        # ROWS would overstate the pace of someone who skipped months. Divide by
        # the calendar span those rows actually cover.
        recent = f["months"][-6:]
        if len(recent) >= 2:
            def ym(m):
                return int(m[:4]) * 12 + int(m[5:7])
            span = max(1, ym(recent[-1]["m"]) - ym(recent[0]["m"]) + 1)
            per_month = sum(m["b"] for m in recent) / span
            shots = sum(m["c"] for m in recent) / span
            bits.append(f"You are adding about {fmt.human_size(per_month)} and "
                        f"{int(round(shots))} photos a month — roughly "
                        f"{fmt.human_size(per_month * 12)} a year at this pace.")
        if f["png_count"]:
            saved = f["png_bytes"] * 0.68        # measured ratio for these 4K shots
            bits.append(f"{fmt.count_label(f['png_count'])} PNGs take "
                        f"{fmt.human_size(f['png_bytes'])}; converting them to JPG in "
                        f"Cleanup would free roughly {fmt.human_size(saved)}.")
        self.lab_forecast.setText(" ".join(bits) or "Not enough history yet.")

    def _year_review(self):
        # "All time" has no poster of its own, so it builds the latest year --
        # which is what the button says it will do
        year = self.poster_year()
        if year.isdigit():
            self.main.build_year_review(int(year))


# ---------------------------------------------------------------- cleanup

class ConvertWorker(QThread):
    progress = Signal(int, int)
    done = Signal(int, int, list)   # saved_bytes, converted_count, errors

    def __init__(self, db, items, quality, parent=None):
        super().__init__(parent)
        self.db = db
        self.items = items       # list of dicts w/ id, path, filesize
        self.quality = quality

    def run(self):
        saved = 0
        okc = 0
        errors = []
        for i, it in enumerate(self.items):
            try:
                new_path, new_size = imaging.convert_to_jpeg(it["path"], self.quality)
                removed, err = winutil.recycle([it["path"]])
                if len(removed) != 1:
                    # the original is still there — drop the copy and leave it alone
                    try:
                        os.remove(new_path)
                    except OSError:
                        pass
                    raise RuntimeError(err or "original could not be recycled")
                st = os.stat(new_path)
                self.db.update_path(it["id"], new_path, new_size, st.st_mtime)
                saved += max(0, (it["filesize"] or 0) - new_size)
                okc += 1
            except Exception as e:
                errors.append(f"{os.path.basename(it['path'])}: {e}")
            self.progress.emit(i + 1, len(self.items))
        self.done.emit(saved, okc, errors)


class CheckModel(QAbstractListModel):
    """Rows: ('H', text) headers or ('P', dict) checkable photos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == CardRole:
            return self.rows[index.row()]
        return None

    def flags(self, index):
        kind, _ = self.rows[index.row()]
        if kind == "S":
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled if kind == "H" else (Qt.ItemIsEnabled | Qt.ItemIsSelectable)

    def checked(self):
        return [d for k, d in self.rows if k == "P" and d["checked"]]

    def set_all(self, on, keep_first_of_group=False):
        group_seen = set()
        for i, (k, d) in enumerate(self.rows):
            if k != "P":
                continue
            if keep_first_of_group and on:
                g = d.get("group")
                if g is not None and g not in group_seen:
                    group_seen.add(g)
                    d["checked"] = False
                    continue
            d["checked"] = on
        if self.rows:
            self.dataChanged.emit(self.index(0), self.index(len(self.rows) - 1))


class CheckDelegate(QStyledItemDelegate):
    W, H = 158, 96

    def __init__(self, view, cache, cfg, parent=None):
        super().__init__(parent)
        self.view = view
        self.cache = cache
        self.cfg = cfg
        self._f = QFont()
        self._f.setPointSizeF(8)
        self._f.setWeight(QFont.DemiBold)
        self._fh = QFont()
        self._fh.setPointSizeF(9.5)
        self._fh.setWeight(QFont.DemiBold)

    def sizeHint(self, option, index):
        kind, d = index.data(CardRole)
        if kind == "S":                 # room for the floating header
            return QSize(max(80, self.view.viewport().width() - 24), max(1, int(d)))
        if kind == "H":
            return QSize(max(80, self.view.viewport().width() - 24), 34)
        return QSize(self.W, self.H)

    def paint(self, p, option, index):
        kind, d = index.data(CardRole)
        if kind == "S":
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if kind == "H":
            p.setFont(self._fh)
            p.setPen(QColor(style.PAL["dim"]))
            p.drawText(QRectF(option.rect).adjusted(4, 0, -4, -4),
                       Qt.AlignLeft | Qt.AlignBottom, d)
            p.restore()
            return
        r = QRectF(option.rect)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        mini = d["mini"]
        pm = self.cache.get(mini)
        if pm and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            scale = max(r.width() / pw, r.height() / ph)
            dw, dh = pw * scale, ph * scale
            p.drawPixmap(QRectF(r.x() + (r.width() - dw) / 2, r.y() + (r.height() - dh) / 2,
                                dw, dh), pm, QRectF(0, 0, pw, ph))
        else:
            p.fillRect(r, QColor(style.PAL["surface2"]))
        g = QLinearGradient(0, r.bottom() - 30, 0, r.bottom())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 150))
        p.fillRect(QRectF(r.x(), r.bottom() - 30, r.width(), 30), g)
        p.setFont(self._f)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QRectF(r.x() + 8, r.bottom() - 22, r.width() - 16, 16),
                   Qt.AlignRight | Qt.AlignVCenter, d.get("label", ""))
        # check circle
        cr = QRectF(r.x() + 8, r.y() + 8, 20, 20)
        if d["checked"]:
            ac = style.accent(self.cfg.get("accent"))
            g2 = QLinearGradient(cr.topLeft(), cr.bottomRight())
            g2.setColorAt(0, QColor(ac["a"]))
            g2.setColorAt(1, QColor(ac["b"]))
            p.setBrush(g2)
            p.setPen(Qt.NoPen)
            p.drawEllipse(cr)
            chk = icons.pixmap("check", "#ffffff", 12, self.view.devicePixelRatioF(), width=3)
            p.drawPixmap(int(cr.x() + 4), int(cr.y() + 4), chk)
        else:
            p.setBrush(QColor(0, 0, 0, 90))
            p.setPen(QPen(QColor(255, 255, 255, 190), 1.6))
            p.drawEllipse(cr)
        if d["checked"]:
            p.setClipping(False)
            ac = style.accent(self.cfg.get("accent"))
            p.setPen(QPen(QColor(ac["a"]), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 9, 9)
        p.restore()

    def editorEvent(self, event, model, option, index):
        kind, d = index.data(CardRole)
        if kind == "P" and event.type() == event.Type.MouseButtonRelease \
                and event.button() == Qt.LeftButton:
            d["checked"] = not d["checked"]
            model.dataChanged.emit(index, index)
            self.view.check_changed.emit()
            return True
        return super().editorEvent(event, model, option, index)


class CheckGridView(QListView):
    check_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setSpacing(7)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(48)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.NoFrame)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.scheduleDelayedItemsLayout()


class CleanupPage(QWidget):
    MODES = [("black", "Black shots"), ("burst", "Bursts"),
             ("dupes", "Duplicates"), ("large", "Huge files"),
             ("deleted", "Recently deleted")]
    DUPE_DISTANCE = 3          # max differing bits of the 64-bit dhash
    DUPE_LUMA_DELTA = 7.0      # …and the frames must be about equally bright

    def __init__(self, main, cache, parent=None):
        super().__init__(parent)
        self.main = main
        self.cache = cache
        self.mode = "black"
        self._convert_worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.head = widgets.PageHead(self, "Cleanup",
                                     "Deletes always go to the Recycle Bin")
        self.lab_title, self.lab_sub = self.head.lab_title, self.head.lab_sub
        self.seg_group = QButtonGroup(self)
        self.seg_group.setExclusive(True)
        for key, label in self.MODES:
            b = QPushButton(label)
            b.setObjectName("PillBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("mode", key)
            b.setMinimumWidth(b.sizeHint().width())   # never squeezed to ellipsis
            self.seg_group.addButton(b)
            # The rarely-used modes give up their place first; the mode you are
            # in never does, so a narrow window cannot strand you.
            # All five can go; `fit` will not drop whichever one is checked, so
            # a narrow window can never strand you in a mode you cannot see.
            self.head.add(b, drop={"deleted": 1, "huge": 2, "dupes": 3,
                                   "burst": 4, "black": 5}.get(key, 6))
            if key == self.mode:
                b.setChecked(True)
        self.seg_group.buttonClicked.connect(self._seg_clicked)

        self.scan_bar = QWidget()
        sb = QHBoxLayout(self.scan_bar)
        sb.setContentsMargins(24, 0, 24, 0)
        sb.setSpacing(10)
        self.scan_label = QLabel("Analyzing…")
        self.scan_label.setStyleSheet("color:%s; font-size:12px;" % style.PAL["dim"])
        self.scan_prog = QProgressBar()
        self.scan_prog.setTextVisible(False)
        self.scan_prog.setFixedHeight(6)
        sb.addWidget(self.scan_label)
        sb.addWidget(self.scan_prog, 1)
        root.addWidget(self.scan_bar)
        self.scan_bar.hide()

        self.model = CheckModel(self)
        self.view = CheckGridView()
        self.view.setModel(self.model)
        self.delegate = CheckDelegate(self.view, cache, self.main.cfg, self)
        self.view.setItemDelegate(self.delegate)
        self.smooth = widgets.SmoothScroll(self.view)
        self.view.check_changed.connect(self._update_bottom)
        cache.ready.connect(lambda _pid: self.view.viewport().update())
        body = QHBoxLayout()
        body.setContentsMargins(24, 0, 8, 0)
        body.addWidget(self.view, 1)
        root.addLayout(body, 1)
        self.head.attach(self.view)
        self.head.viewport_resized.connect(self.view.scheduleDelayedItemsLayout)
        self.empty = widgets.EmptyState("check", "All clean", "", self.view)
        self.empty.hide()

        bottom = QHBoxLayout()
        bottom.setContentsMargins(24, 6, 24, 14)
        bottom.setSpacing(8)
        self.lab_pick = QLabel("0 selected")
        self.lab_pick.setStyleSheet("color:%s;" % style.PAL["dim"])
        bottom.addWidget(self.lab_pick)
        bottom.addStretch(1)
        self.btn_smart = widgets.ghost_btn("Smart select")
        self.btn_smart.setToolTip("Keeps the first shot of every burst")
        self.btn_smart.clicked.connect(self._smart_select)
        self.btn_all = widgets.ghost_btn("All")
        self.btn_all.clicked.connect(lambda: (self.model.set_all(True), self._update_bottom()))
        self.btn_none = widgets.ghost_btn("None")
        self.btn_none.clicked.connect(lambda: (self.model.set_all(False), self._update_bottom()))
        self.btn_convert = widgets.ghost_btn("Convert to JPG", "zap")
        self.btn_convert.clicked.connect(self._convert)
        self.btn_del = widgets.ghost_btn("Recycle selected", "trash", danger=True)
        self.btn_del.clicked.connect(self._recycle_checked)
        self.btn_restore = widgets.ghost_btn("Restore selected", "refresh", primary=True)
        self.btn_restore.clicked.connect(self._restore_checked)
        self.btn_bin = widgets.ghost_btn("Open Recycle Bin", "external")
        self.btn_bin.clicked.connect(lambda: winutil.open_recycle_bin())
        bottom.addWidget(self.btn_smart)
        bottom.addWidget(self.btn_all)
        bottom.addWidget(self.btn_none)
        bottom.addWidget(self.btn_convert)
        bottom.addWidget(self.btn_bin)
        bottom.addWidget(self.btn_restore)
        bottom.addWidget(self.btn_del)
        root.addLayout(bottom)

        self.main.bridge.deep_progress.connect(self._deep_progress)

    # ----- data building -----
    def refresh(self):
        uns = self.main.db.unscanned()
        if uns:
            self.main.svc.sweep(uns)
            self.scan_bar.show()
            self.scan_label.setText(f"Analyzing… ({len(uns)} photos left)")
        else:
            self.scan_bar.hide()
        rows = []
        if self.mode == "black":
            data = self.main.db.black_photos()
            for r in data:
                rows.append(("P", self._mk(r, label=fmt.human_size(r["filesize"]))))
            if rows:
                rows.insert(0, ("H", f"Nearly all-black shots · {len(data)} — "
                                     "usually misfires and loading screens"))
        elif self.mode == "burst":
            data = self.main.db.photos_time_ordered()
            groups = []
            cur = []
            prev_dt = None
            for r in data:
                dt = fmt.parse_iso(r["taken_at"])
                if prev_dt and dt and (dt - prev_dt).total_seconds() <= 2.5:
                    cur.append(r)
                else:
                    if len(cur) >= 3:
                        groups.append(cur)
                    cur = [r]
                prev_dt = dt
            if len(cur) >= 3:
                groups.append(cur)
            for gi, g in enumerate(groups):
                first = g[0]
                total = sum(x["filesize"] or 0 for x in g)
                rows.append(("H", f"Burst · {len(g)} shots · {fmt.dt_label(first['taken_at'])}"
                                  f" · {fmt.human_size(total)}"))
                for r in g:
                    rows.append(("P", self._mk(r, group=gi,
                                               label=fmt.time_label(r["taken_at"]))))
        elif self.mode == "dupes":
            groups = self._duplicate_groups()
            for gi, g in enumerate(groups):
                waste = sum(x["filesize"] or 0 for x in g[1:])
                rows.append(("H", f"{len(g)} near-identical shots · "
                                  f"{fmt.human_size(waste)} recoverable · "
                                  f"first seen {fmt.dt_label(g[0]['taken_at'])}"))
                for r in g:
                    rows.append(("P", self._mk(r, group=gi,
                                               label=fmt.date_short(r["taken_at"]))))
        elif self.mode == "large":
            data = self.main.db.largest(200)
            data = [r for r in data if (r["filesize"] or 0) >= 4 * 1024 * 1024]
            for r in data:
                rows.append(("P", self._mk(r, label=fmt.human_size(r["filesize"]))))
            if rows:
                png_n = sum(1 for k, d in rows if k == "P"
                            and d["path"].lower().endswith(".png"))
                rows.insert(0, ("H", f"Largest files · converting to JPG saves roughly "
                                     f"60–75% ({png_n} PNGs listed)"))
        elif self.mode == "deleted":
            data = self.main.db.recently_deleted()
            for r in data:
                when = fmt.date_short(r["deleted_at"]) if r["deleted_at"] else ""
                rows.append(("P", self._mk(r, label=when)))
            if rows:
                rows.insert(0, ("H", "Photos this app moved to the Recycle Bin · "
                                     "restore puts them back where they were"))
        grouped = self.mode in ("burst", "dupes")
        deleted = self.mode == "deleted"
        # a blank first row, so the grid scrolls under the floating header
        self.model.set_rows([("S", self.head.reserved())] + rows)
        self.btn_convert.setVisible(self.mode == "large")
        self.btn_restore.setVisible(deleted)
        self.btn_bin.setVisible(deleted)
        self.btn_del.setVisible(not deleted)       # they are already deleted
        self.btn_smart.setVisible(grouped)
        self.btn_smart.setToolTip("Keeps the first shot of every group"
                                  if self.mode == "burst" else
                                  "Keeps the best copy of every group")
        self.btn_all.setVisible(not grouped)
        n = sum(1 for k, _d in rows if k == "P")
        self.empty.setVisible(n == 0)
        self.empty.resize(self.view.size())
        subs = {"black": "black shot", "burst": "burst shot", "dupes": "duplicate",
                "large": "huge file", "deleted": "deleted photo"}
        # the header row also carries five mode pills, so the subtitle stays short
        tail = "" if deleted else " · deletes always go to the Recycle Bin"
        self.lab_sub.setText(f"{n} {fmt.plural(n, subs.get(self.mode, 'item'))}{tail}")
        self._update_bottom()

    def _duplicate_groups(self):
        """Near-identical photos anywhere in the library, grouped around a seed.

        Candidate pairs come from a pigeonhole index: a 64-bit hash split into
        four 16-bit chunks means anything within 3 differing bits must match on
        at least one chunk, so we only compare inside those buckets.

        Grouping is deliberately seed-based rather than union-find: transitive
        merging chains A~B~C together even when A and C are plainly different
        photos, which would then offer genuinely distinct shots for deletion.
        Every member here is within DUPE_DISTANCE of the group's own seed.

        dhash alone is composition-only, so a row of avatar shots on flat
        backdrops looks identical to it. Brightness is a cheap second opinion
        that we already store, and it separates those.
        """
        rows = self.main.db.hashed_photos()
        items = []
        for r in rows:
            try:
                h = int(r["dhash"], 16)
            except (TypeError, ValueError):
                continue
            # a flat frame (all black/white) hashes to 0 and would otherwise pile
            # every such photo into one bucket that the size guard then skips
            if h in (0, (1 << 64) - 1):
                continue
            items.append((h, r))

        buckets = {}
        for idx, (h, _r) in enumerate(items):
            for c in range(4):
                buckets.setdefault((c, (h >> (16 * c)) & 0xFFFF), []).append(idx)

        neighbours = {}
        for members in buckets.values():
            if len(members) < 2 or len(members) > 400:   # skip degenerate buckets
                continue
            for a_i in range(len(members)):
                for b_i in range(a_i + 1, len(members)):
                    i, j = members[a_i], members[b_i]
                    if (items[i][0] ^ items[j][0]).bit_count() > self.DUPE_DISTANCE:
                        continue
                    la, lb = items[i][1]["luma"], items[j][1]["luma"]
                    if la is not None and lb is not None \
                            and abs(la - lb) > self.DUPE_LUMA_DELTA:
                        continue
                    neighbours.setdefault(i, set()).add(j)
                    neighbours.setdefault(j, set()).add(i)

        taken = set()
        groups = []
        # biggest neighbourhoods first so the strongest cluster claims its members
        for seed in sorted(neighbours, key=lambda i: len(neighbours[i]), reverse=True):
            if seed in taken:
                continue
            members = [seed] + [j for j in neighbours[seed] if j not in taken]
            if len(members) < 2:
                continue
            taken.update(members)
            groups.append([items[i][1] for i in members])

        # inside a group the keeper comes first: favorites, then biggest file
        for g in groups:
            g.sort(key=lambda r: (0 if r["favorite"] else 1, -(r["filesize"] or 0),
                                  r["taken_at"] or ""))
        groups.sort(key=lambda g: sum(x["filesize"] or 0 for x in g[1:]), reverse=True)
        return groups

    def _mk(self, r, group=None, label=""):
        return {"id": r["id"], "path": r["path"], "filesize": r["filesize"],
                "mini": MiniItem(r["id"], r["path"], r["mtime"], r["filesize"], 1),
                "checked": False, "group": group, "label": label}

    # ----- interactions -----
    def _seg_clicked(self, btn):
        self.mode = btn.property("mode")
        self.refresh()

    def _smart_select(self):
        self.model.set_all(True, keep_first_of_group=True)
        self._update_bottom()

    def _update_bottom(self):
        ch = self.model.checked()
        total = sum(d["filesize"] or 0 for d in ch)
        self.lab_pick.setText(f"{len(ch)} selected · {fmt.human_size(total)}")
        self.btn_del.setEnabled(bool(ch))
        self.btn_convert.setEnabled(bool(ch))
        self.btn_restore.setEnabled(bool(ch))
        self.view.viewport().update()

    def _restore_checked(self):
        ch = self.model.checked()
        if not ch:
            return
        restored, missing = winutil.restore_from_recycle_bin([d["path"] for d in ch])
        back = {os.path.normcase(os.path.abspath(p)) for p in restored}
        done = [d for d in ch if os.path.normcase(os.path.abspath(d["path"])) in back]
        if done:
            self.main.db.restore_photos([d["id"] for d in done])
            self.main.after_photos_changed()
        self.refresh()
        if not done:
            self.main.toast("Nothing came back — the Recycle Bin no longer has "
                            "those files, or Windows would not restore them.", "err")
        elif missing:
            self.main.toast(f"Restored {len(done)}; {len(missing)} were no longer "
                            "in the Recycle Bin.", "err")
        else:
            self.main.toast(f"Restored {len(done)} "
                            f"{fmt.plural(len(done), 'photo')}.", "ok")

    def _recycle_checked(self):
        ch = self.model.checked()
        if not ch:
            return
        total = sum(d["filesize"] or 0 for d in ch)
        if QMessageBox.question(
                self, "Recycle",
                f"Move {len(ch)} photos to the Recycle Bin ({fmt.human_size(total)})?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        removed, err = winutil.recycle([d["path"] for d in ch])
        gone = {os.path.normcase(os.path.abspath(p)) for p in removed}
        done = [d for d in ch if os.path.normcase(os.path.abspath(d["path"])) in gone]
        self.main.db.mark_recycled([d["id"] for d in done],
                                   datetime.now().isoformat(timespec="seconds"))
        freed = sum(d["filesize"] or 0 for d in done)
        if err or len(done) < len(ch):
            self.main.toast(f"{len(done)} of {len(ch)} recycled"
                            + (f" — {err}" if err else "."), "err")
        else:
            self.main.toast(f"{len(done)} photos recycled · "
                            f"{fmt.human_size(freed)} freed", "ok")
        self.main.after_photos_changed()
        self.refresh()

    def _convert(self):
        ch = [d for d in self.model.checked() if d["path"].lower().endswith(".png")]
        if not ch:
            self.main.toast("No PNGs among the selected photos.", "info")
            return
        if self._convert_worker and self._convert_worker.isRunning():
            return
        total = sum(d["filesize"] or 0 for d in ch)
        q = int(self.main.cfg.get("jpeg_quality") or 92)
        if QMessageBox.question(
                self, "Convert to JPG",
                f"Convert {len(ch)} PNGs ({fmt.human_size(total)}) to JPG (quality {q})?\n"
                "Originals go to the Recycle Bin; favorites and albums are kept.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.scan_bar.show()
        self.scan_label.setText("Converting…")
        self.scan_prog.setRange(0, len(ch))
        self.scan_prog.setValue(0)
        self._convert_worker = ConvertWorker(self.main.db, ch, q, self)
        self._convert_worker.progress.connect(
            lambda a, b: (self.scan_prog.setValue(a),
                          self.scan_label.setText(f"Converting… {a}/{b}")))
        self._convert_worker.done.connect(self._convert_done)
        self._convert_worker.start()

    def _convert_done(self, saved, okc, errors):
        self.scan_bar.hide()
        for d in self.model.checked():
            self.cache.invalidate(d["id"])
        msg = f"{okc} photos converted · {fmt.human_size(saved)} freed"
        if errors:
            msg += f" · {len(errors)} {fmt.plural(len(errors), 'error')}"
        self.main.toast(msg, "ok" if not errors else "err")
        self.main.after_photos_changed()
        self.refresh()

    def _deep_progress(self, done, total):
        if total and done < total:
            self.scan_prog.setRange(0, total)
            self.scan_prog.setValue(done)
            if not (self._convert_worker and self._convert_worker.isRunning()):
                self.scan_label.setText(f"Analyzing… {done}/{total}")
        elif self.isVisible() and total and done >= total:
            self.scan_bar.hide()
            self.refresh()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.empty.isVisible():
            self.empty.resize(self.view.size())


# ---------------------------------------------------------------- settings

class SettingsPage(QWidget):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        widgets.SmoothScroll(scroll)
        self.scroll = scroll
        holder = QWidget()
        # A settings form stretched to the width of a maximised window puts the
        # label at one edge of the screen and its control at the other. Cap it
        # and keep it against the left margin, where the reading starts.
        outer = QHBoxLayout(holder)
        outer.setContentsMargins(24, 0, 16, 20)
        self.head = widgets.PageHead(self, "Settings")
        self.lab_sub = self.head.lab_sub
        column = QWidget()
        column.setMaximumWidth(920)
        outer.addWidget(column, 1, Qt.AlignTop)   # grows to its maximum, then stops
        outer.addStretch(0)
        v = QVBoxLayout(column)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # folders
        self.card_folders = widgets.Card("PHOTO FOLDERS")
        self.folders_box = QVBoxLayout()
        self.folders_box.setSpacing(6)
        self.card_folders.vbox.addLayout(self.folders_box)
        btn_add = widgets.ghost_btn("Add folder", "folder-plus")
        btn_add.clicked.connect(self._add_folder)
        self.card_folders.vbox.addWidget(btn_add, 0, Qt.AlignLeft)
        v.addWidget(self.card_folders)

        # appearance
        card_look = widgets.Card("APPEARANCE")
        row = QHBoxLayout()
        row.setSpacing(10)
        lab = QLabel("Accent color:")
        row.addWidget(lab)
        self._dots = []
        for key, ac in style.ACCENTS.items():
            dot = widgets.GradientDot(ac["a"], ac["b"],
                                      selected=(key == self.main.cfg.get("accent")),
                                      on_click=lambda k=key: self._set_accent(k))
            dot.setToolTip(ac["label"])
            self._dots.append((key, dot))
            row.addWidget(dot)
        row.addStretch(1)
        card_look.vbox.addLayout(row)

        trow = QHBoxLayout()
        trow.setSpacing(10)
        trow.addWidget(QLabel("Theme:"))
        self._themes = []
        for key, pal in style.PALETTES.items():
            a, b = pal["swatch"]
            dot = widgets.GradientDot(
                a, b, selected=(key == self.main.cfg.get("palette")),
                on_click=lambda k=key: self._set_palette(k))
            dot.setToolTip(pal["label"])
            self._themes.append((key, dot))
            trow.addWidget(dot)
        trow.addStretch(1)
        card_look.vbox.addLayout(trow)
        v.addWidget(card_look)

        # sharing
        card_share = widgets.Card("DISCORD SHARING")
        self.ed_hook = QLineEdit(self.main.cfg.get("webhook_url") or "")
        self.ed_hook.setPlaceholderText("https://discord.com/api/webhooks/…")
        self.ed_hook.setEchoMode(QLineEdit.Password)
        self.ed_hook.editingFinished.connect(
            lambda: self.main.cfg.set("webhook_url", self.ed_hook.text().strip()))
        hrow = QHBoxLayout()
        hrow.addWidget(self.ed_hook, 1)
        btn_eye = widgets.ghost_btn("Show")
        btn_eye.clicked.connect(self._toggle_hook_echo)
        hrow.addWidget(btn_eye)
        card_share.vbox.addLayout(hrow)
        hint = QLabel("Server ▸ channel settings ▸ Integrations ▸ Webhooks — paste the URL "
                      "you get there. Photos can then be sent to the channel with one click.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_share.vbox.addWidget(hint)
        self.chk_caption = QCheckBox("Burn a caption band into shared photos "
                                     "(world, date, who was there)")
        self.chk_caption.setChecked(bool(self.main.cfg.get("share_captioned")))
        self.chk_caption.toggled.connect(
            lambda on: self.main.cfg.set("share_captioned", bool(on)))
        card_share.vbox.addWidget(self.chk_caption)
        v.addWidget(card_share)

        # local API
        card_api = widgets.Card("LOCAL API")
        arow = QHBoxLayout()
        arow.setSpacing(10)
        self.chk_api = QCheckBox("Enabled")
        self.chk_api.setChecked(bool(self.main.cfg.get("api_enabled")))
        self.chk_api.toggled.connect(self._toggle_api)
        arow.addWidget(self.chk_api)
        arow.addWidget(QLabel("Port:"))
        self.sp_port = widgets.SpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(int(self.main.cfg.get("api_port") or 8770))
        self.sp_port.editingFinished.connect(self._change_port)
        arow.addWidget(self.sp_port)
        arow.addStretch(1)
        card_api.vbox.addLayout(arow)
        self.ed_api_url = QLineEdit("")
        self.ed_api_url.setReadOnly(True)
        urow = QHBoxLayout()
        urow.addWidget(self.ed_api_url, 1)
        btn_copy_url = widgets.ghost_btn("Copy", "copy")
        btn_copy_url.clicked.connect(self._copy_api_url)
        btn_new_tok = widgets.ghost_btn("New token", "refresh")
        btn_new_tok.clicked.connect(self._new_token)
        urow.addWidget(btn_copy_url)
        urow.addWidget(btn_new_tok)
        card_api.vbox.addLayout(urow)
        hint_api = QLabel(
            "Loopback only (127.0.0.1) and token-gated. Paste this URL into a Hexpad "
            "key: action “HTTP request (webhook)”, method POST, body {} — one tap then "
            "sends your newest screenshot to Discord. Swap /discord for /copy, /open "
            "or /index.")
        hint_api.setWordWrap(True)
        hint_api.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_api.vbox.addWidget(hint_api)
        v.addWidget(card_api)

        # backup
        card_bk = widgets.Card("BACKUP")
        brow = QHBoxLayout()
        brow.setSpacing(8)
        self.ed_backup = QLineEdit(self.main.cfg.get("backup_dir") or "")
        self.ed_backup.setPlaceholderText("Backup folder — an external drive, a NAS, "
                                          "a synced folder…")
        self.ed_backup.editingFinished.connect(
            lambda: self.main.cfg.set("backup_dir", self.ed_backup.text().strip()))
        btn_bk_pick = widgets.ghost_btn("Browse", "folder")
        btn_bk_pick.clicked.connect(self._pick_backup_dir)
        self.btn_backup = widgets.ghost_btn("Back up now", "copy", primary=True)
        self.btn_backup.clicked.connect(self._run_backup)
        brow.addWidget(self.ed_backup, 1)
        brow.addWidget(btn_bk_pick)
        brow.addWidget(self.btn_backup)
        card_bk.vbox.addLayout(brow)
        self.chk_bk_hash = QCheckBox("Verify every copy with a checksum (slower, safest)")
        self.chk_bk_hash.setChecked(bool(self.main.cfg.get("backup_verify_hash")))
        self.chk_bk_hash.toggled.connect(
            lambda on: self.main.cfg.set("backup_verify_hash", bool(on)))
        card_bk.vbox.addWidget(self.chk_bk_hash)
        self.lab_backup = QLabel("")
        self.lab_backup.setWordWrap(True)
        self.lab_backup.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_bk.vbox.addWidget(self.lab_backup)
        v.addWidget(card_bk)

        # headset import
        card_q = widgets.Card("IMPORT FROM A HEADSET")
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        self.ed_adb = QLineEdit(self.main.cfg.get("adb_path") or "")
        self.ed_adb.setPlaceholderText("Path to adb.exe (from Android platform-tools "
                                       "or SideQuest)")
        self.ed_adb.editingFinished.connect(
            lambda: self.main.cfg.set("adb_path", self.ed_adb.text().strip()))
        btn_adb = widgets.ghost_btn("Browse", "folder")
        btn_adb.clicked.connect(self._pick_adb)
        self.btn_quest = widgets.ghost_btn("Import photos", "refresh")
        self.btn_quest.clicked.connect(self._run_quest_import)
        qrow.addWidget(self.ed_adb, 1)
        qrow.addWidget(btn_adb)
        qrow.addWidget(self.btn_quest)
        card_q.vbox.addLayout(qrow)
        self.lab_quest = QLabel("")
        self.lab_quest.setWordWrap(True)
        self.lab_quest.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_q.vbox.addWidget(self.lab_quest)
        v.addWidget(card_q)

        # in-world frame
        card_frame = widgets.Card("IN-WORLD FRAME")
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.ed_frame = QLineEdit(self.main.cfg.get("frame_dir") or "")
        self.ed_frame.setPlaceholderText("Folder that gets frame.jpg (a synced folder, "
                                         "a git working copy, a web root…)")
        self.ed_frame.editingFinished.connect(
            lambda: self.main.cfg.set("frame_dir", self.ed_frame.text().strip()))
        btn_pick = widgets.ghost_btn("Browse", "folder")
        btn_pick.clicked.connect(self._pick_frame_dir)
        frow.addWidget(self.ed_frame, 1)
        frow.addWidget(btn_pick)
        card_frame.vbox.addLayout(frow)
        self.ed_frame_cmd = QLineEdit(self.main.cfg.get("frame_publish_cmd") or "")
        self.ed_frame_cmd.setPlaceholderText('Publish command, e.g. git add -A && git '
                                             'commit -m frame && git push  (optional)')
        self.ed_frame_cmd.editingFinished.connect(
            lambda: self.main.cfg.set("frame_publish_cmd", self.ed_frame_cmd.text().strip()))
        card_frame.vbox.addWidget(self.ed_frame_cmd)
        self.chk_frame_cap = QCheckBox("Caption the frame image too")
        self.chk_frame_cap.setChecked(bool(self.main.cfg.get("frame_captioned")))
        self.chk_frame_cap.toggled.connect(
            lambda on: self.main.cfg.set("frame_captioned", bool(on)))
        card_frame.vbox.addWidget(self.chk_frame_cap)
        hint_frame = QLabel(
            f"Right-click a photo ▸ “Send to world frame”. {paths.APP_NAME} only writes the "
            "file and runs your command — it never uploads anything itself. The Udon "
            "script and setup steps are in the app's world\\ folder. Anything you "
            "publish is visible to everyone who visits the world.")
        hint_frame.setWordWrap(True)
        hint_frame.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_frame.vbox.addWidget(hint_frame)
        v.addWidget(card_frame)

        # behavior
        card_beh = widgets.Card("BEHAVIOR")
        grid = QHBoxLayout()
        grid.setSpacing(18)

        def spin_row(label, value, lo, hi, on_change, suffix=""):
            box = QHBoxLayout()
            box.setSpacing(8)
            box.addWidget(QLabel(label))
            sp = widgets.SpinBox()
            sp.setRange(lo, hi)
            sp.setValue(value)
            if suffix:
                sp.setSuffix(suffix)
            sp.valueChanged.connect(on_change)
            box.addWidget(sp)
            return box, sp

        b1, self.sp_slide = spin_row("Slideshow:", int(self.main.cfg.get("slideshow_secs") or 5),
                                     2, 60, lambda val: self.main.cfg.set("slideshow_secs", val),
                                     " s")
        b2, self.sp_q = spin_row("JPG quality:", int(self.main.cfg.get("jpeg_quality") or 92),
                                 60, 100, lambda val: self.main.cfg.set("jpeg_quality", val))
        grid.addLayout(b1)
        grid.addLayout(b2)
        grid.addStretch(1)
        card_beh.vbox.addLayout(grid)
        self.ed_self = QLineEdit(", ".join(sorted(self.main.cfg.self_names)))
        self.ed_self.setPlaceholderText("Your VRChat display names (comma-separated)")
        self.ed_self.editingFinished.connect(self._save_self_names)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Your names:"))
        srow.addWidget(self.ed_self, 1)
        card_beh.vbox.addLayout(srow)
        hint2 = QLabel(f"Your own names are hidden from the People page — {paths.APP_NAME} "
                       "learns them automatically from the VRChat logs.")
        hint2.setWordWrap(True)
        hint2.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_beh.vbox.addWidget(hint2)

        crow = QHBoxLayout()
        crow.setSpacing(8)
        crow.addWidget(QLabel("Copy to clipboard as:"))
        self.cb_copy = widgets.ComboBox()
        self.cb_copy.addItems(["Downscaled (fast to paste)", "Full resolution"])
        self.cb_copy.setCurrentIndex(
            0 if (self.main.cfg.get("copy_mode") or "jpeg") == "jpeg" else 1)
        self.cb_copy.currentIndexChanged.connect(
            lambda i: self.main.cfg.set("copy_mode", "jpeg" if i == 0 else "original"))
        crow.addWidget(self.cb_copy)
        crow.addStretch(1)
        card_beh.vbox.addLayout(crow)
        v.addWidget(card_beh)

        # startup / tray
        card_run = widgets.Card("STARTUP")
        self.chk_tray = QCheckBox(f"Closing the window keeps {paths.APP_NAME} in the tray")
        self.chk_tray.setChecked(bool(self.main.cfg.get("close_to_tray")))
        self.chk_tray.toggled.connect(
            lambda on: self.main.cfg.set("close_to_tray", bool(on)))
        card_run.vbox.addWidget(self.chk_tray)
        self.chk_autostart = QCheckBox("Start with Windows (hidden, in the tray)")
        self.chk_autostart.setChecked(bool(winutil.get_autostart(paths.APP_NAME)))
        self.chk_autostart.toggled.connect(self._toggle_autostart)
        card_run.vbox.addWidget(self.chk_autostart)
        self.chk_startmin = QCheckBox("Start minimised to the tray when launched manually")
        self.chk_startmin.setChecked(bool(self.main.cfg.get("start_minimized")))
        self.chk_startmin.toggled.connect(
            lambda on: self.main.cfg.set("start_minimized", bool(on)))
        card_run.vbox.addWidget(self.chk_startmin)
        hint_run = QLabel(
            f"VRChat only keeps the last few log files. While {paths.APP_NAME} runs it copies "
            "each session into its own database, so leaving it in the tray is what keeps "
            "your world and people history complete.")
        hint_run.setWordWrap(True)
        hint_run.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_run.vbox.addWidget(hint_run)
        v.addWidget(card_run)

        # data
        card_data = widgets.Card("DATA")
        drow = QHBoxLayout()
        drow.setSpacing(8)
        btn_reindex = widgets.ghost_btn("Reindex now", "refresh")
        btn_reindex.clicked.connect(self.main.start_index)
        btn_cache = widgets.ghost_btn("Clear thumbnail cache", "trash")
        btn_cache.clicked.connect(self._clear_cache)
        btn_open = widgets.ghost_btn("Open data folder", "external")
        btn_open.clicked.connect(lambda: winutil.open_file(self._appdir()))
        btn_upd = widgets.ghost_btn("Check for updates", "refresh")
        btn_upd.clicked.connect(
            lambda: self.main.check_for_update(announce_when_current=True))
        drow.addWidget(btn_reindex)
        drow.addWidget(btn_cache)
        drow.addWidget(btn_open)
        drow.addWidget(btn_upd)
        drow.addStretch(1)
        card_data.vbox.addLayout(drow)
        self.chk_updates = QCheckBox("Check GitHub for a newer release at startup")
        self.chk_updates.setChecked(bool(self.main.cfg.get("check_updates")))
        self.chk_updates.toggled.connect(
            lambda on: self.main.cfg.set("check_updates", bool(on)))
        card_data.vbox.addWidget(self.chk_updates)
        self.lab_cache = QLabel("")
        self.lab_cache.setStyleSheet("color:%s; font-size:11px;" % style.PAL["faint"])
        card_data.vbox.addWidget(self.lab_cache)
        v.addWidget(card_data)

        # about
        card_about = widgets.Card("ABOUT")
        ab = QLabel(f"{paths.APP_NAME} · a VRChat photo album — worlds and instance-mates are read "
                    "from VRCX PNG metadata and the VRChat logs. Everything stays on this "
                    "machine.")
        ab.setWordWrap(True)
        ab.setStyleSheet("color:%s;" % style.PAL["dim"])
        card_about.vbox.addWidget(ab)
        v.addWidget(card_about)

        v.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)
        self.head.attach(scroll, reserve_in=outer)

    def _appdir(self):
        return paths.APPDIR

    def refresh(self):
        while self.folders_box.count():
            it = self.folders_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for f in self.main.cfg.folders:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("folder", style.PAL["dim"], 16,
                                      self.devicePixelRatioF()))
            lab = QLabel(paths.pretty(f))
            lab.setToolTip(f)
            lab.setStyleSheet("color:%s;" % style.PAL["text"])
            rm = widgets.icon_btn("x", "Remove from list", px=14)
            rm.clicked.connect(lambda _c=False, p=f: self._remove_folder(p))
            h.addWidget(ic)
            h.addWidget(lab, 1)
            h.addWidget(rm)
            self.folders_box.addWidget(row)
        if not self.main.cfg.folders:
            lab = QLabel("No folders yet — add one, e.g. Pictures\\VRChat.")
            lab.setStyleSheet("color:%s;" % style.PAL["faint"])
            self.folders_box.addWidget(lab)
        # cache size
        try:
            total = sum(e.stat().st_size for e in os.scandir(paths.THUMB_DIR))
            n = len(os.listdir(paths.THUMB_DIR))
            self.lab_cache.setText(f"Cache: {n} thumbnails · {fmt.human_size(total)} · "
                                   f"{paths.pretty(paths.APPDIR)}")
        except OSError:
            self.lab_cache.setText("")
        self._refresh_api_url()
        self._refresh_backup_label()
        self._refresh_quest_label()

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a photo folder")
        if d:
            folders = self.main.cfg.folders
            if d not in folders:
                folders.append(d)
                self.main.cfg.set("folders", folders)
                self.refresh()
                self.main.start_index()

    def _remove_folder(self, p):
        folders = [f for f in self.main.cfg.folders if f != p]
        self.main.cfg.set("folders", folders)
        self.refresh()
        self.main.toast("Folder removed from the list (files untouched).", "info")

    def _save_self_names(self):
        names = [n.strip() for n in self.ed_self.text().split(",") if n.strip()]
        self.main.cfg.set("self_names", names)

    def _toggle_hook_echo(self):
        self.ed_hook.setEchoMode(
            QLineEdit.Normal if self.ed_hook.echoMode() == QLineEdit.Password
            else QLineEdit.Password)

    def _set_palette(self, key):
        self.main.set_palette(key)
        for k, dot in self._themes:
            dot.selected = (k == key)
            dot.update()

    def _set_accent(self, key):
        self.main.set_accent(key)
        for k, dot in self._dots:
            dot.selected = (k == key)
            dot.update()

    def _toggle_api(self, on):
        self.main.cfg.set("api_enabled", bool(on))
        self.main.apply_api_settings()
        self._refresh_api_url()

    def _change_port(self):
        port = int(self.sp_port.value())
        if port != int(self.main.cfg.get("api_port") or 8770):
            self.main.cfg.set("api_port", port)
            self.main.apply_api_settings()
            self._refresh_api_url()

    def _new_token(self):
        from .httpapi import new_token
        self.main.cfg.set("api_token", new_token())
        self.main.apply_api_settings()
        self._refresh_api_url()
        self.main.toast("New API token — update any Hexpad keys using the old URL.", "info")

    def _copy_api_url(self):
        url = self.ed_api_url.text().strip()
        if url.startswith("http"):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            self.main.toast("API URL copied.", "ok")

    def _refresh_api_url(self):
        url = self.main.api.url("discord") if self.main.api.running else ""
        self.ed_api_url.setText(url or "(API is off)")

    def _pick_backup_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the backup folder",
                                             self.ed_backup.text().strip() or "")
        if d:
            self.ed_backup.setText(d)
            self.main.cfg.set("backup_dir", d)
            self._refresh_backup_label()

    def _refresh_backup_label(self):
        dest = (self.main.cfg.get("backup_dir") or "").strip()
        if not dest:
            self.lab_backup.setText(
                "Your library is irreplaceable and lives on one drive. Point this at "
                f"another one and {paths.APP_NAME} will copy anything missing, verify it, "
                "and never delete a thing at the destination.")
            return
        last = backup.last_run(dest) if os.path.isdir(dest) else ""
        self.lab_backup.setText(f"Last backup: {last}" if last
                                else f"No backup written to {dest} yet.")

    def _run_backup(self):
        dest = (self.main.cfg.get("backup_dir") or "").strip()
        if not dest:
            self.main.toast("Pick a backup folder first.", "err")
            return
        self.main.run_backup(dest, bool(self.main.cfg.get("backup_verify_hash")))

    def _pick_adb(self):
        f, _ = QFileDialog.getOpenFileName(self, "Locate adb.exe",
                                           self.ed_adb.text().strip() or "",
                                           "adb (adb.exe)")
        if f:
            self.ed_adb.setText(f)
            self.main.cfg.set("adb_path", f)
            self._refresh_quest_label()

    def _refresh_quest_label(self):
        adb = questimport.find_adb(self.main.cfg.get("adb_path") or "")
        if not adb:
            self.lab_quest.setText(
                "Photos taken on a standalone headset never reach the PC. Install "
                "Android platform-tools (or point this at SideQuest's adb.exe), plug "
                "the headset in with USB debugging on, and they get copied into your "
                "first photo folder.")
            return
        devs = questimport.devices(adb)
        ready = [s for s, st in devs if st == "device"]
        unauth = [s for s, st in devs if st != "device"]
        if ready:
            self.lab_quest.setText(f"adb found · headset connected ({ready[0]})")
        elif unauth:
            self.lab_quest.setText("adb found · headset connected but not authorised — "
                                   "put it on and accept the USB debugging prompt")
        else:
            self.lab_quest.setText("adb found · no headset connected")

    def _run_quest_import(self):
        folders = self.main.cfg.folders
        if not folders:
            self.main.toast("Add a photo folder first.", "err")
            return
        self.main.run_quest_import(self.main.cfg.get("adb_path") or "", folders[0])

    def _pick_frame_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the frame folder",
                                             self.ed_frame.text().strip() or "")
        if d:
            self.ed_frame.setText(d)
            self.main.cfg.set("frame_dir", d)

    def _toggle_autostart(self, on):
        exe, args = winutil.autostart_command("--tray")
        ok = winutil.set_autostart(paths.APP_NAME, f'"{exe}" {args}' if on else "")
        self.main.cfg.set("autostart", bool(on))
        if not ok:
            self.main.toast("Could not write the autostart entry.", "err")
        elif on:
            self.main.toast(
                f"{paths.APP_NAME} will start with Windows, hidden in the tray.", "ok")
        else:
            self.main.toast("Autostart removed.", "ok")

    def _clear_cache(self):
        n = 0
        try:
            for e in os.scandir(paths.THUMB_DIR):
                try:
                    os.remove(e.path)
                    n += 1
                except OSError:
                    pass
        except OSError:
            pass
        self.main.toast(f"{n} thumbnails cleared from the cache.", "ok")
        self.refresh()
