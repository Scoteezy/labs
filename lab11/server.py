"""Local HTTP transport for the Lab 11 reference-poster search module."""

import argparse
import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Type

from lab11.search import ApiError, DEFAULT_CONFIG, SearchService


POSTER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
BODY_READ_TIMEOUT_SECONDS = 2.0


def json_bytes(value: dict) -> bytes:
    """Serialize one API response consistently for clients and saved examples."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def error_body(code: str, status: int) -> dict:
    """Return the common structured error shape without exposing server internals."""
    return {
        "status": "unavailable" if status == HTTPStatus.SERVICE_UNAVAILABLE else "error",
        "error": code,
        "results": [],
    }


def reject_json_constant(value: str) -> None:
    raise ValueError(f"{value} is outside JSON")


def handler_for(service: SearchService) -> Type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one already-loaded immutable service."""

    class SearchHandler(BaseHTTPRequestHandler):
        server_version = "Lab11Search/1.0"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(BODY_READ_TIMEOUT_SECONDS)

        def log_message(self, format: str, *args: Any) -> None:
            """Keep the teaching server quiet unless an embedding application logs it."""

        def send_json(self, status: int, body: dict) -> None:
            content = json_bytes(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def send_api_error(self, error: ApiError) -> None:
            self.send_json(error.status, error_body(error.code, error.status))

        def read_json(self) -> object:
            content_type = self.headers.get("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type")

            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or "Transfer-Encoding" in self.headers
                    or not re.fullmatch(r"[0-9]+", lengths[0])):
                raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_content_length")
            digits = lengths[0].lstrip("0") or "0"
            if (len(digits) > len(str(service.max_body_bytes))
                    or int(digits) > service.max_body_bytes):
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large")
            length = int(digits)

            try:
                raw = self.rfile.read(length)
            except OSError:
                raw = b""
            if len(raw) != length:
                raise ApiError(HTTPStatus.BAD_REQUEST, "incomplete_body")
            try:
                return json.loads(raw.decode("utf-8"), parse_constant=reject_json_constant)
            except (ValueError, RecursionError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json")

        def do_POST(self) -> None:
            route = self.path.partition("?")[0]
            if route != "/search":
                self.send_json(HTTPStatus.NOT_FOUND, error_body("not_found", HTTPStatus.NOT_FOUND))
                return
            try:
                payload = self.read_json()
                self.send_json(HTTPStatus.OK, service.search(payload))
            except ApiError as error:
                self.send_api_error(error)

        def do_GET(self) -> None:
            route = self.path.partition("?")[0]
            prefix = "/posters/"
            if not route.startswith(prefix):
                self.send_json(HTTPStatus.NOT_FOUND, error_body("not_found", HTTPStatus.NOT_FOUND))
                return
            poster_id = route[len(prefix):]
            if not POSTER_ID.fullmatch(poster_id):
                self.send_json(HTTPStatus.NOT_FOUND, error_body("not_found", HTTPStatus.NOT_FOUND))
                return
            try:
                image = service.get_image(poster_id)
            except ApiError as error:
                self.send_api_error(error)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(image)

    return SearchHandler


def create_server(service: SearchService, port: Optional[int] = None) -> ThreadingHTTPServer:
    """Build a loopback server. Passing port zero asks the OS for a free test port."""
    address = (service.host, service.port if port is None else port)
    return ThreadingHTTPServer(address, handler_for(service))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=("baseline", "candidate"),
                        help="Override the configured search mode")
    parser.add_argument("--port", type=int, help="Override the configured loopback port")
    args = parser.parse_args()
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        service = SearchService.load(args.config, mode=args.mode)
        httpd = create_server(service, port=args.port)
    except (ApiError, OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")
    if service.resource_error:
        print(f"Resource check: {service.resource_error}", file=sys.stderr)
    try:
        print(f"Listening on http://{httpd.server_address[0]}:{httpd.server_address[1]}", flush=True)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
