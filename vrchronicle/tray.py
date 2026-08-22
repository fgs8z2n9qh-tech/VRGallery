"""System-tray presence: keeps the log watcher alive while the window is closed."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import icons, paths, style


class Tray(QObject):
    show_window = Signal()
    open_page = Signal(str)
    reindex = Signal()
    slideshow = Signal()
    quit_app = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = QSystemTrayIcon(parent)
        self._icon.setIcon(self._app_icon())
        self._icon.setToolTip(f"{paths.APP_NAME} — {paths.APP_TAGLINE}")

        m = QMenu()
        act_open = m.addAction(icons.qicon("image", style.PAL["dim"], 16),
                               f"Open {paths.APP_NAME}")
        act_open.triggered.connect(self.show_window)
        act_mem = m.addAction(icons.qicon("clock", style.PAL["dim"], 16), "Memories")
        act_mem.triggered.connect(lambda: self.open_page.emit("memories"))
        act_slide = m.addAction(icons.qicon("play", style.PAL["dim"], 16),
                                "Slideshow of favorites")
        act_slide.triggered.connect(self.slideshow)
        m.addSeparator()
        act_idx = m.addAction(icons.qicon("refresh", style.PAL["dim"], 16), "Index now")
        act_idx.triggered.connect(self.reindex)
        m.addSeparator()
        act_quit = m.addAction(icons.qicon("x", style.PAL["dim"], 16), "Quit")
        act_quit.triggered.connect(self.quit_app)
        self._menu = m
        self._icon.setContextMenu(m)
        self._icon.activated.connect(self._on_activated)

    @staticmethod
    def _app_icon():
        import os
        p = paths.asset(paths.APP_NAME + ".ico")
        if os.path.exists(p):
            return QIcon(p)
        return QIcon(icons.logo_pixmap(64, 1.0))

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window.emit()

    def show(self):
        self._icon.show()

    def hide(self):
        self._icon.hide()

    def is_visible(self):
        return self._icon.isVisible()

    def set_tooltip(self, text):
        self._icon.setToolTip(text)

    def notify(self, title, text):
        if self._icon.isVisible() and QSystemTrayIcon.supportsMessages():
            self._icon.showMessage(title, text, self._app_icon(), 4000)
