"""Local native-window launcher, also compatible with an already running server."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
lock = threading.Lock()
process = None


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8765")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_OPTIONS(self):
        self.respond(200, {})

    def do_GET(self):
        self.respond(200, {"ok": True})

    def do_POST(self):
        global process
        if (
            self.headers.get("Origin") not in (None, "http://127.0.0.1:8765")
            or self.path != "/open"
        ):
            self.respond(403, {})
            return
        with lock:
            if process is None or process.poll() is not None:
                with (ROOT / "data" / "overlay.log").open("a", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        [sys.executable, str(ROOT / "overlay.py")],
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
        self.respond(200, {"ok": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8767), Handler).serve_forever()
