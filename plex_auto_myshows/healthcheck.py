import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


log = logging.getLogger(__name__)

HEALTHCHECK_PORT = 9880


def _make_handler(is_healthy: Callable[[], bool], is_ready: Callable[[], bool]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/health"):
                ok = bool(is_healthy())
                self._json(200 if ok else 503, {"healthy": ok})
            elif self.path == "/ready":
                ok = bool(is_ready())
                self._json(200 if ok else 503, {"ready": ok})
            else:
                self._json(404, {"error": "not found"})

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    return Handler


def start_healthcheck(
    is_healthy: Callable[[], bool], is_ready: Callable[[], bool]
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        ("0.0.0.0", HEALTHCHECK_PORT), _make_handler(is_healthy, is_ready)
    )
    threading.Thread(target=server.serve_forever, name="healthcheck", daemon=True).start()
    log.info("Healthcheck server listening on :%d", HEALTHCHECK_PORT)
    return server
