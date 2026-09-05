"""Main window: sidebar navigation, page stack, global photo actions."""
import os
import re
import tempfile
from datetime import datetime

from PySide6.QtCore import (QAbstractNativeEventFilter, QSize, Qt, QThreadPool,
                            QTimer)
from PySide6.QtGui import QIcon, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import (backup, export, fmt, frame, icons, moments, paths, questimport, style,
               vrclog, webhook, widgets, winutil, yearreview)
from .db import PhotoFilter
from .gridmodel import ThumbCache
from .gridpage import GridPage
from .httpapi import LocalApi, new_token
from .lightbox import Lightbox
from .pages import (AlbumsPage, AvatarsPage, CleanupPage, MemoriesPage, MomentsPage,
                    PeoplePage, PersonPage, SessionsPage, SettingsPage, StatsPage,
                    WorldsPage)
from .onboarding import Welcome
from .scanner import Bridge, IndexWorker, LiveWatcher, ThumbService
from .slideshow import Slideshow
from .tray import Tray
from . import updates

NAV = [
    ("all", "Photos", "image"),
    ("favs", "Favorites", "heart"),
    ("memories", "Memories", "clock"),
    ("moments", "Moments", "award"),
    ("albums", "Albums", "layers"),
    None,
    ("sessions", "Sessions", "film"),
    ("worlds", "Worlds", "globe"),
    ("people", "People", "users"),
    ("avatars", "Avatars", "user-check"),
    None,
    ("stats", "Statistics", "chart"),
    ("cleanup", "Cleanup", "zap"),
]

