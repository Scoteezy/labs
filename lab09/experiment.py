"""Controlled comparison of SSIM and a fixed local-difference aggregation.

The candidate changes one factor: it adds the 90th percentile of absolute
pixel differences in the same prepared product ROI. Thresholds are still
selected only from validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lab06.prepare import prepare_pair
from lab07 import baseline


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
PREPARED = REPOSITORY / "lab06" / "data" / "prepared.json"
CONFIG = ROOT / "config.json"
RESULTS = ROOT / "results"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["aggregation"] != "0.55 * ssim_difference + 0.45 * q90_absolute_difference":
        raise ValueError("Неожиданная формула candidate")
    if config["selection_split"] != "validation" or config["min_f1_gain"] < 0:
        raise ValueError("Некорректные условия выбора")
    return config


def candidate_score(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Return fixed combined local/global difference score in [0, 1]."""
    global_difference = baseline.baseline_score(reference, candidate)
    local_difference = float(np.quantile(np.abs(reference - candidate), 0.90))
    score = 0.55 * global_difference + 0.45 * local_difference
    return round(float(max(0.0, min(1.0, score))), 12)


def load_pairs() -> list[dict[str, Any]]:
    payload = json.loads(PREPARED.read_text(encoding="utf-8"))
    return payload["pairs"]


def score_rows(pairs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    from PIL import Image
    rows = []
    for pair in pairs:
        with Image.open(REPOSITORY / pair["original"]) as original, Image.open(REPOSITORY / pair["candidate"]) as candidate:
            reference, compared = prepare_pair(original, candidate, pair["original_box"], pair["candidate_box"])
        rows.append({
            "pair_id": pair["pair_id"],
            "product_id": pair["product_id"],
            "family_id": pair["family_id"],
            "split": pair["split"],
            "label": pair["label"],
            "defect_type": pair["defect_type"],
            "variation": pair["variation"],
            "baseline_score": baseline.baseline_score(reference, compared),
            "candidate_score": candidate_score(reference, compared),
        })
    return sorted(rows, key=lambda row: row["pair_id"])


def view(rows: Iterable[dict[str, Any]], score_name: str) -> list[dict[str, Any]]:
    return [{**row, "score": row[score_name]} for row in rows]


def choose(rows: list[dict[str, Any]], score_name: str) -> tuple[float, dict[str, Any]]:
    return baseline.choose_threshold(view(rows, score_name))


def csv_text(rows: list[dict[str, Any]]) -> str:
    fields = ["pair_id", "product_id", "family_id", "split", "label", "defect_type", "variation", "baseline_score", "candidate_score"]
    from io import StringIO
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def evaluation(rows: list[dict[str, Any]], score_name: str, threshold: float) -> dict[str, Any]:
    return {
        split: baseline.metrics(view([row for row in rows if row["split"] == split], score_name), threshold)
        for split in ("train", "validation", "test")
    }


def report() -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_config()
    pairs = load_pairs()
    validation = score_rows(pair for pair in pairs if pair["split"] == "validation")
    baseline_threshold, baseline_validation = choose(validation, "baseline_score")
    candidate_threshold, candidate_validation = choose(validation, "candidate_score")
    gain = round(candidate_validation["f1"] - baseline_validation["f1"], 6)
    deploy_candidate = gain >= config["min_f1_gain"] and candidate_validation["recall"] >= baseline_validation["recall"]
    decision = {
        "experiment": "LR09-LOCAL-01",
        "mode": "candidate" if deploy_candidate else "baseline",
        "reason": (
            "Candidate достиг условия роста F1 и не снизил Recall на validation."
            if deploy_candidate else
            "Candidate не достиг заранее заданного условия выбора на validation, поэтому оставлен baseline."
        ),
        "baseline_threshold": baseline_threshold,
        "candidate_threshold": candidate_threshold,
        "selected_threshold": candidate_threshold if deploy_candidate else baseline_threshold,
        "selected_model_version": "local_ssim_q90_1.0" if deploy_candidate else "ssim_1.0",
        "selection_split": "validation",
        "validation_f1_gain": gain,
        "validation_baseline": baseline_validation,
        "validation_candidate": candidate_validation,
        "selection_rule": {
            "minimum_f1_gain": config["min_f1_gain"],
            "candidate_recall_not_lower_than_baseline": True,
        },
    }
    # Test pairs are scored after the decision and thresholds have been fixed.
    rows = [*validation, *score_rows(pair for pair in pairs if pair["split"] != "validation")]
    baseline_metrics = evaluation(rows, "baseline_score", baseline_threshold)
    candidate_metrics = evaluation(rows, "candidate_score", candidate_threshold)
    segments = []
    for split in ("validation", "test"):
        split_rows = [row for row in rows if row["split"] == split]
        for variation in sorted({row["variation"] for row in split_rows}):
            group = [row for row in split_rows if row["variation"] == variation]
            segments.append({
                "split": split, "variation": variation, "pairs": len(group),
                "baseline": baseline.confusion(view(group, "baseline_score"), baseline_threshold),
                "candidate": baseline.confusion(view(group, "candidate_score"), candidate_threshold),
            })
    summary = {
        "experiment": "LR09-LOCAL-01",
        "dataset_version": json.loads(PREPARED.read_text(encoding="utf-8"))["dataset_version"],
        "change": "Фиксированное добавление 90-го квантиля абсолютной разности к глобальной SSIM-разности.",
        "formula": config["aggregation"],
        "selection_before_test": "Пороги и решение выбраны по validation, test показан после фиксации решения.",
        "baseline": {"threshold": baseline_threshold, "metrics": baseline_metrics},
        "candidate": {"threshold": candidate_threshold, "metrics": candidate_metrics},
        "segments": segments,
        "decision": decision,
        "input_sha256": {"lab06/data/prepared.json": sha256(PREPARED)},
        "config_sha256": sha256(CONFIG),
    }
    return summary, decision


def run(write: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    summary, decision = report()
    if write:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "scores.csv").write_text(csv_text(score_rows(load_pairs())), encoding="utf-8", newline="")
        (RESULTS / "summary.json").write_text(stable_json(summary), encoding="utf-8")
        (RESULTS / "decision.json").write_text(stable_json(decision), encoding="utf-8")
    return summary, decision


def check() -> None:
    summary, decision = run(write=False)
    expected = (RESULTS / "summary.json").read_text(encoding="utf-8")
    if stable_json(summary) != expected:
        raise ValueError("Эксперимент расходится с summary.json")
    if stable_json(decision) != (RESULTS / "decision.json").read_text(encoding="utf-8"):
        raise ValueError("Решение расходится с decision.json")
    if csv_text(score_rows(load_pairs())) != (RESULTS / "scores.csv").read_text(encoding="utf-8"):
        raise ValueError("Эксперимент расходится с scores.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check"))
    args = parser.parse_args()
    if args.command == "run":
        summary, _ = run(write=True)
        print(stable_json(summary), end="")
    else:
        check()
        print("ЛР 9: контролируемый эксперимент воспроизведён")


if __name__ == "__main__":
    main()
