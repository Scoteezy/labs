"""Run the local Lab 11 HTTP API on 127.0.0.1."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type

from lab11.inspect import ApiError, DEFAULT_CONFIG, InspectionService


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def error_body(code: str, status: int) -> dict:
    return {
        "status": "unavailable" if status == 503 else "error",
        "error": code,
        "human_decision_required": False,
    }


def reject_json_constant(value: str) -> None:
    raise ValueError(f"{value} is outside JSON")


def handler_for(service: InspectionService) -> Type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PackagingInspection/1.0"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format: str, *args) -> None:
            return

        def send_json(self, status: int, body: dict) -> None:
            content = json_bytes(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def read_json(self) -> object:
            media_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
            if media_type != "application/json":
                raise ApiError(415, "unsupported_media_type")
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or "Transfer-Encoding" in self.headers
                    or not re.fullmatch(r"[0-9]+", lengths[0])):
                raise ApiError(400, "invalid_content_length")
            digits = lengths[0].lstrip("0") or "0"
            limit = service.config["max_body_bytes"]
            if len(digits) > len(str(limit)) or int(digits) > limit:
                raise ApiError(413, "body_too_large")
            length = int(digits)
            try:
                raw = self.rfile.read(length)
            except OSError as error:
                raise ApiError(400, "incomplete_body") from error
            if len(raw) != length:
                raise ApiError(400, "incomplete_body")
            try:
                return json.loads(raw.decode("utf-8"), parse_constant=reject_json_constant)
            except (ValueError, RecursionError) as error:
                raise ApiError(400, "invalid_json") from error

        def do_POST(self) -> None:
            if self.path.partition("?")[0] != "/inspect":
                self.send_json(404, error_body("not_found", 404))
                return
            try:
                self.send_json(200, service.inspect(self.read_json()))
            except ApiError as error:
                self.send_json(error.status, error_body(error.code, error.status))

        def do_GET(self) -> None:
            self.send_json(404, error_body("not_found", 404))

    return Handler


def create_server(service: InspectionService, port: int | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((service.host, service.port if port is None else port), handler_for(service))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", type=int)
    parser.add_argument("--mode", choices=("baseline", "candidate"))
    args = parser.parse_args()
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        service = InspectionService.load(args.config, args.mode)
        httpd = create_server(service, args.port)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    try:
        print(f"Listening on http://{httpd.server_address[0]}:{httpd.server_address[1]}", flush=True)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
