"""LAN labelling server for the 2026-09-30 eval expansion (news suitability + same-topic pairs).

Serves label.html and stores each labeller's answers under results/<name>.json. Nothing else is
readable or writable. Run: python label_server.py --host 192.168.110.168 --port 4180
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "label.html"
RESULTS = ROOT / "results"
ITEM_IDS = {
    item["item_id"]
    for name in ("topics-to-label.json", "pairs-to-label.json")
    for item in json.loads((ROOT / name).read_text(encoding="utf-8"))
}
NAME = re.compile(r"^[\w一-鿿]{1,20}$")
MAX_BODY = 512 * 1024
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "labels/1"

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] in {"/", "/index.html"}:
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/labels":
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"too large", "text/plain")
            return
        try:
            payload = json.loads(self.rfile.read(length))
            name = str(payload["labeller"]).strip()
            labels = payload["labels"]
            if not NAME.match(name) or not isinstance(labels, dict):
                raise ValueError("bad name or labels")
            clean = {
                item_id: {"label": value["label"], "at": str(value.get("at", ""))[:40]}
                for item_id, value in labels.items()
                if item_id in ITEM_IDS and isinstance(value, dict) and value.get("label") in {"y", "n", "s"}
            }
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, b"bad request", "text/plain")
            return
        record = {
            "labeller": name,
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "client": self.client_address[0],
            "labels": clean,
        }
        with LOCK:
            RESULTS.mkdir(exist_ok=True)
            target = RESULTS / f"{name}.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(target)
        body = json.dumps({"saved": len(clean)}).encode()
        self._send(HTTPStatus.OK, body, "application/json")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        if self.command == "POST":
            print(f"{datetime.now():%H:%M:%S} {self.client_address[0]} {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"labelling page: http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
