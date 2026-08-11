"""Serve the capstone health demo from the repository root."""
from __future__ import annotations

import argparse
import http.server
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve demo assets without allowing stale browser copies."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the satellite health capstone demo")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    handler = lambda *a, **kw: NoCacheHandler(*a, directory=str(ROOT), **kw)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Health demo: http://127.0.0.1:{args.port}/demo/")
        print("Press Ctrl+C to stop.")
        server.serve_forever()


if __name__ == "__main__":
    main()
