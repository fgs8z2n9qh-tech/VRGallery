"""App bootstrap: single instance, style, icon, CLI flags (--index, --shot)."""
import argparse
import os
import sys

from . import paths


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vrchronicle")
    ap.add_argument("--data-dir", metavar="DIR",
                    help="use a different library folder instead of "
                         "%LOCALAPPDATA%\\VRChronicle")
    ap.add_argument("--index", action="store_true", help="headless index, then exit")
    ap.add_argument("--tray", action="store_true", help="start hidden in the system tray")
    ap.add_argument("--no-index", action="store_true",
                    help="do not scan or watch for changes; show the library as it is")
    ap.add_argument("--shot", metavar="PNG", help="screenshot the window to a file and exit")
    ap.add_argument("--page", default="all", help="page key for --shot")
    ap.add_argument("--wait", type=int, default=2600, help="ms to wait before --shot")
    ap.add_argument("--size", metavar="WxH",
                    help="window size for --shot, e.g. 1100x700 (checks narrow layouts)")
    args = ap.parse_args(argv)

    if args.data_dir:
        paths.set_appdir(args.data_dir)
    paths.ensure_dirs()
    paths.enable_crash_log()

    if args.index:
        from PySide6.QtCore import QCoreApplication
        from .config import Config
        from .db import Database
        from .scanner import Bridge, IndexWorker
        _app = QCoreApplication([])
        cfg = Config()
        db = Database()
        bridge = Bridge()
        bridge.index_progress.connect(lambda t, a, b: print(f"[{t}] {a}/{b}"))
        stats = {}
        bridge.index_done.connect(stats.update)
        IndexWorker(db, cfg, bridge).run()
        if stats.get("auth"):
            cfg.add_self_names(stats["auth"])
        print("kesz:", {k: v for k, v in stats.items() if k != "auth"})
        db.close()
        return 0

    from PySide6.QtCore import QLockFile, QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import style, winutil
    from .config import Config
    from .db import Database
    from .mainwindow import MainWindow

    winutil.set_app_id(paths.APP_ID)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(paths.APP_NAME)
    app.setOrganizationName(paths.APP_NAME)
    app.setStyle("Fusion")

    lock = QLockFile(paths.LOCK_PATH)
    lock.setStaleLockTime(0)
    if not args.shot and not lock.tryLock(100):
        QMessageBox.information(None, paths.APP_NAME, paths.APP_NAME + " is already running.")
        return 0

    ico_path = paths.asset(paths.APP_NAME + ".ico")
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))
    else:
        from . import icons
        app.setWindowIcon(QIcon(icons.logo_pixmap(256, 1.0)))

    cfg = Config()
    app.setStyleSheet(style.build_qss(cfg.get("accent")))
    db = Database()
    # A library with photos in it predates the welcome card, so don't ask again.
    # Quitting before answering leaves an empty database, and must ask again.
    if not cfg.get("onboarded") and db.counts()[0] > 0:
        cfg.set("onboarded", True)
    win = MainWindow(app, cfg, db, auto_index=not args.no_index)

    if args.size:
        try:
            w, h = (int(n) for n in args.size.lower().split("x"))
            win.resize(w, h)
            cfg.set("window", [win.x(), win.y(), w, h, False], save=False)
        except (ValueError, TypeError):
            pass
    geo = cfg.get("window")
    if isinstance(geo, list) and len(geo) == 5:
        x, y, w, h, maxed = geo
        win.setGeometry(x, y, w, h)
    else:
        maxed = False

    # The tray icon keeps the process alive; MainWindow.closeEvent quits explicitly
    # when the user really means it, so we never strand a headless process.
    app.setQuitOnLastWindowClosed(False)

    start_hidden = bool(args.tray) or (bool(cfg.get("start_minimized")) and not args.shot)
    if start_hidden:
        win.tray.notify(paths.APP_NAME,
                        "Running in the tray — watching for new VRChat screenshots.")
    elif maxed:
        win.showMaximized()
        winutil.dark_titlebar(win.winId())
    else:
        win.show()
        winutil.dark_titlebar(win.winId())

    if args.shot:
        def snap():
            key = args.page
            if key in ("lightbox", "lightbox-tags"):
                photos = win.page_grid.model.photos()
                if photos:
                    win.open_lightbox(win.page_grid, photos, 0)
                if key == "lightbox-tags":
                    win.lightbox.viewer.set_show_all_tags(True)
            elif key == "lightbox-hover":
                # simulate pointing at the first tag, for documentation shots
                photos = win.page_grid.model.photos()
                if photos:
                    win.open_lightbox(win.page_grid, photos, 0)
                v = win.lightbox.viewer
                if v._tags:
                    v._hover_tag = 0
                    v.update()
            elif key in ("scrolled", "glass"):      # mid-scroll, for the sticky day
                win.activate("all")
                page0 = win.page_grid
                bar = page0.view.verticalScrollBar()
                base = int(bar.maximum() * 0.12) or 400
                from PySide6.QtCore import QPoint as _QP
                from .gridmodel import KindRole as _KR, KIND_PHOTO as _KP
                vp = page0.view.viewport()
                for extra in range(0, 900, 15):     # inside a day, photos at the foot
                    bar.setValue(base + extra)
                    page0._sync_sticky()
                    under = page0.view.indexAt(_QP(vp.width() // 2, vp.height() - 60))
                    if (not page0.sticky.isHidden()
                            and under.isValid() and under.data(_KR) == _KP):
                        break
                if key == "glass":              # ...with the floating panels up
                    from PySide6.QtCore import QItemSelectionModel
                    page = win.page_grid
                    sel = page.view.selectionModel()
                    for row in (3, 4, 5):
                        sel.select(page.model.index(row, 0), QItemSelectionModel.Select)
                    rail = page.rail
                    rail._show_bubble(rail.height() * 0.35)
                    rail._hover_y = rail.height() * 0.35
                    rail.update()
            elif key in ("years", "months"):        # the zoomed-out browsing levels
                win.activate("all")
                win.page_grid.set_level("year" if key == "years" else "month")
            elif key == "rail":                     # the timeline rail, mid-drag
                rail = win.page_grid.rail
                rail._show_bubble(rail.height() * 0.45)
                rail._hover_y = rail.height() * 0.45
                rail.update()
            elif key == "stats-year":               # statistics narrowed to a year
                win.activate("stats")
                if win.page_stats.cb_year.count() > 1:
                    win.page_stats.cb_year.setCurrentIndex(1)
            elif key.startswith("person:"):         # e.g. person:The_Woozoo
                win.show_person(key.split(":", 1)[1])
            elif key.startswith("cleanup:"):        # e.g. cleanup:dupes
                win.activate("cleanup")
                win.page_cleanup.mode = key.split(":", 1)[1]
                for b in win.page_cleanup.seg_group.buttons():
                    b.setChecked(b.property("mode") == win.page_cleanup.mode)
                win.page_cleanup.refresh()
            elif key and key != "all":
                win.activate(key)

            def grab():
                pm = win.grab()
                pm.save(args.shot)
                print("shot:", args.shot)
                win.quit_app()      # proper teardown: joins workers before exit
            QTimer.singleShot(max(400, args.wait), grab)
        QTimer.singleShot(300, snap)

    return app.exec()
