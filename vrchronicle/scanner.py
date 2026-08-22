"""Index pipeline (files -> DB -> log correlation) + async thumbnail/deep-scan service."""
import os
import threading
import traceback
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal, QFileSystemWatcher
from PySide6.QtGui import QImage

from . import fmt, imaging, vrclog


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


class Bridge(QObject):
    """All cross-thread signals live here (created on the GUI thread)."""
    thumb_ready = Signal(int, QImage)
    meta_changed = Signal(int)
    index_progress = Signal(str, int, int)
    index_done = Signal(dict)
    deep_progress = Signal(int, int)
    toast = Signal(str, str)     # text, kind ('info'|'ok'|'err')
    year_ready = Signal(str)     # path of a rendered poster / contact sheet
    reindex_needed = Signal()    # new files arrived from outside the watcher
    headset_found = Signal(str, str, str, list, str)   # adb, serial, dir, names, dest
    sheet_ready = Signal(str)    # path of a rendered contact sheet
    backup_planned = Signal(str, list, int, int, bool)


class IndexWorker(QThread):
    """One full incremental pass: scan files, parse changed logs, re-match photos."""

    def __init__(self, db, cfg, bridge, parent=None):
        super().__init__(parent)
        self.db = db
        self.cfg = cfg
        self.bridge = bridge

    def run(self):
        try:
            self._run()
        except Exception:
            traceback.print_exc()
            self.bridge.toast.emit("Indexing failed (details in crash.log).", "err")
            self.bridge.index_done.emit({"new": 0, "auth": []})

    def _run(self):
        b = self.bridge
        folders = self.cfg.folders
        b.index_progress.emit("Scanning photos…", 0, 0)
        if self.isInterruptionRequested():
            return
        known = self.db.known_files()
        present = set()
        batch = []
        new_count = 0
        for p in imaging.scan_folder_files(folders):
            if self.isInterruptionRequested():
                return
            present.add(p)
            try:
                st = os.stat(p)
            except OSError:
                continue
            k = known.get(p)
            if k and k[1] == st.st_size and abs((k[2] or 0) - st.st_mtime) < 1.0:
                continue
            t = imaging.parse_shot_time(os.path.basename(p)) or datetime.fromtimestamp(st.st_mtime)
            iso = _iso(t)
            batch.append({"path": p, "folder": os.path.dirname(p),
                          "filename": os.path.basename(p), "taken_at": iso,
                          "day": iso[:10], "filesize": st.st_size, "mtime": st.st_mtime})
            if not k:
                new_count += 1
            if len(batch) >= 500:
                self.db.upsert_photos(batch)
                batch = []
        self.db.upsert_photos(batch)
        self.db.set_missing(present, folders)

        b.index_progress.emit("Reading VRChat logs…", 0, 0)
        stored = self.db.get_meta("log_parser_version")
        if str(stored) != str(vrclog.PARSER_VERSION):
            self.db.forget_logs()      # re-read them with the newer parser
            self.db.set_meta("log_parser_version", vrclog.PARSER_VERSION)
        state = self.db.logs_state()
        auth = set()
        logs = vrclog.find_logs()
        for i, lf in enumerate(logs):
            if self.isInterruptionRequested():
                return
            try:
                st = os.stat(lf)
            except OSError:
                continue
            name = os.path.basename(lf)
            old = state.get(name)
            if old and old[0] == st.st_size:
                continue
            sessions, names, avatars = vrclog.parse_log(lf)
            auth |= names
            self.db.replace_log_sessions(name, st.st_size, st.st_mtime, sessions, avatars)
            b.index_progress.emit("Reading VRChat logs…", i + 1, len(logs))

        b.index_progress.emit("Matching photos to logs…", 0, 0)
        # self names may have only just been learned from this pass
        self_names = set(self.cfg.self_names) | auth
        avatar_events = self.db.self_avatar_events(sorted(self_names))
        matcher = vrclog.SessionMatcher(self.db.all_sessions(), avatar_events)
        rows = self.db.photos_for_log_match()
        # With no avatar timeline (no self names configured yet) we must not write
        # NULLs over avatar tags an earlier pass established.
        keep_avatars = not avatar_events
        matches = []
        for i, r in enumerate(rows):
            if self.isInterruptionRequested():
                return
            dt = fmt.parse_iso(r["taken_at"])
            if not dt:
                continue
            m = matcher.match(dt)
            rec = {"id": r["id"], "session_id": None, "avatar": None, "instance_type": "",
                   "world_id": None, "world_name": None, "source": "none", "players": []}
            if m:
                sid, wid, wname, players, itype = m
                # only claim an avatar for a photo we can actually place in a
                # session — otherwise a stale switch event would label unrelated
                # shots taken days later
                rec.update(session_id=sid, world_id=wid, world_name=wname,
                           source="log", players=players, avatar=matcher.avatar_at(dt),
                           instance_type=itype)
            if r["meta_source"] == "vrcx":
                rec["source"] = "vrcx"
            matches.append(rec)
            if len(matches) >= 800:
                self.db.apply_log_matches(matches, keep_avatars)
                matches = []
                b.index_progress.emit("Matching photos to logs…", i + 1, len(rows))
        self.db.apply_log_matches(matches, keep_avatars)

        total, size, favs = self.db.counts()
        b.index_done.emit({"new": new_count, "auth": sorted(auth),
                           "total": total, "bytes": size, "favorites": favs})


