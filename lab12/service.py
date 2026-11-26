"""Connect the frozen image detector to review rules and durable designer actions."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
from datetime import datetime, timezone
from contextlib import closing

from lab11.inspect import ApiError, InspectionService

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
CONFIG = ROOT / "config.json"
KNOWLEDGE = ROOT / "knowledge.json"
PREPARED = REPOSITORY / "lab06/data/prepared.json"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}")


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def require_object(value: object) -> dict:
    if not isinstance(value, dict):
        raise ApiError(400, "object_required")
    return value


def identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ApiError(400, code)
    return value


def load_resources() -> tuple[dict, dict, dict]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["host"] != "127.0.0.1" or config["max_body_bytes"] != 4096:
        raise ValueError("Unexpected localhost configuration")
    for name, expected in config["input_sha256"].items():
        if digest((REPOSITORY / name).read_bytes()) != expected:
            raise ValueError(f"Resource checksum differs: {name}")
    knowledge = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    prepared = json.loads(PREPARED.read_text(encoding="utf-8"))
    if knowledge["version"] != config["knowledge_version"] or prepared["dataset_version"] != config["dataset_version"]:
        raise ValueError("Resource version differs")
    records = {
        row["pair_id"]: row for row in prepared["pairs"]
        if row["rights_status"] == "project_generated" and row["source"] == "controlled_synthetic"
    }
    return config, knowledge, records


class ReviewStore:
    """SQLite transactions make retries and competing decisions consistent."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS inspections (
                    inspection_id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    review_status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    event_id TEXT PRIMARY KEY,
                    inspection_id TEXT NOT NULL UNIQUE REFERENCES inspections(inspection_id),
                    request TEXT NOT NULL,
                    response TEXT NOT NULL
                );
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def remember(self, output: dict) -> dict:
        with self.lock, closing(self.connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO inspections VALUES (?, ?, ?, ?)",
                (output["inspection_id"], output["record_id"], json_text(output), output["review_status"]),
            )
            return self.read(db, output["inspection_id"])

    def read(self, db: sqlite3.Connection, inspection_id: str) -> dict:
        row = db.execute("SELECT * FROM inspections WHERE inspection_id = ?", (inspection_id,)).fetchone()
        if row is None:
            raise ApiError(404, "inspection_not_found")
        output = json.loads(row["payload"])
        output["review_status"] = row["review_status"]
        event = db.execute("SELECT response FROM feedback WHERE inspection_id = ?", (inspection_id,)).fetchone()
        output["feedback"] = json.loads(event["response"]) if event else None
        output["release_allowed"] = row["review_status"] == "designer_accepted"
        return output

    def get(self, inspection_id: str) -> dict:
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            return self.read(db, inspection_id)

    def record(self, request: dict, policy: dict) -> dict:
        with self.lock, closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM feedback WHERE event_id = ?", (request["event_id"],)).fetchone()
            if prior:
                if prior["request"] != json_text(request):
                    raise ApiError(409, "event_id_conflict")
                return json.loads(prior["response"])
            current = self.read(db, request["inspection_id"])
            if current["feedback"] is not None:
                raise ApiError(409, "inspection_already_decided")
            if request["action"] in ("accept", "reject") and current["review_status"] != "awaiting_designer":
                raise ApiError(409, "expert_review_required")
            rule = policy["actions"][request["action"]]
            response = {
                **request,
                "record_id": current["record_id"],
                "status": rule["status"],
                "review_status": rule["review_status"],
                "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "model_updated": False,
                "dataset_updated": False,
                "knowledge_version": current["knowledge_version"],
            }
            db.execute(
                "INSERT INTO feedback VALUES (?, ?, ?, ?)",
                (request["event_id"], request["inspection_id"], json_text(request), json_text(response)),
            )
            db.execute(
                "UPDATE inspections SET review_status = ? WHERE inspection_id = ?",
                (response["review_status"], request["inspection_id"]),
            )
            return response

    def events(self) -> list[dict]:
        with closing(self.connect()) as db:
            return [
                json.loads(row["response"])
                for row in db.execute("SELECT response FROM feedback ORDER BY event_id")
            ]


