"""Measure local preparation and selected SSIM scoring on validation pairs."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from pathlib import Path

from lab07 import baseline
from lab09 import experiment


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
DECISION_PATH = REPOSITORY / "lab09" / "results" / "decision.json"
PAIRS_PATH = REPOSITORY / "lab06" / "data" / "prepared.json"


def percentile(samples: list[int], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * fraction) - 1] / 1_000_000


def selected_score(reference, candidate, mode: str) -> float:
    if mode == "baseline":
        return baseline.baseline_score(reference, candidate)
    if mode == "candidate":
        return experiment.candidate_score(reference, candidate)
    raise ValueError("Неизвестный выбранный режим")


def run(cycles: int = 20) -> dict:
    experiment.check()
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
    pairs = json.loads(PAIRS_PATH.read_text(encoding="utf-8"))["pairs"]
    validation = [row for row in pairs if row["split"] == "validation"]
    if not validation:
        raise ValueError("Нет validation-пар для замера")

    for row in validation:
        selected_score(*baseline.prepared_images(row), decision["mode"])
    durations = []
    for _ in range(cycles):
        for row in validation:
            started = time.perf_counter_ns()
            selected_score(*baseline.prepared_images(row), decision["mode"])
            durations.append(time.perf_counter_ns() - started)

    return {
        "experiment": "LR10-LATENCY-01",
        "purpose": "Время подготовки двух областей товара из файлов и оценки выбранной модели.",
        "mode": decision["mode"],
        "model_version": decision["selected_model_version"],
        "pairs_per_cycle": len(validation),
        "cycles": cycles,
        "samples": len(durations),
        "unit": "milliseconds",
        "p50_ms": round(percentile(durations, 0.5), 6),
        "p95_ms": round(percentile(durations, 0.95), 6),
        "minimum_ms": round(min(durations) / 1_000_000, 6),
        "maximum_ms": round(max(durations) / 1_000_000, 6),
        "mean_ms": round(statistics.fmean(durations) / 1_000_000, 6),
        "included": "Pillow open, проверка областей, crop, resize, grayscale и score.",
        "excluded": "Чтение JSON, запуск процесса, HTTP, base64-декодирование и решение дизайнера.",
        "environment": {
            "python": platform.python_version(),
            "system": platform.platform(),
        },
        "note": "Значения зависят от машины и фоновой нагрузки.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--out", type=Path, help="Optionally save a new measurement")
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("cycles must be positive")
    result = run(args.cycles)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
