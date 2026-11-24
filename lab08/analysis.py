"""Analyse SSIM-baseline errors and prepare one constrained LR09 hypothesis."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from lab07 import baseline


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
BASELINE_SUMMARY = REPOSITORY / "lab07" / "results" / "summary.json"
BASELINE_SCORES = REPOSITORY / "lab07" / "results" / "scores.csv"
RESULTS = ROOT / "results"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def read_rows() -> list[dict[str, Any]]:
    with BASELINE_SCORES.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["label"] = int(row["label"])
        row["score"] = float(row["score"])
    return rows


def verdict(row: dict[str, Any], threshold: float) -> str:
    predicted = int(row["score"] >= threshold)
    label = row["label"]
    return "tp" if predicted and label else "fp" if predicted else "fn" if label else "tn"


def segment_metrics(rows: list[dict[str, Any]], threshold: float, field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[field]].append(row)
    output = []
    for value, group in sorted(grouped.items()):
        summary = baseline.metrics(group, threshold)
        output.append({field: value, **summary})
    return output


def analysis() -> dict[str, Any]:
    baseline_summary = json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8"))
    threshold = baseline_summary["threshold"]
    rows = read_rows()
    failures = []
    for row in rows:
        state = verdict(row, threshold)
        if state in ("fp", "fn"):
            failures.append({**row, "error": state})
    validation = [row for row in rows if row["split"] == "validation"]
    return {
        "experiment": "LR08-ERROR-01",
        "baseline_experiment": baseline_summary["experiment"],
        "baseline_threshold": threshold,
        "selection_scope": "Ошибка и гипотеза сформулированы по validation. Test не используется для выбора изменения.",
        "baseline_metrics": baseline_summary["metrics"],
        "segments_by_defect_type": segment_metrics(rows, threshold, "defect_type"),
        "segments_by_variation": segment_metrics(rows, threshold, "variation"),
        "validation_failures": [
            {key: value for key, value in row.items() if key != "split"}
            for row in failures if row["split"] == "validation"
        ],
        "validation_error_counts": dict(sorted(Counter(verdict(row, threshold) for row in validation).items())),
        "hypothesis": {
            "id": "H09-local-difference",
            "change": "К глобальному SSIM добавить фиксированный квантиль локальных абсолютных различий в той же области товара.",
            "expected_effect": "Повышение F1 за счёт отделения структурных изменений от освещения при Recall не ниже baseline.",
            "metric": "F1 критичного изменения на validation. Защитная метрика: Recall не ниже baseline.",
            "controlled_conditions": "Те же пары, разбиение по family_id, подготовка 128x128 и правило выбора порога только на validation.",
            "limit": "Гипотеза не проверяет реальные результаты генеративного редактирования и сложные ракурсы.",
        },
    }


def write() -> dict[str, Any]:
    content = analysis()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "analysis.json").write_text(stable_json(content), encoding="utf-8")
    return content


def check() -> None:
    expected = (RESULTS / "analysis.json").read_text(encoding="utf-8")
    if stable_json(analysis()) != expected:
        raise ValueError("ЛР 8 расходится с сохранённым анализом")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check"))
    args = parser.parse_args()
    if args.command == "run":
        print(stable_json(write()), end="")
    else:
        check()
        print("ЛР 8: анализ baseline воспроизведён")


if __name__ == "__main__":
    main()
