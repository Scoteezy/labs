"""Measure warm-query latency for the fixed Lab 09 validation benchmark."""

import argparse
import math
import platform
import time
import unicodedata
from pathlib import Path

from lab07 import baseline
from lab09.experiment import Experiment, normalized_text


MODES = ("baseline", "candidate")


def percentile_ns(samples: list[int], proportion: float) -> int:
    """Return the nearest-rank percentile without adding a dependency."""
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * proportion) - 1]


def milliseconds(value_ns: int) -> float:
    return round(value_ns / 1_000_000, 6)


def build_modes(experiment: Experiment, benchmark: baseline.Benchmark) -> dict:
    """Build each index before timing any query operation."""
    modes = {}
    for name, candidate in (("baseline", False), ("candidate", True)):
        index, cases = experiment.evaluate_mode(benchmark, candidate=candidate)
        modes[name] = {
            "index": index,
            "replacements": experiment.replacements if candidate else {},
            "weights": experiment.candidate_idf["weights"] if candidate else experiment.base_idf["weights"],
            "expected": [
                [{"poster_id": hit["poster_id"], "score": hit["score"]} for hit in case["results"]]
                for case in cases
            ],
        }
    return modes


def rank_query(query: str, mode: dict, k: int) -> list[dict]:
    terms = normalized_text(query, mode["replacements"]).split()
    vector = baseline.vectorize(terms, mode["weights"])
    return baseline.rank(vector, mode["index"], k)


def verify_rankings(queries: list[dict], modes: dict, k: int) -> None:
    for name in MODES:
        for query, expected in zip(queries, modes[name]["expected"]):
            actual = rank_query(query["text"], modes[name], k)
            if actual != expected:
                raise ValueError(f"Ранжирование {name} расходится с результатом ЛР 9")


def run_warmups(queries: list[dict], modes: dict, k: int, cycles: int) -> None:
    for cycle in range(cycles):
        order = MODES if cycle % 2 == 0 else tuple(reversed(MODES))
        for name in order:
            for query in queries:
                rank_query(query["text"], modes[name], k)


def measure(queries: list[dict], modes: dict, k: int, cycles: int) -> dict[str, list[int]]:
    samples = {name: [] for name in MODES}
    for cycle in range(cycles):
        order = MODES if cycle % 2 == 0 else tuple(reversed(MODES))
        for name in order:
            for query in queries:
                start = time.perf_counter_ns()
                rank_query(query["text"], modes[name], k)
                samples[name].append(time.perf_counter_ns() - start)
    return samples


def report(samples: dict[str, list[int]], experiment: Experiment, benchmark: baseline.Benchmark,
           warmup_cycles: int, cycles: int) -> dict:
    clock = time.get_clock_info("perf_counter")
    mode_names = {
        "baseline": experiment.config["baseline"],
        "candidate": experiment.config["candidate"],
    }
    return {
        "experiment": "LR10-LATENCY-01",
        "purpose": "Задержка обработки запроса и top-3 ранжирования после загрузки индекса на validation ЛР 9.",
        "dataset_version": experiment.config["dataset_version"],
        "split": experiment.config["selection_split"],
        "queries": len(benchmark.queries),
        "permitted_candidates": len(benchmark.descriptions),
        "k": experiment.k,
        "measurement": {
            "unit": "milliseconds",
            "timer": "time.perf_counter_ns",
            "timer_resolution_seconds": clock.resolution,
            "warmup_cycles_per_mode": warmup_cycles,
            "measurement_cycles_per_mode": cycles,
            "samples_per_mode": len(next(iter(samples.values()))),
            "interleaving": "Порядок режимов меняется на каждом цикле. Запросы идут в фиксированном порядке validation.",
            "included": "Нормализация текста, векторизация запроса и косинусное top-3 ранжирование.",
            "excluded": "Проверка допуска при построении индекса, чтение файлов, запуск процесса, HTTP и сериализация.",
            "ranking_check": "До замера выдачи сверяются с повторно рассчитанными выдачами ЛР 9.",
        },
        "modes": {
            name: {
                "implementation": mode_names[name],
                "p50_ms": milliseconds(percentile_ns(values, 0.50)),
                "p95_ms": milliseconds(percentile_ns(values, 0.95)),
                "minimum_ms": milliseconds(min(values)),
                "maximum_ms": milliseconds(max(values)),
            }
            for name, values in samples.items()
        },
        "environment": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "system": platform.system(),
            "architecture": platform.machine(),
            "unicode_version": unicodedata.unidata_version,
            "dependencies": "Python standard library",
        },
        "note": "Временные значения зависят от машины и фоновой нагрузки.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optionally save the report to this file")
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--warmup-cycles", type=int, default=20)
    args = parser.parse_args()
    if args.cycles < 1 or args.warmup_cycles < 0:
        parser.error("Число циклов должно быть положительным, а число прогревов неотрицательным")

    try:
        experiment = Experiment()
        benchmark = baseline.load_validation(experiment.conditions(experiment.config["selection_split"]))
        modes = build_modes(experiment, benchmark)
        verify_rankings(benchmark.queries, modes, experiment.k)
        run_warmups(benchmark.queries, modes, experiment.k, args.warmup_cycles)
        output = report(
            measure(benchmark.queries, modes, experiment.k, args.cycles),
            experiment,
            benchmark,
            args.warmup_cycles,
            args.cycles,
        )
        content = baseline.json_text(output)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(content, encoding="utf-8")
        print(content, end="")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
