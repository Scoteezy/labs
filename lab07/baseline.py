"""Baseline SSIM detector for controlled packaging-pair pilot data.

Run from the repository root:
    ../venv/bin/python -m lab07.baseline run
    ../venv/bin/python -m lab07.baseline check
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from lab06.prepare import prepare_pair


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
PREPARED = REPOSITORY / "lab06" / "data" / "prepared.json"
RESULTS = ROOT / "results"
CONFIG = ROOT / "config.json"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_score(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Return difference score in [0, 1], where larger means more change."""
    if reference.shape != candidate.shape or reference.ndim != 2:
        raise ValueError("Ожидаются два выровненных двумерных фрагмента одного размера")
    if min(reference.shape) < 7:
        raise ValueError("Фрагмент слишком мал для SSIM")
    score = 1.0 - structural_similarity(reference, candidate, data_range=1.0)
    return round(float(max(0.0, min(1.0, score))), 12)


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["metric"] != "f1_critical_change" or config["positive_label"] != 1:
        raise ValueError("Конфигурация baseline не соответствует метрике критичного изменения")
    return config


def load_pairs() -> list[dict[str, Any]]:
    payload = json.loads(PREPARED.read_text(encoding="utf-8"))
    pairs = payload["pairs"]
    required = {"pair_id", "original", "candidate", "original_box", "candidate_box", "label", "split"}
    if not pairs or any(required - row.keys() for row in pairs):
        raise ValueError("prepared.json не содержит обязательных полей")
    if any(row["label"] not in (0, 1) or row["split"] not in ("train", "validation", "test") for row in pairs):
        raise ValueError("Некорректная метка или разбиение")
    return pairs


def prepared_images(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    with Image.open(REPOSITORY / row["original"]) as original, Image.open(REPOSITORY / row["candidate"]) as candidate:
        return prepare_pair(original, candidate, row["original_box"], row["candidate_box"])


def score_rows(pairs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for pair in pairs:
        reference, candidate = prepared_images(pair)
        rows.append({
            "pair_id": pair["pair_id"],
            "product_id": pair["product_id"],
            "family_id": pair["family_id"],
            "split": pair["split"],
            "label": pair["label"],
            "defect_type": pair["defect_type"],
            "variation": pair["variation"],
            "score": baseline_score(reference, candidate),
        })
    return sorted(rows, key=lambda row: row["pair_id"])


def confusion(rows: Iterable[dict[str, Any]], threshold: float) -> dict[str, int]:
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for row in rows:
        predicted = int(row["score"] >= threshold)
        actual = row["label"]
        key = "tp" if predicted and actual else "fp" if predicted else "fn" if actual else "tn"
        counts[key] += 1
    return counts


def metrics(rows: Iterable[dict[str, Any]], threshold: float) -> dict[str, Any]:
    rows = list(rows)
    counts = confusion(rows, threshold)
    tp, fp, tn, fn = (counts[key] for key in ("tp", "fp", "tn", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "threshold": threshold,
        "cases": len(rows),
        "positive_cases": sum(row["label"] for row in rows),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "specificity": round(specificity, 6),
        **counts,
    }


def candidate_thresholds(rows: list[dict[str, Any]]) -> list[float]:
    unique = sorted({row["score"] for row in rows})
    if not unique:
        return []
    values = {0.0, 1.0}
    for lower, higher in zip(unique, unique[1:]):
        values.add(round((lower + higher) / 2, 12))
    values.update(unique)
    return sorted(values)


def choose_threshold(rows: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    if not rows or len({row["label"] for row in rows}) != 2:
        raise ValueError("Для выбора порога на validation нужны оба класса")
    options = [(threshold, metrics(rows, threshold)) for threshold in candidate_thresholds(rows)]
    return max(options, key=lambda item: (item[1]["f1"], item[1]["recall"], item[1]["specificity"], -item[0]))


def csv_text(rows: list[dict[str, Any]]) -> str:
    fieldnames = ["pair_id", "product_id", "family_id", "split", "label", "defect_type", "variation", "score"]
    from io import StringIO
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    config = load_config()
    validation = [row for row in rows if row["split"] == "validation"]
    threshold, validation_metrics = choose_threshold(validation)
    splits = {name: [row for row in rows if row["split"] == name] for name in ("train", "validation", "test")}
    return {
        "experiment": "LR07-SSIM-01",
        "dataset_version": json.loads(PREPARED.read_text(encoding="utf-8"))["dataset_version"],
        "method": "1 - SSIM на серых выровненных фрагментах упаковки размером 128x128",
        "score_direction": "большее значение означает большее отличие",
        "selection_split": "validation",
        "threshold_selection": "Максимальный F1, затем Recall, Specificity и меньший порог при равенстве.",
        "threshold": threshold,
        "metrics": {name: metrics(split_rows, threshold) for name, split_rows in splits.items()},
        "validation_selection": validation_metrics,
        "input_sha256": {"lab06/data/prepared.json": sha256(PREPARED)},
        "config_sha256": sha256(CONFIG),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
    }


def selected_examples(rows: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    validation = [row for row in rows if row["split"] == "validation"]
    correct = {0: [], 1: []}
    failures = []
    for row in validation:
        prediction = int(row["score"] >= threshold)
        example = {**row, "prediction": prediction}
        if prediction == row["label"]:
            correct[prediction].append(example)
        else:
            failures.append(example)
    return correct[0][:5] + correct[1][:5] + failures


def write_examples(rows: list[dict[str, Any]], threshold: float) -> str:
    from io import StringIO
    stream = StringIO(newline="")
    fields = ["pair_id", "product_id", "family_id", "split", "label",
              "defect_type", "variation", "score", "prediction"]
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected_examples(rows, threshold))
    return stream.getvalue()


def run(write: bool) -> dict[str, Any]:
    rows = score_rows(load_pairs())
    content = report(rows)
    if write:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "scores.csv").write_text(csv_text(rows), encoding="utf-8", newline="")
        (RESULTS / "examples.csv").write_text(
            write_examples(rows, content["threshold"]), encoding="utf-8", newline="")
        (RESULTS / "summary.json").write_text(stable_json(content), encoding="utf-8")
    return content


def check() -> None:
    rows = score_rows(load_pairs())
    actual = report(rows)
    expected = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    # The published environment records provenance, while checking the results
    # on a different Python patch release or OS remains possible.
    actual.pop("environment")
    expected.pop("environment")
    if actual != expected:
        raise ValueError("Baseline расходится с зафиксированным summary.json")
    expected_scores = (RESULTS / "scores.csv").read_text(encoding="utf-8")
    if csv_text(rows) != expected_scores:
        raise ValueError("Baseline расходится с зафиксированным scores.csv")
    if write_examples(rows, actual["threshold"]) != (RESULTS / "examples.csv").read_text(encoding="utf-8"):
        raise ValueError("Baseline расходится с зафиксированным examples.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check"))
    args = parser.parse_args()
    if args.command == "run":
        print(stable_json(run(write=True)), end="")
    else:
        check()
        print("ЛР 7: SSIM baseline воспроизведён")


if __name__ == "__main__":
    main()
