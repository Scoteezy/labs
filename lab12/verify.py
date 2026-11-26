"""Record real HTTP calls, persistent feedback, and unchanged model/data fingerprints."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from lab12.server import create_server
from lab12.service import ReviewService, ROOT, REPOSITORY, digest

SNAPSHOT = ROOT / "results/workflow_examples.json"
CONTEXT = dict(same_product=True, frontal_view=True, label_visible=True, regions_aligned=True)
PROTECTED = (
    "lab06/data/prepared.json", "lab06/data/summary.json",
    "lab09/results/decision.json", "lab11/config.json", "lab12/knowledge.json",
)


def call(port: int, method: str, route: str, payload=None) -> tuple[int, dict]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        connection.request(method, route, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def collect() -> dict:
    before = {name: digest((REPOSITORY / name).read_bytes()) for name in PROTECTED}
    steps = []
    with TemporaryDirectory() as temporary:
        db = Path(temporary) / "review.sqlite"
        service = ReviewService(db)
        with create_server(service, port=0) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                def step(name, method, route, payload, expected_http, expected_field, expected_value):
                    http, output = call(server.server_port, method, route, payload)
                    if http != expected_http or output.get(expected_field) != expected_value:
                        raise ValueError(f"{name}: unexpected response {http}, {output}")
                    steps.append({
                        "case": name, "method": method, "path": route, "input": payload,
                        "expected": {"http_status": expected_http, expected_field: expected_value},
                        "http_status": http, "output": output,
                    })
                    return output

                passed = step("inspect_preserved", "POST", "/inspect",
                              {"record_id": "PAIR001_01", "context": CONTEXT},
                              200, "assessment", "passed")
                accept = {
                    "event_id": "E_accept_01", "inspection_id": passed["inspection_id"],
                    "actor": "designer_demo", "action": "accept",
                    "note": "Визуально проверены надпись, логотип и контур. Упаковка сохранена.",
                }
                step("designer_accepts", "POST", "/feedback", accept, 200, "review_status", "designer_accepted")
                step("retry_same_event", "POST", "/feedback", accept, 200, "review_status", "designer_accepted")
                step("accepted_state", "GET", "/inspections/" + passed["inspection_id"],
                     None, 200, "release_allowed", True)
                false_positive = step("inspect_lighting_false_alarm", "POST", "/inspect",
                                      {"record_id": "PAIR019_04", "context": CONTEXT},
                                      200, "assessment", "suspected_distortion")
                correction = {
                    "event_id": "E_correct_01", "inspection_id": false_positive["inspection_id"],
                    "actor": "designer_demo", "action": "correct", "proposed_label": 0,
                    "defect_type": "none", "note": "Затемнение кадра. Текст, логотип и форма сохранены.",
                }
                step("correct_false_alarm", "POST", "/feedback", correction, 200, "status", "pending_review")
                step("correction_state", "GET", "/inspections/" + false_positive["inspection_id"],
                     None, 200, "review_status", "awaiting_expert")
                step("repeat_inspection_keeps_review", "POST", "/inspect",
                     {"record_id": "PAIR019_04", "context": CONTEXT},
                     200, "review_status", "awaiting_expert")
                step("changed_retry_conflicts", "POST", "/feedback",
                     {**correction, "note": "Другое исправление"}, 409, "error", "event_id_conflict")
                step("decision_after_pending_blocked", "POST", "/feedback",
                     {**accept, "event_id": "E_accept_02", "inspection_id": false_positive["inspection_id"]},
                     409, "error", "inspection_already_decided")
                manual = step("label_visibility_unconfirmed", "POST", "/inspect",
                              {"record_id": "PAIR002_01", "context": {**CONTEXT, "label_visible": False}},
                              200, "assessment", "manual_review")
                if manual["machine_result"] is not None:
                    raise ValueError("An unsupported pair reached the image model")
                step("accept_unverifiable_blocked", "POST", "/feedback",
                     {**accept, "event_id": "E_accept_03", "inspection_id": manual["inspection_id"]},
                     409, "error", "expert_review_required")
                escalation = {
                    "event_id": "E_escalate_01", "inspection_id": manual["inspection_id"],
                    "actor": "designer_demo", "action": "escalate",
                    "note": "Видимость этикетки не подтверждена. Нужен проверяющий и подходящий кадр.",
                }
                step("escalate_uncertain_pair", "POST", "/feedback", escalation, 200, "status", "pending_review")
                suspected = step("inspect_text_change", "POST", "/inspect",
                                 {"record_id": "PAIR001_08", "context": CONTEXT},
                                 200, "assessment", "suspected_distortion")
                step("designer_rejects_frame", "POST", "/feedback", {
                    "event_id": "E_reject_01", "inspection_id": suspected["inspection_id"],
                    "actor": "designer_demo", "action": "reject",
                    "note": "Изменилась значимая надпись на этикетке. Кадр отправлен на доработку.",
                }, 200, "review_status", "designer_rejected")
                step("unknown_record", "POST", "/inspect", {"record_id": "PAIR999_99", "context": CONTEXT},
                     404, "error", "record_not_found")
                step("invalid_context", "POST", "/inspect", {"record_id": "PAIR001_01", "context": {}},
                     400, "error", "context_requires_four_booleans")
                step("wrong_actor", "POST", "/feedback", {**accept, "actor": "anonymous"},
                     403, "error", "actor_not_allowed")
                step("inconsistent_correction", "POST", "/feedback",
                     {**correction, "event_id": "E_invalid_01", "proposed_label": 0, "defect_type": "text"},
                     400, "error", "invalid_label_and_defect_type")
            finally:
                server.shutdown()
                thread.join()
        reopened = ReviewService(db)
        if (len(reopened.store.events()) != 4
                or reopened.store.get(passed["inspection_id"])["release_allowed"] is not True
                or reopened.store.get(false_positive["inspection_id"])["review_status"] != "awaiting_expert"):
            raise ValueError("State was not preserved after reopening SQLite")
        events = reopened.store.events()
        if any(event["model_updated"] or event["dataset_updated"] for event in events):
            raise ValueError("Feedback changed a frozen artifact")
    after = {name: digest((REPOSITORY / name).read_bytes()) for name in PROTECTED}
    if before != after:
        raise ValueError("Model, data, or knowledge changed after feedback")
    return {
        "steps": steps,
        "events_after_restart": events,
        "checks": {
            "sqlite_reopened": True, "stored_events": len(events),
            "retries_create_no_duplicate": True,
            "protected_files_unchanged": before == after, "input_sha256": before,
        },
    }


def comparable(value):
    """Ignore actual event timestamps when reproducing the saved HTTP responses."""
    value = deepcopy(value)

    def visit(obj):
        if isinstance(obj, dict):
            for key, child in obj.items():
                if key == "created_at":
                    parsed = datetime.fromisoformat(child)
                    if parsed.utcoffset() is None:
                        raise ValueError("Event has no timezone")
                    obj[key] = "<actual UTC event time>"
                else:
                    visit(child)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)
    visit(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    actual = collect()
    if args.write:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if comparable(actual) != comparable(expected):
            parser.exit(1, "Сохранённый протокол отличается от нового HTTP-прогона.\n")
    print(f"{len(actual['steps'])} HTTP-сценариев, 4 события после перезапуска, хеши сохранены: OK")


if __name__ == "__main__":
    main()
