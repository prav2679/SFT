#!/usr/bin/env python3
"""Serve the CUSF Leaflet frontend and proxy its Tawhiri API calls locally.

Frontend: http://127.0.0.1:8080
Tawhiri backend must be running at http://127.0.0.1:5000
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
BACKEND = os.environ.get("TAWHIRI_BACKEND", "http://127.0.0.1:5000").rstrip("/")
DEFAULT_DATASET = os.environ.get("TAWHIRI_DATASET", "2026-10-02T00:00:00Z")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path.rstrip("/") == "/api/v1":
            params = parse_qsl(parsed.query, keep_blank_values=True)
            if not any(k == "dataset" for k, _ in params):
                params.append(("dataset", DEFAULT_DATASET))
            query = urlencode(params)
            target = f"{BACKEND}/api/v1/?{query}"
            try:
                req = Request(target, headers={"Accept": self.headers.get("Accept", "application/json")})
                with urlopen(req, timeout=300) as response:
                    body = response.read()
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
            except HTTPError as exc:
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (URLError, TimeoutError, OSError) as exc:
                body = ("Local Tawhiri backend unavailable at " + BACKEND + ". Start tawhiri-webapp first. Details: " + str(exc)).encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        super().do_GET()

if __name__ == "__main__":
    print("CUSF Leaflet frontend: http://127.0.0.1:8080")
    print("Tawhiri backend:      " + BACKEND)
    print("Default dataset:      " + DEFAULT_DATASET)
    print("Keep the Tawhiri backend running in a separate terminal.")
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