WORLD_URL = "https://vrchat.com/home/world/"
# world ids arrive from PNG metadata written by another program, so they are
# untrusted input and get shape-checked before they are ever pasted into a URL
RE_WORLD_ID = re.compile(r"^wrld_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                         r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _nav_icon(name):
    ic = QIcon()
    ic.addPixmap(icons.pixmap(name, style.PAL["dim"], 18, 2.0), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icons.pixmap(name, style.PAL["text"], 18, 2.0), QIcon.Normal, QIcon.On)
    return ic


NO_EDGE = Qt.Edges()      # built once: the empty flag is awkward to construct


class _SnapEventFilter(QAbstractNativeEventFilter):
    """Qt's end of winutil.SnapFilter.

    The logic lives in winutil, which knows nothing about Qt; this is only the
    adapter that lets QApplication deliver native messages to it. It is a module
    global because installNativeEventFilter does NOT take ownership -- a filter
    that goes out of scope leaves Qt calling into freed memory.
    """

    def __init__(self):
        super().__init__()
        self._impl = winutil.SnapFilter()

    def watch(self, hwnd):
        self._impl.watch(hwnd)

    def nativeEventFilter(self, event_type, message):
        return self._impl.nativeEventFilter(event_type, message)


_SNAP_FILTER = _SnapEventFilter()
_SNAP_INSTALLED = False


class MainWindow(QMainWindow):
    EDGE = 8            # gap around the floating panels, and the resize border
    NO_EDGE = NO_EDGE

    def __init__(self, app, cfg, db, auto_index=True):
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.db = db
        self.auto_index = auto_index
        self.setWindowTitle(paths.APP_NAME)
        self.resize(1500, 920)
        # Small enough to be snapped to half of a 1920 screen (960 wide), and to
        # a quarter (960x516). The old 1080x660 made both physically impossible.
        self.setMinimumSize(840, 470)

        self.bridge = Bridge(self)
        self.svc = ThumbService(db, self.bridge, self)
        self.cache = ThumbCache(self.svc, self.bridge, self)
        self._index_worker = None
        # set before anything that can reach start_index: the tray, the local
        # API and F5 are all wired below, and none of them may read a photo
        # while the welcome card is still waiting for an answer
        self.welcome = None
        self._nav_buttons = {}
        self._current_key = "all"
        self._drill_from = None
        self._snap_ready = False

        # Frameless, with the app's own title bar -- and snappable, which it was
        # not: FramelessWindowHint makes a WS_POPUP window and Windows will not
        # snap one at all, by drag, by Win+Left or by the snap-layout flyout.
        # The styles that make it snappable are put back in showEvent and the
        # frame they imply is cancelled again in WM_NCCALCSIZE; see
        # winutil.snap_styles.
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_Hover, True)

        # The sidebar rises to the top margin so the window has the same border
        # all the way round; the window buttons live in a slim strip above the
        # content column, where they cost no vertical space of their own.
        root = QWidget()
        root.setObjectName("Root")
        rl = QHBoxLayout(root)
        rl.setContentsMargins(self.EDGE, self.EDGE, self.EDGE, self.EDGE)
        rl.setSpacing(self.EDGE)
        self.setCentralWidget(root)
        self.titlebar = widgets.TitleBar(self)

        # ---------------- sidebar ----------------
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(228)
        side.setAttribute(Qt.WA_StyledBackground, True)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 16, 14, 14)
        sv.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(34, self.devicePixelRatioF()))
        logo.setFixedSize(34, 34)
        bname = QLabel(paths.APP_NAME)
        bname.setObjectName("BrandName")
        brand.addWidget(logo)
        brand.addWidget(bname)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(14)

        # The nav list scrolls when the window is too short for it. Twelve items
        # want about 520 px and a window snapped to a quarter of a 1080-tall
        # screen has 516; without this the buttons are squeezed past their own
        # minimum and print over one another. Settings and the status line stay
        # pinned below it either way.
        nav_holder = QWidget()
        nv = QVBoxLayout(nav_holder)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(4)
        for entry in NAV:
            if entry is None:
                nv.addSpacing(10)
                continue
            key, label, icon_name = entry
            b = QPushButton("  " + label)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(_nav_icon(icon_name))
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _c=False, k=key: self.activate(k))
            self._nav_buttons[key] = b
            nv.addWidget(b)
        nv.addStretch(1)

        self.nav_scroll = QScrollArea()
        self.nav_scroll.setWidget(nav_holder)
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QScrollArea.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_scroll.setMinimumHeight(0)
        widgets.SmoothScroll(self.nav_scroll)
        sv.addWidget(self.nav_scroll, 1)
        self.btn_settings = QPushButton("  Settings")
        self.btn_settings.setObjectName("NavBtn")
        self.btn_settings.setCheckable(True)
        self.btn_settings.setFocusPolicy(Qt.NoFocus)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setIcon(_nav_icon("settings"))
        self.btn_settings.setIconSize(QSize(18, 18))
        self.btn_settings.clicked.connect(lambda: self.activate("settings"))
        self._nav_buttons["settings"] = self.btn_settings
        sv.addWidget(self.btn_settings)
        sv.addSpacing(8)
        self.lab_status = QLabel("")
        self.lab_status.setObjectName("SidebarStatus")
        self.lab_status.setWordWrap(True)
        sv.addWidget(self.lab_status)
        rl.addWidget(side)

        # ---------------- pages ----------------
        col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.titlebar)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        rl.addWidget(col, 1)

        self.page_grid = GridPage(self, self.cache)
        self.page_memories = MemoriesPage(self, self.cache)
        self.page_albums = AlbumsPage(self, self.cache)
        self.page_moments = MomentsPage(self, self.cache)
        self.page_person = PersonPage(self, self.cache)
        self.page_sessions = SessionsPage(self, self.cache)
        self.page_worlds = WorldsPage(self, self.cache)
        self.page_people = PeoplePage(self, self.cache)
        self.page_avatars = AvatarsPage(self, self.cache)
        self.page_stats = StatsPage(self)
        self.page_cleanup = CleanupPage(self, self.cache)
        self.page_settings = SettingsPage(self)
        for p in (self.page_grid, self.page_memories, self.page_albums, self.page_moments,
                  self.page_person, self.page_sessions, self.page_worlds, self.page_people,
                  self.page_avatars, self.page_stats, self.page_cleanup,
                  self.page_settings):
            self.stack.addWidget(p)
        self.page_grid.back_requested.connect(self.pop_drill)

        self.lightbox = Lightbox(self)
        self.slideshow = Slideshow(cfg)
        self.toast_w = widgets.Toast(self)
        self.toast_w.set_glass_source(self.stack)   # it floats over the page

        # ---------------- wiring ----------------
        self.bridge.index_progress.connect(self._on_index_progress)
        self.bridge.index_done.connect(self._on_index_done)
        self.bridge.toast.connect(self.toast)
        self.bridge.meta_changed.connect(self._on_meta_changed)
        self.bridge.deep_progress.connect(self._on_deep_progress)
        self.bridge.year_ready.connect(self._on_year_ready)
        self.bridge.reindex_needed.connect(self.start_index)
        self.bridge.headset_found.connect(self._on_headset_found)
        self.bridge.sheet_ready.connect(self._on_sheet_ready)
        self.bridge.backup_planned.connect(self._on_backup_planned)
        self.bridge.update_available.connect(self._on_update_available)

        # --no-index keeps a throwaway copy of a library exactly as it is, which
        # is what documentation screenshots need
        # Not on a first run: the welcome card has not been answered yet, and the
        # folder it offers to change is the one the watcher would poll.
        self.watcher = None
        if auto_index and cfg.get("onboarded"):
            self.watcher = LiveWatcher(cfg, self)
            self.watcher.changed.connect(self._on_watch_changed)

        # ---------------- tray + local API ----------------
        self._quitting = False
        self.tray = Tray(self)
        self.tray.show_window.connect(self.show_from_tray)
        self.tray.open_page.connect(lambda k: (self.show_from_tray(), self.activate(k)))
        self.tray.reindex.connect(self.start_index)
        self.tray.slideshow.connect(self._slideshow_favorites)
        self.tray.wallpaper.connect(lambda: self.act_wallpaper())
        self.tray.quit_app.connect(self.quit_app)
        self.tray.show()

        self.api = LocalApi(self._api_status)
        self.api.signals.command.connect(self._on_api_command)
        self.api.signals.log.connect(self.toast)
        self.apply_api_settings()

        QShortcut(QKeySequence("F5"), self, self.start_index)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)

        self.activate("all")

        if not cfg.get("onboarded"):
            self.welcome = Welcome(self)
            self.welcome.finished.connect(self._finish_onboarding)
            self.welcome.setGeometry(root.rect())
            self.welcome.show()
            self.welcome.raise_()
        elif auto_index:
            QTimer.singleShot(150, self.start_index)

        if auto_index and cfg.get("check_updates"):
            QTimer.singleShot(4000, self.check_for_update)

    # ---------------- navigation ----------------
    def activate(self, key):
        self._drill_from = None
        self._current_key = key
        for k, b in self._nav_buttons.items():
            b.setChecked(k == key)
        if key == "all":
            self.page_grid.configure(PhotoFilter(), "Photos", back=False, levels=True)
            self._show_page(self.page_grid)
        elif key == "favs":
            self.page_grid.configure(PhotoFilter(favorites=True), "Favorites", back=False)
            self._show_page(self.page_grid)
        elif key == "memories":
            self.page_memories.refresh()
            self._show_page(self.page_memories)
        elif key == "albums":
            self.page_albums.refresh()
            self._show_page(self.page_albums)
        elif key == "moments":
            self.page_moments.refresh()
            self._show_page(self.page_moments)
        elif key == "sessions":
            self.page_sessions.refresh()
            self._show_page(self.page_sessions)
        elif key == "avatars":
            self.page_avatars.refresh()
            self._show_page(self.page_avatars)
        elif key == "worlds":
            self.page_worlds.refresh()
            self._show_page(self.page_worlds)
        elif key == "people":
            self.page_people.refresh()
            self._show_page(self.page_people)
        elif key == "stats":
            self.page_stats.refresh()
            self._show_page(self.page_stats)
        elif key == "cleanup":
            self.page_cleanup.refresh()
            self._show_page(self.page_cleanup)
        elif key == "settings":
            self.page_settings.refresh()
            self._show_page(self.page_settings)

    def _show_page(self, page):
        """Switch the stack with a quick fade on the incoming page."""
        from PySide6.QtCore import QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        changed = self.stack.currentWidget() is not page
        self.stack.setCurrentWidget(page)
        if not changed:
            return
        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", page)
        anim.setDuration(150)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _push_grid(self, f, title):
        if self._drill_from is None:
            self._drill_from = self._current_key
        for b in self._nav_buttons.values():
            b.setChecked(False)
        self.page_grid.configure(f, title, back=True)
        self._show_page(self.page_grid)

    def pop_drill(self):
        key = self._drill_from or "all"
        self.activate(key)

    def push_world(self, world_id, name):
        self._push_grid(PhotoFilter(world_id=world_id), name or "World")

    def push_person(self, name):
        self._push_grid(PhotoFilter(person=name), name)

    def push_album(self, aid, name):
        self._push_grid(PhotoFilter(album_id=aid), name)

    def push_day(self, day):
        self._push_grid(PhotoFilter(day=day, sort_desc=False), fmt.day_label(day))

    def push_avatar(self, name):
        self._push_grid(PhotoFilter(avatar=name), name)

    def show_person(self, name):
        """The People card opens a profile, not a filtered grid."""
        self._drill_from = self._current_key or "people"
        for b in self._nav_buttons.values():
            b.setChecked(False)
        self.page_person.show_person(name)
        self._show_page(self.page_person)

    def push_moment(self, moment):
        rows = self.db.photos_by_ids_full(moment["ids"])
        if not rows:
            return
        from .gridmodel import PhotoItem
        items = [PhotoItem(r) for r in rows]
        self.open_lightbox(self.page_moments, items, 0)

    def push_session(self, session_id, world_name):
        row = self.db.session_row(session_id)
        title = world_name or (row["world_name"] if row else "") or "Session"
        when = fmt.dt_short(row["start_at"]) if row else ""
        self._push_grid(PhotoFilter(session_id=session_id, sort_desc=False),
                        f"{title} · {when}" if when else title)

    def _focus_search(self):
        if self.stack.currentWidget() is self.page_grid:
            self.page_grid.search.setFocus()
            self.page_grid.search.selectAll()

    # ---------------- indexing ----------------
    def start_index(self):
        if not self.auto_index:
            return
        if self.welcome is not None:
            return      # nothing is read until the welcome card is accepted
        if self._index_worker and self._index_worker.isRunning():
            return
        if self._index_worker is not None:
            # the previous QThread is finished but still a child of this window;
            # without this every index pass would leave one behind for the session
            self._index_worker.deleteLater()
        self._index_worker = IndexWorker(self.db, self.cfg, self.bridge, self)
        self._index_worker.start()

    def _on_index_progress(self, text, done, total):
        if total:
            self.lab_status.setText(f"{text} {done}/{total}")
        else:
            self.lab_status.setText(text)

    def _on_index_done(self, stats):
        if stats.get("auth"):
            self.cfg.add_self_names(stats["auth"])
        total = stats.get("total", 0)
        size = stats.get("bytes", 0)
        self.lab_status.setText(f"{fmt.count_label(total)} photos · {fmt.human_size(size)}")
        new = stats.get("new", 0)
        if new:
            self.toast(f"{new} new {fmt.plural(new, 'photo')} indexed.", "ok")
        # sessions/avatars/worlds can change even with no new photos, because the
        # log pass re-runs — always let the visible page pick that up.
        self.after_photos_changed()
        # background deep pass (thumbs + luma/dhash/VRCX) for anything new
        rows = self.db.unscanned()
        if rows:
            self.svc.sweep(rows)
        if self.watcher is not None:
            self.watcher.rearm()

    def _on_watch_changed(self):
        self.start_index()

    def _on_deep_progress(self, done, total):
        if total and done < total:
            self.lab_status.setText(f"Analyzing photos… {done}/{total}")
        elif total and done >= total:
            t, s, _f = self.db.counts()
            self.lab_status.setText(f"{fmt.count_label(t)} photos · {fmt.human_size(s)}")

    def _on_meta_changed(self, _pid):
        if self.stack.currentWidget() is self.page_grid:
            self.page_grid.view.viewport().update()

    def after_photos_changed(self):
        cur = self.stack.currentWidget()
        for page in (self.page_grid, self.page_worlds, self.page_people, self.page_albums,
                     self.page_stats, self.page_sessions, self.page_avatars,
                     self.page_moments):
            if cur is page:
                page.refresh()
                return

    # ---------------- first run / updates ----------------
    def _finish_onboarding(self):
        if self.welcome is None:
            return                      # a second 'finished' must not re-arm
        self.welcome.hide()
        self.welcome.deleteLater()
        self.welcome = None
        if self.auto_index:
            # exactly one watcher, now pointed at the folder just chosen
            if self.watcher is None:
                self.watcher = LiveWatcher(self.cfg, self)
                self.watcher.changed.connect(self._on_watch_changed)
            else:
                self.watcher.rearm()
        self.start_index()

    def check_for_update(self, announce_when_current=False):
        bridge = self.bridge

        def job():
            try:
                tag, url = updates.check()
            except Exception:
                # a background thread that raises takes the worker down silently
                if announce_when_current:
                    bridge.toast.emit("Could not reach GitHub to check for "
                                      "updates.", "err")
                return
            if tag:
                bridge.update_available.emit(tag, url)
            elif announce_when_current:
                bridge.toast.emit(f"{paths.APP_NAME} {paths.APP_VERSION} is the "
                                  "latest release.", "ok")

        self._run_bg(job)

    def _on_update_available(self, tag, url):
        if QMessageBox.question(
                self, "Update available",
                f"{paths.APP_NAME} {tag} has been released — you are running "
                f"{paths.APP_VERSION}.\n\nOpen the release page?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            winutil.open_url(url)

    def act_wallpaper(self, item=None):
        """Put a photo on the desktop. A copy is used so the original is never
        locked by the shell or rewritten by Windows."""
        if item is None:
            rows = self.db.query_photos(PhotoFilter(favorites=True, media="photo"))
            if not rows:
                rows = self.db.query_photos(PhotoFilter(min_rating=4, media="photo"))
            if not rows:
                self.toast("Mark a favorite first and it can go on your desktop.",
                           "info")
                return
            import random
            from .gridmodel import PhotoItem
            item = PhotoItem(random.choice(rows))
        if getattr(item, "is_video", False):
            self.toast("That one is a recording, not a photo.", "err")
            return
        bridge = self.bridge
        src = item.path

        def job():
            try:
                out = os.path.join(paths.APPDIR, "wallpaper.jpg")
                export.downscaled_copy(src, out, max_px=3840, quality=94)
                ok = winutil.set_wallpaper(out)
                bridge.toast.emit("Desktop wallpaper set." if ok else
                                  "Windows refused the wallpaper change.",
                                  "ok" if ok else "err")
            except Exception as e:
                bridge.toast.emit(f"Wallpaper failed: {e.__class__.__name__}", "err")

        self._run_bg(job)

    # ---------------- tray ----------------
    def show_from_tray(self):
        was_hidden = not self.isVisible()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if was_hidden:
            winutil.dark_titlebar(self.winId())

    def quit_app(self):
        self._quitting = True
        self.close()
        QApplication.quit()

    def _slideshow_favorites(self):
        rows = self.db.query_photos(PhotoFilter(favorites=True))
        if not rows:
            rows = self.db.query_photos(PhotoFilter())
        if not rows:
            self.toast("Nothing to show yet.", "info")
            return
        from .gridmodel import PhotoItem
        self.start_slideshow([PhotoItem(r) for r in rows], 0)

    # ---------------- local API ----------------
    def apply_api_settings(self):
        """(Re)start or stop the loopback API to match the config."""
        self.api.stop()
        if not self.cfg.get("api_enabled"):
            return
        token = (self.cfg.get("api_token") or "").strip()
        if not token:
            token = new_token()
            self.cfg.set("api_token", token)
        self.api.start(int(self.cfg.get("api_port") or 8770), token)

    def _api_status(self):
        """Runs on an API worker thread — DB access only, no widgets."""
        total, size, favs = self.db.counts()
        rows = self.db.query_photos(PhotoFilter())
        latest = rows[0] if rows else None
        return {
            "app": paths.APP_NAME,
            "version": paths.APP_VERSION,
            "photos": total,
            "favorites": favs,
            "bytes": size,
            "latest": {
                "file": os.path.basename(latest["path"]),
                "world": latest["world_name"],
                "taken_at": latest["taken_at"],
            } if latest else None,
        }

    def _on_api_command(self, cmd):
        if cmd == "index":
            self.start_index()
            self.toast("Reindex requested from the local API.", "info")
            return
        rows = self.db.query_photos(PhotoFilter())
        if not rows:
            self.toast("The local API asked for the latest photo, but there is none.", "err")
            return
        from .gridmodel import PhotoItem
        latest = PhotoItem(rows[0])
        if cmd == "discord":
            self.act_share(latest)
        elif cmd == "copy":
            self.act_copy(latest)
        elif cmd == "open":
            self.show_from_tray()
            self.activate("all")
            self.open_lightbox(self.page_grid, self.page_grid.model.photos(), 0)

    # ---------------- shared photo actions ----------------
    def toast(self, text, kind="info"):
        self.toast_w.show_message(text, kind)

    def act_favorite(self, pids, on=None):
        if not pids:
            return
        if on is None:
            favs = self.db.favorites_of(pids)
            on = not (len(favs) == len(pids))
        self.db.set_favorite(pids, on)
        self.page_grid.model.set_favorite(pids, on)
        it = self.lightbox.current()
        if it and it.id in set(pids):
            it.favorite = on
            self.lightbox._refresh_fav_icon()
        if self.page_grid.filter.favorites and not on:
            self.page_grid.refresh()

    def act_rate(self, pids, stars):
        if not pids:
            return
        self.db.set_rating(pids, stars)
        self.page_grid.model.set_rating(pids, stars)
        it = self.lightbox.current()
        if it and it.id in set(pids):
            it.rating = stars
            self.lightbox.refresh_rating()
        self.toast(f"Rated {'★' * stars}" if stars else "Rating cleared.", "ok")
        if self.page_grid.filter.min_rating and stars < self.page_grid.filter.min_rating:
            self.page_grid.refresh()

    def act_tag(self, photo_id, name, x, y, w=0.0, h=0.0):
        self.db.set_photo_tag(photo_id, name, x, y, w, h,
                              datetime.now().isoformat(timespec="seconds"))
        self.toast(f"Tagged {name}.", "ok")

    def act_copy(self, item):
        img = QImage(item.path)
        if img.isNull():
            self.toast("Could not read the image.", "err")
            return
        note = ""
        if (self.cfg.get("copy_mode") or "jpeg") == "jpeg":
            cap = int(self.cfg.get("copy_max_px") or 2560)
            if max(img.width(), img.height()) > cap:
                img = img.scaled(cap, cap, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                note = f" ({img.width()}×{img.height()})"
        QApplication.clipboard().setImage(img)
        self.toast(f"Photo copied to clipboard{note}.", "ok")

    def act_reveal(self, item):
        winutil.reveal_in_explorer(item.path)

    def act_world_link(self, item):
        wid = item.world_id or ""
        if not RE_WORLD_ID.match(wid):
            self.toast("This photo has no usable world id.", "err")
            return
        if winutil.open_url(WORLD_URL + wid):
            self.toast("Opened the world page in your browser.", "ok")

    def _photo_people(self, item):
        _row, players = self.db.photo(item.id)
        selfn = self.cfg.self_names
        return [n for n, _u in players if n not in selfn]

    def _privacy_note(self, item):
        """A caution line when a photo was taken somewhere not everyone could see."""
        itype = getattr(item, "instance_type", "") or ""
        if itype not in vrclog.PRIVATE_INSTANCES:
            return ""
        label = vrclog.INSTANCE_LABELS.get(itype, itype)
        return (f"\n\n⚠ This photo was taken in a {label} instance — the people in it "
                "did not necessarily expect it to leave that group.")

    def _run_bg(self, fn):
        """Run a blocking job off the GUI thread; it reports through bridge.toast."""
        import threading
        threading.Thread(target=fn, daemon=True).start()

    def act_share(self, item):
        if getattr(item, "is_video", False):
            self.toast("Recordings are usually too big for a webhook — share the "
                       "file yourself.", "err")
            return
        url = (self.cfg.get("webhook_url") or "").strip()
        if not url:
            self.toast("Set up your Discord webhook in Settings first.", "err")
            return
        cap_parts = []
        if item.world_name:
            cap_parts.append(f"**{item.world_name}**")
        d = fmt.dt_short(item.taken_at)
        if d:
            cap_parts.append(d)
        caption = " · ".join(cap_parts)
        note = self._privacy_note(item)
        if note and QMessageBox.question(
                self, "Send to Discord",
                "Send this photo to your Discord channel?" + note,
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        captioned = bool(self.cfg.get("share_captioned"))
        people = self._photo_people(item) if captioned else []
        accent = (style.accent(self.cfg.get("accent"))["a"],
                  style.accent(self.cfg.get("accent"))["b"])
        bridge = self.bridge
        self.toast("Sending to Discord…", "info")

        def job():
            send_path, tmp = item.path, None
            if captioned:
                try:
                    # unique per job: two shares in flight must not fight over one file
                    fd, tmp = tempfile.mkstemp(prefix="share_", suffix=".jpg",
                                               dir=paths.APPDIR)
                    os.close(fd)
                    export.captioned_card(item.path, item.world_name, item.taken_at,
                                          people, tmp, accent=accent)
                    send_path = tmp
                except Exception:
                    if tmp:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                    send_path, tmp = item.path, None
            ok, msg = webhook.send_photo(url, send_path, caption)
            bridge.toast.emit(msg, "ok" if ok else "err")
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        self._run_bg(job)

    def act_export_card(self, item):
        export.ensure_export_dir()
        suggested = os.path.join(paths.EXPORT_DIR,
                                 export.suggest_name(item.world_name, item.taken_at))
        out, _f = QFileDialog.getSaveFileName(self, "Save captioned copy", suggested,
                                              "JPEG image (*.jpg)")
        if not out:
            return
        people = self._photo_people(item)
        ac = style.accent(self.cfg.get("accent"))
        bridge = self.bridge
        self.toast("Rendering…", "info")

        def job():
            try:
                export.captioned_card(item.path, item.world_name, item.taken_at,
                                      people, out, accent=(ac["a"], ac["b"]))
                bridge.toast.emit("Captioned copy saved.", "ok")
            except Exception as e:
                bridge.toast.emit(f"Export failed: {e.__class__.__name__}", "err")

        self._run_bg(job)

    def act_frame(self, item):
        frame_dir = (self.cfg.get("frame_dir") or "").strip()
        if not frame_dir:
            self.toast("Pick a frame folder in Settings ▸ In-world frame first.", "err")
            return
        if QMessageBox.question(
                self, "Send to world frame",
                "Publish this photo to your in-world picture frame?\n\n"
                f"It will be written to:\n{frame_dir}\n\n"
                "Anything published there can be seen by everyone who visits the world."
                + self._privacy_note(item),
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        people = self._photo_people(item)
        ac = style.accent(self.cfg.get("accent"))
        cmd = (self.cfg.get("frame_publish_cmd") or "").strip()
        captioned = bool(self.cfg.get("frame_captioned"))
        max_px = int(self.cfg.get("frame_max_px") or 2048)
        bridge = self.bridge
        self.toast("Publishing to the frame…", "info")

        def job():
            ok, msg = frame.publish(item.path, item.world_name, item.taken_at, people,
                                    frame_dir, cmd, max_px=max_px, captioned=captioned,
                                    accent=(ac["a"], ac["b"]))
            bridge.toast.emit(msg, "ok" if ok else "err")

        self._run_bg(job)

    def act_recycle(self, items, after=None):
        if not items:
            return
        total = sum((i.filesize or 0) for i in items)
        label = (f"Move this photo to the Recycle Bin ({fmt.human_size(total)})?"
                 if len(items) == 1 else
                 f"Move {len(items)} photos to the Recycle Bin ({fmt.human_size(total)})?")
        if QMessageBox.question(self, "Recycle", label,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        removed, err = winutil.recycle([i.path for i in items])
        gone = {os.path.normcase(os.path.abspath(p)) for p in removed}
        # only the files that actually disappeared are marked gone in the library
        self.db.mark_recycled([i.id for i in items
                               if os.path.normcase(os.path.abspath(i.path)) in gone],
                              datetime.now().isoformat(timespec="seconds"))
        n = len(removed)
        if err or n < len(items):
            self.toast(f"{n} of {len(items)} moved to the Recycle Bin"
                       + (f" — {err}" if err else "."), "err")
        else:
            self.toast(f"{n} {fmt.plural(n, 'photo')} moved to the Recycle Bin.", "ok")
        if after:
            after()
        self.after_photos_changed()

    def act_album_menu(self, pids, anchor_widget):
        m = self._album_menu(pids)
        m.exec(anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft()))

    def _album_menu(self, pids):
        m = QMenu(self)
        albums = self.db.albums()
        for a in albums:
            act = m.addAction(icons.qicon("layers", style.PAL["dim"], 16), a["name"])
            act.triggered.connect(
                lambda _c=False, aid=a["id"], nm=a["name"]: self._album_add(aid, nm, pids))
        if albums:
            m.addSeparator()
        new = m.addAction(icons.qicon("plus", style.PAL["dim"], 16), "New album…")
        new.triggered.connect(lambda: self._album_new(pids))
        return m

    def _album_add(self, aid, name, pids):
        self.db.album_add(aid, pids, datetime.now().isoformat(timespec="seconds"))
        n = len(pids)
        self.toast(f"Added {n} {fmt.plural(n, 'photo')} to {name}.", "ok")

    def _album_new(self, pids):
        name, ok = QInputDialog.getText(self, "New album", "Album name:")
        name = (name or "").strip()
        if ok and name:
            aid = self.db.create_album(name, datetime.now().isoformat(timespec="seconds"))
            if aid:
                self._album_add(aid, name, pids)

    def show_photo_menu(self, gpos, items, page):
        single = items[0] if len(items) == 1 else None
        m = QMenu(self)
        if single:
            act_open = m.addAction(icons.qicon("maximize", style.PAL["dim"], 16), "Open")
            act_open.triggered.connect(
                lambda: self.open_lightbox(page, page.model.photos(),
                                           max(0, page.model.photos().index(single))
                                           if single in page.model.photos() else 0))
        favs = self.db.favorites_of([i.id for i in items])
        all_fav = len(favs) == len(items)
        act_fav = m.addAction(icons.qicon("star", style.PAL["star"], 16),
                              "Remove favorite" if all_fav else "Add to favorites")
        act_fav.triggered.connect(lambda: self.act_favorite([i.id for i in items]))
        rate = m.addMenu(icons.qicon("award", style.PAL["dim"], 16), "Rate")
        for n in range(5, -1, -1):
            a = rate.addAction("★" * n if n else "No rating")
            a.triggered.connect(lambda _c=False, s=n: self.act_rate(
                [i.id for i in items], s))
        sub = m.addMenu(icons.qicon("layers", style.PAL["dim"], 16), "Add to album")
        real = self._album_menu([i.id for i in items])
        for a in real.actions():
            sub.addAction(a)
        if page.filter.album_id:
            act_rm = m.addAction(icons.qicon("minimize-2", style.PAL["dim"], 16),
                                 "Remove from this album")
            act_rm.triggered.connect(
                lambda: (self.db.album_remove(page.filter.album_id, [i.id for i in items]),
                         page.refresh()))
        if single:
            m.addSeparator()
            act_copy = m.addAction(icons.qicon("copy", style.PAL["dim"], 16),
                                   "Copy to clipboard")
            act_copy.triggered.connect(lambda: self.act_copy(single))
            act_send = m.addAction(icons.qicon("send", style.PAL["dim"], 16),
                                   "Send to Discord")
            act_send.triggered.connect(lambda: self.act_share(single))
            act_card = m.addAction(icons.qicon("award", style.PAL["dim"], 16),
                                   "Save captioned copy…")
            act_card.triggered.connect(lambda: self.act_export_card(single))
            act_frame = m.addAction(icons.qicon("maximize", style.PAL["dim"], 16),
                                    "Send to world frame")
            act_frame.triggered.connect(lambda: self.act_frame(single))
            act_wall = m.addAction(icons.qicon("image", style.PAL["dim"], 16),
                                   "Set as desktop wallpaper")
            act_wall.triggered.connect(lambda: self.act_wallpaper(single))
            act_rev = m.addAction(icons.qicon("folder", style.PAL["dim"], 16),
                                  "Show in Explorer")
            act_rev.triggered.connect(lambda: self.act_reveal(single))
            if single.world_id:
                act_w = m.addAction(icons.qicon("globe", style.PAL["dim"], 16),
                                    "Go to world")
                act_w.triggered.connect(
                    lambda: self.push_world(single.world_id, single.world_name))
                act_wl = m.addAction(icons.qicon("external", style.PAL["dim"], 16),
                                     "Open world on vrchat.com")
                act_wl.triggered.connect(lambda: self.act_world_link(single))
            if single.avatar_name:
                act_av = m.addAction(icons.qicon("user-check", style.PAL["dim"], 16),
                                     f"Photos wearing “{single.avatar_name}”")
                act_av.triggered.connect(lambda: self.push_avatar(single.avatar_name))
        m.addSeparator()
        act_sheet = m.addAction(icons.qicon("layers", style.PAL["dim"], 16),
                                "Contact sheet from selection…")
        act_sheet.triggered.connect(
            lambda: self.act_contact_sheet([i.id for i in items],
                                           items[0].world_name or "VRChat",
                                           f"{len(items)} photos"))
        act_xmp = m.addAction(icons.qicon("edit", style.PAL["dim"], 16),
                              "Write XMP sidecar" + ("s" if len(items) > 1 else ""))
        act_xmp.triggered.connect(lambda: self.act_write_sidecars(items))
        m.addSeparator()
        act_del = m.addAction(icons.qicon("trash", style.PAL["danger"], 16), "Recycle")
        act_del.triggered.connect(lambda: self.act_recycle(items, after=page.refresh))
        m.exec(gpos)

    # ---------------- backup / headset import ----------------
    def run_backup(self, dest, verify_hash):
        if getattr(self, "_backup_busy", False):
            self.toast("A backup is already running.", "info")
            return
        # planning stats every destination file, which is slow on a spun-down
        # external drive — do it off the GUI thread and confirm afterwards
        bridge = self.bridge
        db = self.db
        self.toast("Checking what needs backing up…", "info")

        def plan_job():
            try:
                rows = db.all_photo_paths()
                todo, already, bytes_todo = backup.plan(rows, dest)
                bridge.backup_planned.emit(dest, todo, already, bytes_todo, verify_hash)
            except Exception as e:
                bridge.toast.emit(f"Backup check failed: {e.__class__.__name__}", "err")

        self._run_bg(plan_job)

    def _on_backup_planned(self, dest, todo, already, bytes_todo, verify_hash):
        if not todo:
            self.toast(f"Backup already complete — {already} photos in {dest}.", "ok")
            return
        if QMessageBox.question(
                self, "Back up",
                f"Copy {len(todo)} new {fmt.plural(len(todo), 'photo')} "
                f"({fmt.human_size(bytes_todo)}) to:\n{dest}\n\n"
                f"{already} are already there. Nothing at the destination is ever "
                "deleted.", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._backup_busy = True
        bridge = self.bridge
        self.toast(f"Backing up {len(todo)} photos…", "info")

        def job():
            try:
                def prog(done, total, copied_bytes):
                    if done % 25 == 0 or done == total:
                        bridge.index_progress.emit("Backing up…", done, total)
                copied, failed, nbytes, errors = backup.run(
                    todo, dest, verify_hash=verify_hash, progress=prog)
                msg = f"Backed up {copied} photos ({fmt.human_size(nbytes)})"
                if failed:
                    msg += f" · {failed} failed"
                bridge.toast.emit(msg, "err" if failed else "ok")
            except Exception as e:
                bridge.toast.emit(f"Backup failed: {e.__class__.__name__}", "err")
            finally:
                # must clear even on an unexpected error, or the button stays dead
                self._backup_busy = False
                bridge.index_progress.emit("", 0, 0)

        self._run_bg(job)

    def run_quest_import(self, adb_path, dest_dir):
        # Talking to adb means several subprocess round trips that can each take
        # seconds on a sleeping headset, so the probe runs off the GUI thread and
        # comes back through a signal to raise the confirmation.
        bridge = self.bridge
        self.toast("Looking for a headset…", "info")

        def probe():
            try:
                adb = questimport.find_adb(adb_path)
                if not adb:
                    bridge.toast.emit("adb.exe not found — set its path in Settings.",
                                      "err")
                    return
                devs = [s for s, st in questimport.devices(adb) if st == "device"]
                if not devs:
                    bridge.toast.emit("No authorised headset connected over USB.", "err")
                    return
                remote, names = questimport.list_remote(adb, devs[0])
                if not names:
                    bridge.toast.emit("No VRChat photos found on the headset.", "info")
                    return
                bridge.headset_found.emit(adb, devs[0], remote, names, dest_dir)
            except Exception as e:
                bridge.toast.emit(f"Headset probe failed: {e.__class__.__name__}", "err")

        self._run_bg(probe)

    def _on_headset_found(self, adb, serial, remote, names, dest_dir):
        if QMessageBox.question(
                self, "Import from headset",
                f"Found {len(names)} photos in {remote}.\n\n"
                f"Copy the new ones into:\n{dest_dir}\n\n"
                "Nothing on the headset is changed or deleted.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        bridge = self.bridge
        self.toast("Copying from the headset…", "info")

        def job():
            try:
                def prog(done, total, pulled):
                    if done % 5 == 0 or done == total:
                        bridge.index_progress.emit("Importing from headset…", done, total)
                pulled, skipped, errors = questimport.pull(
                    adb, remote, names, dest_dir, serial, progress=prog)
                msg = f"Imported {pulled} photos"
                if skipped:
                    msg += f" · {skipped} already had"
                if errors:
                    msg += f" · {len(errors)} failed"
                bridge.toast.emit(msg, "err" if errors else "ok")
                if pulled:
                    bridge.reindex_needed.emit()
            except Exception as e:
                # e.g. the destination folder cannot be created at all
                bridge.toast.emit(f"Import failed: {e.__class__.__name__}", "err")
            finally:
                bridge.index_progress.emit("", 0, 0)

        self._run_bg(job)

    # ---------------- contact sheet / metadata sidecars ----------------
    def act_contact_sheet(self, photo_ids, title, subtitle):
        rows = [r for r in self.db.photos_by_ids_full(photo_ids) if not r["is_video"]]
        if not rows:
            self.toast("Nothing to lay out — a contact sheet needs photos.", "err")
            return
        export.ensure_export_dir()
        suggested = os.path.join(paths.EXPORT_DIR,
                                 export.suggest_name(title, rows[0]["taken_at"], "sheet"))
        out, _f = QFileDialog.getSaveFileName(self, "Save contact sheet", suggested,
                                              "JPEG image (*.jpg)")
        if not out:
            return
        entries = [(r["path"], r["mtime"], r["filesize"]) for r in rows[:24]]
        ac = style.accent(self.cfg.get("accent"))
        bridge = self.bridge
        self.toast("Building the contact sheet…", "info")

        def job():
            try:
                export.contact_sheet(entries, title, subtitle, out,
                                     accent=(ac["a"], ac["b"]),
                                     thumb_loader=self._sheet_thumb)
                bridge.sheet_ready.emit(out)
            except Exception as e:
                bridge.toast.emit(f"Contact sheet failed: {e.__class__.__name__}", "err")

        self._run_bg(job)

    @staticmethod
    def _sheet_thumb(entry, size):
        """Reuse the on-disk thumbnail cache so a 24-cell sheet is instant."""
        from PIL import Image
        from . import imaging
        path, mtime, filesize = entry
        try:
            tp = imaging.thumb_path(imaging.thumb_key(path, mtime or 0, filesize or 0))
            if not os.path.exists(tp):
                return None
            im = Image.open(tp).convert("RGB")
            sw, sh = im.size
            if min(sw, sh) < min(size):
                return None
            sc = max(size[0] / sw, size[1] / sh)
            im = im.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), Image.LANCZOS)
            ox = (im.size[0] - size[0]) // 2
            oy = (im.size[1] - size[1]) // 2
            return im.crop((ox, oy, ox + size[0], oy + size[1]))
        except Exception:
            return None

    def act_write_sidecars(self, items):
        # one sidecar per stem: photo.png and photo.jpg would target the same .xmp
        payload, seen, dupes = [], set(), 0
        selfn = self.cfg.self_names
        foreign = 0
        for it in items:
            key = os.path.splitext(it.path)[0].lower()
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            side = os.path.splitext(it.path)[0] + ".xmp"
            if os.path.exists(side):
                try:
                    with open(side, "r", encoding="utf-8", errors="replace") as f:
                        if not export._ours(f.read(2048)):
                            foreign += 1
                except OSError:
                    pass
            row, players = self.db.photo(it.id)
            payload.append((it.path, it.world_name, it.taken_at,
                            [p for p, _u in players if p not in selfn],
                            (row["avatar_name"] if row else "") or "",
                            (row["instance_type"] if row else "") or ""))
        n = len(payload)
        msg = (f"Write an .xmp file next to {n} {fmt.plural(n, 'photo')}?\n\n"
               "Bridge, Lightroom and darktable read these, so the world, the people "
               "and the avatar travel with your files. The photos themselves are "
               "not modified.")
        if foreign:
            msg += (f"\n\n{foreign} of them already have an .xmp from another program. "
                    "A timestamped .bak copy is kept before it is replaced.")
        if dupes:
            msg += f"\n\n{dupes} skipped: same name as another selected photo."
        if QMessageBox.question(self, "Write XMP sidecars", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        bridge = self.bridge

        def job():
            ok = bad = 0
            for path, world, taken, people, avatar, itype in payload:
                try:
                    export.xmp_sidecar(path, world, taken, people, avatar, itype)
                    ok += 1
                except Exception:
                    bad += 1
            bridge.toast.emit(f"{ok} sidecar files written"
                              + (f" · {bad} failed" if bad else "."),
                              "err" if bad else "ok")

        self._run_bg(job)

    # ---------------- year in review ----------------
    def build_year_review(self, year):
        ac = style.accent(self.cfg.get("accent"))
        selfn = sorted(self.cfg.self_names)
        bridge = self.bridge
        db = self.db
        self.toast(f"Building your {year} poster…", "info")
        holder = {}

        def job():
            try:
                path, stats = yearreview.build(db, year, selfn, (ac["a"], ac["b"]))
            except Exception as e:
                bridge.toast.emit(f"Year in review failed: {e.__class__.__name__}", "err")
                return
            if not path:
                bridge.toast.emit(f"No photos from {year}.", "err")
                return
            holder["path"] = path
            holder["stats"] = stats
            bridge.year_ready.emit(path)

        self._run_bg(job)

    def _on_year_ready(self, path):
        self.toast("Year in review saved — opening it now.", "ok")
        winutil.open_file(path)

    def _on_sheet_ready(self, path):
        self.toast("Contact sheet saved — opening it now.", "ok")
        winutil.open_file(path)

    # ---------------- lightbox / slideshow ----------------
    def open_lightbox(self, page, photos, pos):
        self.lightbox.open(photos, pos, page)

    def start_slideshow(self, items, pos):
        self.slideshow.start(items, pos)

    # ---------------- accent ----------------
    def set_accent(self, key):
        self.cfg.set("accent", key)
        self.app.setStyleSheet(style.build_qss(key))
        self.page_grid.delegate.set_accent(style.accent(key)["a"])
        self.page_grid.view.viewport().update()
        self.toast(f"Accent: {style.ACCENTS[key]['label']}", "ok")

    # ---------------- window plumbing ----------------
    # ---------------- frameless window: edges and state ----------------
    def _edges_at(self, pos):
        """Which border the pointer is on, for resizing a frameless window."""
        if self.isMaximized() or self.isFullScreen():
            return NO_EDGE
        m, r = self.EDGE, self.rect()
        edges = NO_EDGE
        if pos.x() <= m:
            edges |= Qt.LeftEdge
        elif pos.x() >= r.width() - m:
            edges |= Qt.RightEdge
        if pos.y() <= m:
            edges |= Qt.TopEdge
        elif pos.y() >= r.height() - m:
            edges |= Qt.BottomEdge
        return edges

    def _cursor_for(self, edges):
        """Qt's edge flags are not ints -- int() on a combined one raises --
        so they are compared as flags rather than used as dictionary keys."""
        if not edges:
            return None
        for combo, cursor in ((Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor),
                              (Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor),
                              (Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor),
                              (Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor)):
            if edges == combo:
                return cursor
        if edges in (Qt.LeftEdge, Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges in (Qt.TopEdge, Qt.BottomEdge):
            return Qt.SizeVerCursor
        return None

    def mouseMoveEvent(self, ev):
        cur = self._cursor_for(self._edges_at(ev.position().toPoint()))
        if cur is None:
            self.unsetCursor()
        else:
            self.setCursor(cur)
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        self.unsetCursor()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        edges = self._edges_at(ev.position().toPoint())
        handle = self.windowHandle()
        if ev.button() == Qt.LeftButton and edges and handle is not None:
            handle.startSystemResize(edges)     # the compositor does the drag
            ev.accept()
            return
        super().mousePressEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        # Not in __init__: there is no native window until the widget is shown,
        # and GetWindowLong on a null handle silently does nothing.
        global _SNAP_INSTALLED
        if not self._snap_ready:
            self._snap_ready = winutil.snap_styles(int(self.winId()))
            if self._snap_ready:
                _SNAP_FILTER.watch(int(self.winId()))
                if not _SNAP_INSTALLED:
                    QApplication.instance().installNativeEventFilter(_SNAP_FILTER)
                    _SNAP_INSTALLED = True

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange and hasattr(self, "titlebar"):
            self.titlebar.sync()
            # a maximised window has no border to grab, and its corners are square
            gap = 0 if self.isMaximized() else self.EDGE
            lay = self.centralWidget().layout()
            lay.setContentsMargins(gap, gap, gap, gap)
            lay.setSpacing(self.EDGE)
            winutil.round_corners(self.winId(), not self.isMaximized())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.lightbox.isVisible():
            self.lightbox.setGeometry(self.centralWidget().rect())
        if self.welcome is not None:
            self.welcome.setGeometry(self.centralWidget().rect())
        self.toast_w._replace()

    def closeEvent(self, ev):
        self.cfg.set("thumb_px", self.page_grid.slider.value(), save=False)
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.cfg.set("window", [g.x(), g.y(), g.width(), g.height(),
                                bool(self.isMaximized())], save=True)
        if not self._quitting and self.cfg.get("close_to_tray") and self.tray.is_visible():
            self.hide()
            self.lightbox.close_box()
            if not self.cfg.get("_tray_hint_shown"):
                self.cfg.set("_tray_hint_shown", True)
                self.tray.notify(paths.APP_NAME,
                                 "Still running in the tray, keeping your VRChat "
                                 "session history. Right-click the icon to quit.")
            ev.ignore()
            return
        self.api.stop()
        self.tray.hide()
        self.slideshow.stop()
        # A QThread that is still running when its Python wrapper is collected
        # aborts the whole process, so this join must not be time-boxed. The
        # worker checks isInterruptionRequested() in every loop, which bounds it.
        self.svc.abort()
        self.svc.pool.clear()
        if self._index_worker is not None:
            self._index_worker.requestInterruption()
            self._index_worker.wait()
        pool_ok = self.svc.pool.waitForDone(5000)
        glob_ok = QThreadPool.globalInstance().waitForDone(3000)
        if pool_ok and glob_ok:
            self.db.close()      # otherwise leave it to the OS: a live worker
                                 # must never meet a closed sqlite connection
        super().closeEvent(ev)
        QApplication.quit()      # QuitOnLastWindowClosed is off for the tray
