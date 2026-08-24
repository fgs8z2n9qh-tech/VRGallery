"""A tiny localhost HTTP API so other local tools (Hexpad keys, scripts) can poke us.

Bound to 127.0.0.1 only and gated by a token that lives in the config, because the
callers on the other end (a Stream-Deck-style key) cannot send custom headers —
the token therefore travels in the query string of a loopback-only request.
"""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Signal

DEFAULT_PORT = 8770
COMMANDS = ("discord", "index", "open", "copy")


def new_token():
    return secrets.token_urlsafe(12)


class ApiSignals(QObject):
    """Marshals requests from server threads onto the GUI thread."""
    command = Signal(str)
    log = Signal(str, str)


class _Handler(BaseHTTPRequestHandler):
    server_version = "VRGallery"
    sys_version = ""

    # --- plumbing ---
    def log_message(self, *_a):
        pass                      # never spam stdout

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _authorized(self, query):
        want = self.server.api_token
        if not want:
            return True
        got = (query.get("token") or [""])[0]
        try:                      # compare bytes: a non-ASCII token must 403, not raise
            return secrets.compare_digest(str(got).encode("utf-8"),
                                          str(want).encode("utf-8"))
        except (UnicodeError, TypeError):
            return False

    # --- routes ---
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authorized(q):
            return self._send(403, {"error": "bad token"})
        if u.path in ("/", "/status"):
            try:
                return self._send(200, self.server.status_provider())
            except Exception:
                return self._send(500, {"error": "status failed"})
        return self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:                       # drain the body so the client sees a clean exchange
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 1 << 20:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass
        if not self._authorized(q):
            return self._send(403, {"error": "bad token"})
        cmd = u.path.strip("/").split("/")[-1].lower()
        if cmd not in COMMANDS:
            return self._send(404, {"error": "unknown command", "accepts": list(COMMANDS)})
        # hand off and answer immediately: the caller (Hexpad) has an 8 s timeout
        self.server.signals.command.emit(cmd)
        return self._send(202, {"ok": True, "queued": cmd})


class LocalApi:
    def __init__(self, status_provider):
        self.signals = ApiSignals()
        self._status_provider = status_provider
        self._server = None
        self._thread = None
        self.port = None
        self.token = ""

    @property
    def running(self):
        return self._server is not None

    def start(self, port=DEFAULT_PORT, token=""):
        self.stop()
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
        except OSError as e:
            self.signals.log.emit(f"Local API could not start on port {port} ({e.errno}).",
                                  "err")
            return False
        srv.daemon_threads = True
        srv.api_token = token
        srv.signals = self.signals
        srv.status_provider = self._status_provider
        self._server = srv
        self.port = int(port)
        self.token = token
        self._thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.4},
                                        name="vrgallery-api", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
        self.port = None

    def url(self, command="discord"):
        if not self.running:
            return ""
        q = f"?token={self.token}" if self.token else ""
        return f"http://127.0.0.1:{self.port}/latest/{command}{q}"
