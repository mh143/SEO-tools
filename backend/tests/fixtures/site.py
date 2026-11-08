"""A tiny configurable HTTP server used as a crawl target in tests (bound to 127.0.0.1)."""

from __future__ import annotations

import gzip
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class FixtureSite:
    def __init__(self, routes: dict[str, tuple] | None = None, port: int = 0):
        # route path -> (status, headers: dict, body: bytes|str) or callable(handler)->tuple
        self.routes: dict = routes or {}
        self.hits: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _handler(self):
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self, with_body=True):
                path = urlsplit(self.path).path
                full = self.path
                n = int(self.headers.get("Content-Length") or 0)
                self.body = self.rfile.read(n) if n else b""
                site.hits.append(full if self.command in ("GET", "HEAD") else f"{self.command} {full}")
                route = (site.routes.get(f"{self.command} {path}") or site.routes.get(full) or site.routes.get(path)
                         or site.routes.get("*"))
                if route is None:
                    status, headers, body = 404, {"Content-Type": "text/html"}, "<html><body>Not found</body></html>"
                elif callable(route):
                    status, headers, body = route(self)
                else:
                    status, headers, body = route
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(status)
                headers = dict(headers)
                headers.setdefault("Content-Type", "text/html; charset=utf-8")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if with_body:
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def do_GET(self):
                self._serve()

            def do_HEAD(self):
                self._serve(False)

            def do_POST(self):
                self._serve()

            def do_PUT(self):
                self._serve()

            def do_DELETE(self):
                self._serve()

            def do_PATCH(self):
                self._serve()

        return H

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def slow(seconds: float, body: str = "<html></html>"):
    def r(_h):
        time.sleep(seconds)
        return 200, {}, body

    return r


def gz(data: bytes) -> bytes:
    return gzip.compress(data)


def page(title: str | None, body: str, head_extra: str = "", lang: str | None = "en") -> str:
    t = f"<title>{title}</title>" if title is not None else ""
    lang_attr = f' lang="{lang}"' if lang else ""
    return (f"<!doctype html><html{lang_attr}><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width'>{t}{head_extra}</head><body>{body}</body></html>")
