"""First run: say what will be read, from where, before reading any of it.

The app's whole trick is parsing VRChat's logs, and "an app that reads your
VRChat logs" deserves an explanation rather than a silent scan.
"""
import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from . import icons, paths, style, vrclog, widgets


class Welcome(QWidget):
    """Covers the window until the user says go."""
    finished = Signal()

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"Welcome {{ background: {style.PAL['bg']}; }}")

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(660)
        v = QVBoxLayout(card)
        v.setContentsMargins(36, 32, 36, 28)
        v.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(56, self.devicePixelRatioF()))
        logo.setFixedSize(56, 56)
        head.addWidget(logo)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        t = QLabel(f"Welcome to {paths.APP_NAME}")
        t.setStyleSheet("font-size:22px; font-weight:700;")
        s = QLabel("A photo album that remembers where you were and who was there")
        s.setStyleSheet("color:%s;" % style.PAL["dim"])
        tcol.addWidget(t)
        tcol.addWidget(s)
        head.addLayout(tcol)
        head.addStretch(1)
        v.addLayout(head)
        v.addWidget(widgets.HLine())

        body = QLabel(
            "To do that it reads two things on this PC, and nothing else:\n\n"
            "•  your VRChat screenshots — only ever read, never modified\n"
            "•  VRChat's own log files — for the world you were in, who joined the "
            "instance, and which avatar you wore\n\n"
            "VRChat deletes those logs after a few sessions, so they are copied into "
            "a database of your own as it goes. Everything stays on this machine; "
            "nothing is uploaded unless you set up Discord sharing yourself.")
        body.setWordWrap(True)
        body.setStyleSheet("font-size:13px; line-height:150%;")
        v.addWidget(body)

        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        v.addLayout(self.rows)

        v.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_folder = widgets.ghost_btn("Choose folder…", "folder")
        self.btn_folder.clicked.connect(self._pick_folder)
        self.btn_go = widgets.ghost_btn("Scan my photos", "check", primary=True)
        self.btn_go.clicked.connect(self._go)
        buttons.addWidget(self.btn_folder)
        buttons.addWidget(self.btn_go)
        v.addLayout(buttons)
        outer.addWidget(card)
        self.refresh()

    # ---- findings ----
    def _row(self, ok, title, detail):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        dot = QLabel()
        dot.setFixedSize(18, 18)
        dot.setPixmap(icons.pixmap("check" if ok else "info",
                                   style.PAL["ok"] if ok else style.PAL["star"],
                                   16, self.devicePixelRatioF()))
        h.addWidget(dot)
        lab = QLabel(f"<b>{title}</b><br><span style='color:{style.PAL['faint']}'>"
                     f"{detail}</span>")
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        h.addWidget(lab, 1)
        return w

    def refresh(self):
        while self.rows.count():
            it = self.rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        folders = self.main.cfg.folders
        folder = folders[0] if folders else ""
        has_folder = bool(folder) and os.path.isdir(folder)
        # This runs while the window is being built, so it is bounded on all
        # three axes: a OneDrive or UNC tree of near-empty folders would
        # otherwise walk for minutes and the app would look hung.
        count = 0
        capped = False
        errs = []
        if has_folder:
            deadline = time.monotonic() + 1.0
            dirs_seen = 0
            for _root, _dirs, files in os.walk(folder, onerror=errs.append):
                count += len(files)
                dirs_seen += 1
                if count > 5000 or dirs_seen >= 2000 or time.monotonic() > deadline:
                    capped = True
                    break
        unreadable = bool(errs) and count == 0
        if not has_folder:
            detail = "Not found. Take a photo in VRChat once, or pick the folder yourself."
        elif unreadable:
            detail = f"{paths.pretty(folder)} — could not be read ({errs[0].strerror})"
        else:
            detail = f"{paths.pretty(folder)} — about {count}{'+' if capped else ''} files"
        self.rows.addWidget(self._row(has_folder and not unreadable,
                                      "Screenshot folder", detail))

        logs = vrclog.find_logs()
        self.rows.addWidget(self._row(
            bool(logs), "VRChat logs",
            (f"{len(logs)} log files in {paths.pretty(paths.vrchat_log_dir())}"
             if logs else
             "None yet — worlds and people will fill in after your next session.")))

        vrcx = os.path.join(os.environ.get("APPDATA", ""), "VRCX")
        has_vrcx = os.path.isdir(vrcx)
        self.rows.addWidget(self._row(
            has_vrcx, "VRCX (optional)",
            "Found — if its screenshot helper is on, world and player names come "
            "straight out of the PNGs." if has_vrcx else
            "Not installed. Everything still works from the logs alone."))

        self.btn_go.setEnabled(has_folder)
        self.btn_go.setText("Scan my photos" if has_folder else "Pick a folder first")

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Where are your VRChat screenshots?")
        if d:
            self.main.cfg.set("folders", [d])
            self.refresh()

    def _go(self):
        self.main.cfg.set("onboarded", True)
        self.finished.emit()