class _Job(QRunnable):
    def __init__(self, svc, pid, path, mtime, size, scanned, want_image):
        super().__init__()
        self.setAutoDelete(True)
        self.svc = svc
        self.pid = pid
        self.path = path
        self.mtime = mtime
        self.size = size
        self.scanned = scanned
        self.want_image = want_image

    def run(self):
        self.svc._run_job(self)


class ThumbService(QObject):
    """Thumbnails + deep scan (luma/dhash/VRCX) off the GUI thread.

    One decode per photo: the same pass writes the disk thumb and fills DB fields.
    Visible grid requests run at high priority, the background sweep at low.
    """

    def __init__(self, db, bridge, parent=None):
        super().__init__(parent)
        self.db = db
        self.bridge = bridge
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, min(6, os.cpu_count() or 4)))
        self._pending = set()
        self._plock = threading.Lock()
        self._sweep_total = 0
        self._sweep_done = 0
        self._abort = False

    def abort(self):
        """Make in-flight jobs return immediately so shutdown can actually join."""
        self._abort = True

    def request_thumb(self, pid, path, mtime, size, scanned):
        with self._plock:
            if pid in self._pending:
                return
            self._pending.add(pid)
        self.pool.start(_Job(self, pid, path, mtime, size, scanned, True), 2)

    def sweep(self, rows):
        """rows: db.unscanned() result."""
        added = 0
        for r in rows:
            with self._plock:
                if r["id"] in self._pending:
                    continue
                self._pending.add(r["id"])
            self.pool.start(_Job(self, r["id"], r["path"], r["mtime"], r["filesize"],
                                 0, False), 0)
            added += 1
        self._sweep_total += added
        return added

    def _run_job(self, job):
        if self._abort:
            with self._plock:
                self._pending.discard(job.pid)
            return
        try:
            key = imaging.thumb_key(job.path, job.mtime or 0, job.size or 0)
            tp = imaging.thumb_path(key)
            need_deep = (not job.scanned) or (not os.path.exists(tp))
            if need_deep:
                try:
                    res = imaging.deep_scan(job.path, key)
                    self.db.set_deep(job.pid, res["width"], res["height"],
                                     res["luma"], res["dhash"])
                    if res["vrcx"]:
                        wid, wname, players = res["vrcx"]
                        self.db.set_meta_vrcx(job.pid, wid, wname, players)
                        self.bridge.meta_changed.emit(job.pid)
                except Exception:
                    self.db.set_deep(job.pid, 0, 0, None, None)
            if job.want_image:
                img = QImage(tp) if os.path.exists(tp) else QImage()
                self.bridge.thumb_ready.emit(job.pid, img)
        finally:
            with self._plock:
                self._pending.discard(job.pid)
            if not job.want_image:
                self._sweep_done += 1
                self.bridge.deep_progress.emit(self._sweep_done, self._sweep_total)


class LiveWatcher(QObject):
    """Fires `changed` when new screenshots land or the newest VRChat log grows."""
    changed = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._fsw = QFileSystemWatcher(self)
        self._fsw.directoryChanged.connect(self._on_dir)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(2500)
        self._debounce.timeout.connect(self.changed)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(15000)
        self._log_timer.timeout.connect(self._poll_logs)
        self._log_state = None
        self.rearm()
        self._log_timer.start()

    def rearm(self):
        dirs = self._fsw.directories()
        if dirs:
            self._fsw.removePaths(dirs)
        want = []
        for f in self.cfg.folders:
            if os.path.isdir(f):
                want.append(f)
                try:
                    for d in os.listdir(f):
                        full = os.path.join(f, d)
                        if os.path.isdir(full) and d.lower() not in imaging.SKIP_DIR_NAMES:
                            want.append(full)
                except OSError:
                    pass
        if want:
            self._fsw.addPaths(want[:64])

    def _on_dir(self, _path):
        self._debounce.start()

    def _poll_logs(self):
        logs = vrclog.find_logs()
        if not logs:
            return
        newest = logs[-1]
        try:
            st = (os.path.basename(newest), os.path.getsize(newest))
        except OSError:
            return
        if self._log_state is None:
            self._log_state = st
            return
        if st != self._log_state:
            self._log_state = st
            self._debounce.start()
