"""Local API for the knowledge rules and designer feedback of Lab 12."""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sqlite3

from lab11.inspect import ApiError
from lab11.server import error_body, handler_for as transport_handler
from lab12.service import ROOT, ReviewService, identifier


def handler_for(service: ReviewService):
    class ReviewHandler(transport_handler(service)):
        def respond(self, operation) -> None:
            try:
                self.send_json(200, operation())
            except ApiError as error:
                self.send_json(error.status, error_body(error.code, error.status))
            except (sqlite3.Error, OSError):
                self.send_json(503, error_body("resource_unavailable", 503))

        def do_POST(self) -> None:
            route = self.path.partition("?")[0]
            operations = {"/inspect": service.inspect, "/feedback": service.feedback}
            operation = operations.get(route)
            if operation is None:
                self.send_json(404, error_body("not_found", 404))
                return
            self.respond(lambda: operation(self.read_json()))

        def do_GET(self) -> None:
            route = self.path.partition("?")[0]
            if route == "/feedback":
                self.respond(lambda: {"events": service.store.events()})
                return
            if route.startswith("/inspections/"):
                inspection_id = route.removeprefix("/inspections/")
                self.respond(lambda: service.store.get(identifier(inspection_id, "invalid_inspection_id")))
                return
            self.send_json(404, error_body("not_found", 404))

    return ReviewHandler


def create_server(service: ReviewService, port: int | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (service.config["host"], service.config["port"] if port is None else port),
        handler_for(service),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument("--db", type=Path, default=ROOT / "runtime/review.sqlite")
    args = parser.parse_args()
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        service = ReviewService(args.db)
        httpd = create_server(service, args.port)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
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
