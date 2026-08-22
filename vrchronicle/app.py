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
    win = MainWindow(app, cfg, db, auto_index=not args.no_index)

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
