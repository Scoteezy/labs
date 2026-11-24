"""Exercise the local HTTP contract and compare full JSON responses with the snapshot."""

import argparse
import json
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Optional

from lab11.search import BASE_IDF, DEFAULT_CONFIG, LEXICON, SearchService, load_config
from lab11.server import create_server


SNAPSHOT = Path(__file__).with_name("results") / "api_examples.json"
NORMAL = "афиша крупным акцентом"
NORMAL_IDS = ("P001", "P011", "P027")
UNKNOWN = "jazz minimalist"


@dataclass
class Case:
    name: str
    profile: str
    payload: object
    http_status: int
    status: str
    error: Optional[str] = None
    ids: tuple[str, ...] = ()
    fallback_reason: Optional[str] = None
    path: str = "/search"
    raw_body: Optional[str] = None
    content_type: str = "application/json; charset=utf-8"


CASES = (
    Case("normal", "baseline", {"query": NORMAL}, 200, "ok", ids=NORMAL_IDS),
    Case("trimmed", "baseline", {"query": f"  {NORMAL}  "}, 200, "ok", ids=NORMAL_IDS),
    Case("synonym_baseline", "baseline", {"query": "саксофон"}, 200, "no_matches"),
    Case("synonym_candidate", "candidate", {"query": "саксофон"}, 200, "ok",
         ids=("P006", "P005", "P004")),
    Case("unknown_language", "candidate", {"query": UNKNOWN}, 200, "no_matches"),
    Case("empty", "baseline", {"query": "  "}, 400, "error", "empty_query"),
    Case("max_length", "baseline", {"query": "я" * 300}, 200, "no_matches"),
    Case("long", "baseline", {"query": "я" * 301}, 400, "error", "query_too_long"),
    Case("bad_type", "baseline", {"query": 42}, 400, "error", "query_must_be_string"),
    Case("missing_query", "baseline", {}, 400, "error", "query_must_be_string"),
    Case("not_object", "baseline", [], 400, "error", "object_required"),
    Case("bad_json", "baseline", None, 400, "error", "invalid_json", raw_body='{"query":'),
    Case("oversize_body", "baseline", None, 413, "error", "body_too_large",
         raw_body=" " * 4097),
    Case("wrong_media_type", "baseline", {"query": NORMAL}, 415, "error",
         "unsupported_media_type", content_type="text/plain"),
    Case("unknown_route", "baseline", {"query": NORMAL}, 404, "error", "not_found",
         path="/unknown"),
    Case("fallback", "candidate_missing_lexicon", {"query": NORMAL}, 200, "fallback",
         ids=NORMAL_IDS, fallback_reason="candidate_unavailable"),
    Case("fallback_no_matches", "candidate_missing_lexicon", {"query": UNKNOWN}, 200,
         "no_matches", fallback_reason="candidate_unavailable"),
    Case("unavailable", "baseline_missing_idf", {"query": NORMAL}, 503, "unavailable",
         "catalog_unavailable"),
)


def load_profile(profile: str, directory: Path) -> SearchService:
    if profile in ("baseline", "candidate"):
        return SearchService.load(mode=profile)
    config = load_config(DEFAULT_CONFIG)
    if profile == "candidate_missing_lexicon":
        config["mode"] = "candidate"
        del config["sha256"][LEXICON]
    elif profile == "baseline_missing_idf":
        del config["sha256"][BASE_IDF]
    else:
        raise ValueError(f"Неизвестный профиль: {profile}")
    path = directory / f"{profile}.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return SearchService.load(path)


def capture(port: int, case: Case) -> dict:
    body = case.raw_body
    if body is None:
        body = json.dumps(case.payload, ensure_ascii=False, separators=(",", ":"))
    raw = body.encode("utf-8")
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", case.path, body=raw, headers={"Content-Type": case.content_type})
        response = connection.getresponse()
        output = json.loads(response.read())
    finally:
        connection.close()

    expected = (case.http_status, case.status, case.error, case.ids, case.fallback_reason)
    actual = (response.status, output["status"], output.get("error"),
              tuple(row["id"] for row in output["results"]), output.get("fallback_reason"))
    if actual != expected:
        raise ValueError(f"{case.name}: ожидалось {expected}, получено {actual}")
    if response.status == 200:
        expected_mode = "candidate" if case.profile == "candidate" else "baseline"
        if output["mode"] != expected_mode or output["human_decision_required"] != bool(case.ids):
            raise ValueError(f"{case.name}: неверный режим или признак ручного выбора")

    return {
        "case": case.name,
        "profile": case.profile,
        "request": {
            "method": "POST",
            "path": case.path,
            "content_type": case.content_type,
            "body_bytes": len(raw),
            **({"json": case.payload} if case.raw_body is None else {"raw_utf8": case.raw_body}),
        },
        "expected": {
            "http_status": case.http_status,
            "status": case.status,
            "error": case.error,
            "ids": list(case.ids),
            "fallback_reason": case.fallback_reason,
        },
        "http_status": response.status,
        "output": output,
    }


def run_cases() -> list[dict]:
    outputs = {}
    with TemporaryDirectory() as temporary:
        for profile in dict.fromkeys(case.profile for case in CASES):
            service = load_profile(profile, Path(temporary))
            with create_server(service, port=0) as server:
                worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
                worker.start()
                try:
                    for case in CASES:
                        if case.profile == profile:
                            outputs[case.name] = capture(server.server_port, case)
                finally:
                    server.shutdown()
                    worker.join()
    return [outputs[case.name] for case in CASES]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Save new HTTP responses to the snapshot")
    args = parser.parse_args()
    try:
        rows = run_cases()
        content = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        if args.write:
            SNAPSHOT.write_text(content, encoding="utf-8")
        elif SNAPSHOT.read_text(encoding="utf-8") != content:
            raise ValueError(f"Повторный прогон расходится с {SNAPSHOT.name}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"{len(rows)} HTTP-сценариев: OK")


if __name__ == "__main__":
    main()
