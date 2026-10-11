"""Serve the legacy AngularJS app without npm or Angular CLI."""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent / "legacy-angularjs-app"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(APP_ROOT),
    )
    with socketserver.TCPServer((args.host, args.port), handler) as server:
        print(f"Serving legacy AngularJS app from {APP_ROOT}")
        print(f"Open http://{args.host}:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