class ReviewService:
    def __init__(self, store_path: Path):
        self.config, self.knowledge, self.records = load_resources()
        self.detector = InspectionService.load()
        self.store = ReviewStore(store_path)

    def inspect(self, payload: object) -> dict:
        payload = require_object(payload)
        record_id = identifier(payload.get("record_id"), "invalid_record_id")
        row = self.records.get(record_id)
        if row is None:
            raise ApiError(404, "record_not_found")
        context = payload.get("context")
        required = [rule["field"] for rule in self.knowledge["required_context"]]
        if not isinstance(context, dict) or set(context) != set(required) or any(type(v) is not bool for v in context.values()):
            raise ApiError(400, "context_requires_four_booleans")
        reasons = [rule["reason"] for rule in self.knowledge["required_context"] if not context[rule["field"]]]
        images = {}
        for field in ("original", "candidate"):
            content = (REPOSITORY / row[field]).read_bytes()
            if digest(content) != row[f"{field}_sha256"]:
                raise ApiError(503, "image_integrity_failed")
            images[f"{field}_base64"] = base64.b64encode(content).decode("ascii")
        machine = None
        if not reasons:
            machine = self.detector.inspect({
                **images, "original_box": row["original_box"], "candidate_box": row["candidate_box"],
            })
        frozen = {
            "record_id": record_id, "context": context,
            "original_sha256": row["original_sha256"], "candidate_sha256": row["candidate_sha256"],
            "knowledge_sha256": self.config["input_sha256"]["lab12/knowledge.json"],
            "decision_sha256": self.detector.config["decision_sha256"],
        }
        inspection_id = "I_" + digest(json_text(frozen).encode("utf-8"))[:24]
        return self.store.remember({
            "inspection_id": inspection_id,
            "record_id": record_id,
            "status": "manual_review" if reasons else machine["status"],
            "assessment": "manual_review" if reasons else machine["assessment"],
            "review_status": "awaiting_expert" if reasons else "awaiting_designer",
            "release_allowed": False,
            "human_decision_required": True,
            "knowledge_version": self.knowledge["version"],
            "context": context,
            "applied_rules": [rule["rule_id"] for rule in self.knowledge["required_context"]],
            "reasons": reasons,
            "machine_result": machine,
            "provenance": {
                "source": row["source"], "rights_status": row["rights_status"],
                "instruction": self.knowledge["source"],
                "original": row["original"], "candidate": row["candidate"],
                "original_sha256": row["original_sha256"], "candidate_sha256": row["candidate_sha256"],
            },
            "model_updated": False,
            "dataset_updated": False,
        })

    def feedback(self, payload: object) -> dict:
        payload = require_object(payload)
        policy = self.knowledge["feedback"]
        if payload.get("actor") != policy["actor"]:
            raise ApiError(403, "actor_not_allowed")
        action = payload.get("action")
        if not isinstance(action, str) or action not in policy["actions"]:
            raise ApiError(400, "invalid_action")
        note = payload.get("note")
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= policy["note_max_chars"]:
            raise ApiError(400, "note_must_have_1_to_500_chars")
        label, defect = payload.get("proposed_label"), payload.get("defect_type")
        if action == "correct":
            matching = [rule for rule in self.knowledge["label_rules"]
                        if type(label) is int and label == rule["label"] and defect in rule["defect_types"]]
            if not matching:
                raise ApiError(400, "invalid_label_and_defect_type")
        elif label is not None or defect is not None:
            raise ApiError(400, "correction_fields_require_correct")
        request = {
            "event_id": identifier(payload.get("event_id"), "invalid_event_id"),
            "inspection_id": identifier(payload.get("inspection_id"), "invalid_inspection_id"),
            "action": action, "actor": policy["actor"], "note": note.strip(),
            "proposed_label": label, "defect_type": defect,
        }
        return self.store.record(request, policy)
