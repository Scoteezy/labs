"""Reproduce the Lab 08 analysis using the frozen Lab 07 baseline."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from shutil import copyfile
from statistics import mean
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lab07 import baseline

RESULTS = Path(__file__).resolve().parent / "results"


def outcome(case: dict) -> str:
    hits = case["results"]
    if not hits:
        return "no_overlap" if case["known_terms"] else "empty_vector"
    if not case["metrics"]["recall"]:
        return "irrelevant_only"
    if hits[0]["relevance"] < 2:
        return "no_grade_2_at_1"
    return "grade_2_at_1"


def ranking_row(query: dict, case: dict) -> dict:
    hits = case["results"]
    return {
        "query_id": case["query_id"],
        "query": case["query"],
        "kind": case["segment"],
        "genre": query["genre"],
        "returned": " ".join(hit["poster_id"] for hit in hits),
        "grades": " ".join(str(hit["relevance"]) for hit in hits),
        "scores": " ".join(f"{hit['score']:.12f}" for hit in hits),
        "matched_terms_by_rank": " | ".join(", ".join(hit["matched_terms"]) for hit in hits),
        "known_terms": " ".join(case["known_terms"]),
        "unknown_terms": " ".join(case["unknown_terms"]),
        "relevant_qrels": " ".join(f"{pid}={grade}" for pid, grade in case["qrels"].items() if grade),
        "ndcg_at_3": f"{case['metrics']['ndcg']:.6f}",
        "recall_at_3": f"{case['metrics']['recall']:.6f}",
        "outcome": outcome(case),
    }


def summarize(dimension: str, segment: str, cases: list[dict]) -> dict:
    return {
        "dimension": dimension,
        "segment": segment,
        "queries": len(cases),
        "ndcg_at_3": f"{mean(case['metrics']['ndcg'] for case in cases):.6f}",
        "recall_at_3": f"{mean(case['metrics']['recall'] for case in cases):.6f}",
        "empty_results": sum(not case["results"] for case in cases),
        "no_relevant_hit": sum(not case["metrics"]["recall"] for case in cases),
        "grade_2_at_1": sum(outcome(case) == "grade_2_at_1" for case in cases),
    }


def manual_checks(cases: list[dict], k: int) -> list[dict]:
    by_id = {case["query_id"]: case for case in cases}
    actual, empty = by_id["V14"], by_id["V13"]
    ideal = 3 + 1 / math.log2(3)
    scenarios = [
        ("V14_actual", "V14", [hit["relevance"] for hit in actual["results"]], 1.5 / ideal, 0.5),
        ("V14_ideal", "V14", [2, 1, 0], 1.0, 1.0),
        ("V14_reversed", "V14", [1, 2, 0], (1 + 3 / math.log2(3)) / ideal, 1.0),
        ("V13_empty", "V13", [hit["relevance"] for hit in empty["results"]], 0.0, 0.0),
    ]
    checks = []
    for name, query_id, grades, ndcg, recall in scenarios:
        truth = list(by_id[query_id]["qrels"].values())
        scores = baseline.evaluate_ranking(grades, truth, k)
        expected = {"ndcg": ndcg, "recall": recall}
        passed = all(math.isclose(scores[metric], value, rel_tol=1e-12, abs_tol=1e-12)
                     for metric, value in expected.items())
        checks.append({"case": name, "query_id": query_id, "grades": grades,
                       "expected": expected, "computed": scores, "passed": passed})
    return checks


def rights_probe(settings: dict, benchmark: baseline.Benchmark, index: dict) -> dict:
    probe_id = "CONTROL_UNKNOWN"
    known_id = "P022"
    probe = {"id": probe_id, "description": benchmark.descriptions[known_id],
             "rights_status": "unknown", "split": settings["evaluation_split"]}
    clean = json.loads((baseline.DATA / "clean.json").read_bytes())
    content = baseline.json_text([*clean, probe]).encode("utf-8")
    fixture_settings = {
        **settings, "input_sha256": {**settings["input_sha256"], "clean.json": baseline.sha256(content)}
    }
    with TemporaryDirectory() as temporary:
        fixture_dir = Path(temporary)
        for filename in settings["input_sha256"]:
            copyfile(baseline.DATA / filename, fixture_dir / filename)
        (fixture_dir / "clean.json").write_bytes(content)
        with patch.object(baseline, "DATA", fixture_dir):
            guarded = baseline.load_validation(fixture_settings)
    query = next(row["text"] for row in benchmark.queries if row["id"] == "V19")
    query_vector = baseline.vectorize(baseline.tokens(query), benchmark.weights)
    unfiltered = baseline.rank(query_vector, {**index, probe_id: index[known_id]}, settings["k"])
    guarded_index = {pid: index[pid] for pid in guarded.descriptions}
    filtered = baseline.rank(query_vector, guarded_index, settings["k"])
    ids = [hit["poster_id"] for hit in filtered]
    unfiltered_ids = [hit["poster_id"] for hit in unfiltered]
    return {"probe_id": probe_id, "query_id": "V19", "status": probe["rights_status"],
            "unfiltered": unfiltered_ids, "filtered": ids,
            "passed": probe_id in unfiltered_ids and probe_id not in ids and known_id in ids}


def qrels_check(benchmark: baseline.Benchmark, posters: dict) -> dict:
    pairs = mismatches = 0
    for query in benchmark.queries:
        for poster_id, grade in benchmark.relevance[query["id"]].items():
            poster = posters[poster_id]
            expected = 0
            if poster["genre"] == query["genre"]:
                expected = 1 + (poster["style"] == query["target_style"])
            pairs += 1
            mismatches += grade != expected
    return {"pairs": pairs, "rule_mismatches": mismatches}


def reports() -> dict[str, str]:
    settings = json.loads(baseline.SETTINGS.read_bytes())
    benchmark = baseline.load_validation(settings)
    k = settings["k"]
    index = {pid: baseline.vectorize(baseline.tokens(text), benchmark.weights)
             for pid, text in benchmark.descriptions.items()}
    cases = baseline.evaluate(benchmark, index, k)

    groups = defaultdict(list)
    rankings = []
    for query, case in zip(benchmark.queries, cases):
        row = ranking_row(query, case)
        rankings.append(row)
        for key in (("type", query["kind"]), ("genre", query["genre"]), ("outcome", row["outcome"])):
            groups[key].append(case)
    summary = [summarize("total", "all", cases)]
    for dimension in ("type", "genre", "outcome"):
        summary.extend(summarize(*key, group) for key, group in groups.items() if key[0] == dimension)

    clean = json.loads((baseline.DATA / "clean.json").read_bytes())
    posters = {row["id"]: row for row in clean}
    returned = [hit["poster_id"] for case in cases for hit in case["results"]]
    unauthorized = sum(posters[pid]["rights_status"] != "demo_allowed" for pid in returned)
    no_source = sum(not posters[pid].get("source", "").strip() for pid in returned)
    qrels = qrels_check(benchmark, posters)
    manual = manual_checks(cases, k)
    guard = rights_probe(settings, benchmark, index)

    extras = []
    for name, text in (("english", "jazz minimalist"), ("out_of_catalog", "балет витраж")):
        terms = baseline.tokens(text)
        vector = baseline.vectorize(terms, benchmark.weights)
        hits = baseline.rank(vector, index, k)
        extras.append({"case": name, "query": text, "known_terms": list(vector),
                       "returned": [hit["poster_id"] for hit in hits]})
    no_positive = baseline.evaluate_ranking([], [0] * len(index), k)

    if unauthorized or no_source or qrels["rule_mismatches"] or not guard["passed"] or not all(
        check["passed"] for check in manual
    ):
        raise ValueError("Проверка расчёта, разметки или допуска не пройдена")
    if any(probe["returned"] for probe in extras) or no_positive != {"ndcg": 0, "recall": 0}:
        raise ValueError("Изменилось поведение контрольного сценария вне validation")
    evidence = {
        "baseline": {"queries": len(cases), "candidates": len(index), "k": k,
                     "returned_cards": len(returned), "unauthorized_returns": unauthorized,
                     "returns_missing_source": no_source},
        "manual_checks": manual,
        "qrels_check": qrels,
        "rights_probe": guard,
        "special_queries_outside_validation": extras,
        "no_relevant_qrels_engine_convention": no_positive,
    }
    return {"rankings.csv": baseline.csv_text(rankings), "segments.csv": baseline.csv_text(summary),
            "checks.json": baseline.json_text(evidence)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check"))
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args()
    try:
        generated = reports()
        if args.command == "run":
            args.out.mkdir(parents=True, exist_ok=True)
        for name, content in generated.items():
            path = args.out / name
            if args.command == "run":
                path.write_bytes(content.encode("utf-8"))
            elif path.read_bytes() != content.encode("utf-8"):
                raise ValueError(f"Результат отличается от сохранённого: {name}")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{len(generated)} файла анализа ЛР 8 прошли проверки.")


if __name__ == "__main__":
    main()
