"""Local podcast server that never exposes project secrets or source files."""

from __future__ import annotations

import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXACT_PUBLIC_PATHS = {"/podcast.xml", "/cover.png"}


def is_public_path(raw_path: str) -> bool:
    path = unquote(urlsplit(raw_path).path)
    if path == "/":
        return True
    if path in EXACT_PUBLIC_PATHS:
        return True
    if not path.startswith("/episodes/"):
        return False
    relative = path.removeprefix("/episodes/")
    return bool(relative) and "/" not in relative and relative.lower().endswith(".mp3")


class PodcastRequestHandler(SimpleHTTPRequestHandler):
    """Serve only the files needed by podcast clients."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _guard_request(self) -> bool:
        if not is_public_path(self.path):
            self.send_error(404, "Not found")
            return False
        if urlsplit(self.path).path == "/":
            self.send_response(302)
            self.send_header("Location", "/podcast.xml")
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if self._guard_request():
            super().do_GET()

    def do_HEAD(self):
        if self._guard_request():
            super().do_HEAD()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), PodcastRequestHandler)
    print(f"Serving podcast files on port {args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local podcast server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
