"""Capture and verify the Lab 11 HTTP contract against controlled Lab 4 pairs."""

from __future__ import annotations

import base64
import io
import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from PIL import Image

from lab11.inspect import InspectionService
from lab11.server import create_server
from lab09 import experiment


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
SNAPSHOT = ROOT / "results" / "api_examples.json"


def pair_payload(pair_id: str) -> dict:
    pairs = json.loads((REPOSITORY / "lab06" / "data" / "prepared.json").read_text(encoding="utf-8"))["pairs"]
    row = next(row for row in pairs if row["pair_id"] == pair_id)
    return {
        "original_base64": base64.b64encode((REPOSITORY / row["original"]).read_bytes()).decode("ascii"),
        "candidate_base64": base64.b64encode((REPOSITORY / row["candidate"]).read_bytes()).decode("ascii"),
        "original_box": row["original_box"],
        "candidate_box": row["candidate_box"],
    }


def request(port: int, path: str, body: bytes, content_type: str = "application/json") -> tuple[int, dict]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, body=body, headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        })
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def request_declared_too_large(port: int, max_body_bytes: int) -> tuple[int, dict]:
    """Exercise the Content-Length guard without uploading an oversized body.

    The server rejects this request from its headers, so sending the claimed
    body would only make a normal HTTP client hit a broken pipe after 413.
    """
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest("POST", "/inspect")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(max_body_bytes + 1))
        connection.endheaders()
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def invoke(service: InspectionService, name: str, payload: object, expected: tuple[int, str], path="/inspect",
           content_type="application/json") -> dict:
    with create_server(service, port=0) as httpd:
        worker = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            status, output = request(httpd.server_port, path, body, content_type)
        finally:
            httpd.shutdown()
            worker.join()
    actual = output.get("assessment") if status == 200 else output.get("error")
    if (status, actual) != expected:
        raise ValueError(f"{name}: expected {expected}, got {(status, actual)}")
    return {
        "case": name,
        "request": {
            "path": path,
            "content_type": content_type,
            "body_bytes": len(body),
            **({"raw_utf8": payload.decode("utf-8")} if isinstance(payload, bytes) else {"json": payload}),
        },
        "expected": {"http_status": expected[0], "assessment_or_error": expected[1]},
        "http_status": status,
        "output": output,
    }


def invoke_declared_too_large(service: InspectionService) -> dict:
    with create_server(service, port=0) as httpd:
        worker = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            status, output = request_declared_too_large(httpd.server_port, service.config["max_body_bytes"])
        finally:
            httpd.shutdown()
            worker.join()
    if (status, output.get("error")) != (413, "body_too_large"):
        raise ValueError(f"body_too_large: expected (413, body_too_large), got {(status, output.get('error'))}")
    return {
        "case": "body_too_large",
        "request": {
            "path": "/inspect",
            "content_type": "application/json",
            "declared_body_bytes": service.config["max_body_bytes"] + 1,
            "body_sent": False,
        },
        "http_status": status,
        "output": output,
    }


def scenarios() -> list[dict]:
    selected = InspectionService.load()
    candidate = InspectionService.load(force_mode="candidate")
    unavailable = InspectionService(selected.config, None, "fixture")
    valid = pair_payload("PAIR001_01")
    critical = pair_payload("PAIR001_08")
    invalid_box = dict(valid, original_box=[0, 0, 10000, 10])
    with Image.open(io.BytesIO(base64.b64decode(valid["original_base64"]))) as source:
        encoded = io.BytesIO()
        source.save(encoded, format="JPEG")
    wrong_format = dict(valid, original_base64=base64.b64encode(encoded.getvalue()).decode("ascii"))
    cases = [
        invoke(selected, "normal_passed", valid, (200, "passed")),
        invoke(selected, "normal_suspected", critical, (200, "suspected_distortion")),
        invoke(candidate, "forced_candidate", critical, (200, "suspected_distortion")),
        invoke(selected, "not_object", [], (400, "object_required")),
        invoke(selected, "invalid_json", b'{"original_base64":', (400, "invalid_json")),
        invoke(selected, "invalid_base64", dict(valid, original_base64="%%%"), (400, "original_invalid_base64")),
        invoke(selected, "wrong_format", wrong_format, (415, "original_must_be_png")),
        invoke(selected, "invalid_box", invalid_box, (400, "invalid_box")),
        invoke(selected, "wrong_media_type", valid, (415, "unsupported_media_type"), content_type="text/plain"),
        invoke(selected, "unknown_route", valid, (404, "not_found"), path="/unknown"),
        invoke_declared_too_large(selected),
        invoke(unavailable, "unavailable", valid, (503, "model_unavailable")),
    ]
    with patch.object(experiment, "candidate_score", side_effect=RuntimeError("controlled failure")):
        fallback = invoke(candidate, "candidate_fallback", critical, (200, "suspected_distortion"))
    if (fallback["output"]["status"], fallback["output"]["mode"], fallback["output"]["fallback_reason"]) != (
        "fallback", "baseline", "candidate_scoring_failed"
    ):
        raise ValueError("Модуль не подтвердил резервное переключение на baseline")
    cases.append(fallback)
    return cases


def stable(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true")
    action.add_argument("--request", metavar="PAIR_ID", help="Print one valid JSON request")
    args = parser.parse_args()
    if args.request:
        try:
            payload = pair_payload(args.request)
        except StopIteration:
            parser.error(f"Неизвестная пара: {args.request}")
        print(json.dumps(payload, ensure_ascii=False))
        return
    rows = scenarios()
    content = stable(rows)
    if args.write:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(content, encoding="utf-8")
    elif SNAPSHOT.read_text(encoding="utf-8") != content:
        raise SystemExit("Снимок API отличается. Запустите с --write только после проверки причин.")
    print(f"{len(rows)} HTTP-сценариев: OK")


if __name__ == "__main__":
    main()
