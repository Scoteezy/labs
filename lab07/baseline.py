"""TF-IDF baseline for the fixed validation split of Lab 06."""

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "lab06" / "data"
RESULTS = ROOT / "results"
SETTINGS = ROOT / "settings.json"


@dataclass
class Benchmark:
    weights: dict[str, float]
    descriptions: dict[str, str]
    queries: list[dict]
    relevance: dict[str, dict[str, int]]


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_validation(settings: dict) -> Benchmark:
    contents = {}
    for filename, digest in settings["input_sha256"].items():
        content = (DATA / filename).read_bytes()
        if sha256(content) != digest:
            raise ValueError(f"Контрольная сумма ЛР 6 не совпала для {filename}")
        contents[filename] = content

    fit_split = settings["fit_split"]
    evaluation_split = settings["evaluation_split"]
    splits = json.loads(contents["split.json"])
    idf = json.loads(contents["idf.json"])
    if idf["fit_split"] != fit_split or idf["train_ids"] != splits[fit_split]["poster_ids"]:
        raise ValueError("Разбиение обучения IDF расходится с зафиксированным split")

    selected = splits[evaluation_split]
    descriptions = {
        row["id"]: row["description"]
        for row in json.loads(contents["clean.json"])
        if row["split"] == evaluation_split and row["rights_status"] == "demo_allowed"
    }
    by_query = {
        row["id"]: row
        for row in json.loads(contents["queries.json"])
        if row["split"] == evaluation_split
    }
    if descriptions.keys() != set(selected["poster_ids"]):
        raise ValueError("Набор допущенных карточек расходится с зафиксированным split")
    if by_query.keys() != set(selected["query_ids"]):
        raise ValueError("Набор запросов расходится с зафиксированным split")

    relevance = {query_id: {} for query_id in selected["query_ids"]}
    for row in csv.DictReader(io.StringIO(contents["qrels.csv"].decode("utf-8"))):
        if row["split"] != evaluation_split:
            continue
        grades = relevance[row["query_id"]]
        poster_id, grade = row["poster_id"], int(row["relevance"])
        if poster_id in grades or grade not in (0, 1, 2):
            raise ValueError(f"Некорректная оценка пары {row['query_id']}/{poster_id}")
        grades[poster_id] = grade
    if any(grades.keys() != descriptions.keys() for grades in relevance.values()):
        raise ValueError("Разметка должна покрывать все пары validation")

    queries = [by_query[query_id] for query_id in selected["query_ids"]]
    return Benchmark(idf["weights"], descriptions, queries, relevance)


def tokens(text: str) -> list[str]:
    """Match the frozen Lab 06 tokenizer used to fit IDF."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[a-zа-яё0-9]+", normalized)


def vectorize(terms: list[str], weights: dict[str, float]) -> dict[str, float]:
    counts = Counter(terms)
    values = {term: counts[term] * weights[term] for term in sorted(counts) if term in weights}
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {term: round(value / norm, 12) for term, value in values.items()} if norm else {}


def rank(query: dict[str, float], index: dict[str, dict[str, float]], k: int) -> list[dict]:
    if not query:
        return []
    hits = []
    for poster_id, vector in index.items():
        score = round(math.fsum(value * vector.get(term, 0.0) for term, value in query.items()), 12)
        if score > 0:
            hits.append({"poster_id": poster_id, "score": score})
    return sorted(hits, key=lambda hit: (-hit["score"], hit["poster_id"]))[:k]


def dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(position + 2) for position, grade in enumerate(grades[:k]))


def evaluate_ranking(returned: list[int], truth: list[int], k: int) -> dict:
    ideal_gain = dcg(sorted(truth, reverse=True), k)
    relevant = sum(grade > 0 for grade in truth)
    return {
        "ndcg": dcg(returned, k) / ideal_gain if ideal_gain else 0.0,
        "recall": sum(grade > 0 for grade in returned[:k]) / relevant if relevant else 0.0,
    }


def evaluate(benchmark: Benchmark, index: dict, k: int) -> list[dict]:
    cases = []
    for query in benchmark.queries:
        terms = tokens(query["text"])
        query_vector = vectorize(terms, benchmark.weights)
        grades = benchmark.relevance[query["id"]]
        hits = rank(query_vector, index, k)
        results = [
            {
                **hit,
                "relevance": grades[hit["poster_id"]],
                "matched_terms": sorted(query_vector.keys() & index[hit["poster_id"]].keys()),
            }
            for hit in hits
        ]
        cases.append({
            "query_id": query["id"],
            "query": query["text"],
            "segment": query["kind"],
            "known_terms": list(dict.fromkeys(term for term in terms if term in benchmark.weights)),
            "unknown_terms": list(dict.fromkeys(term for term in terms if term not in benchmark.weights)),
            "results": results,
            "qrels": grades,
            "metrics": evaluate_ranking([hit["relevance"] for hit in results], list(grades.values()), k),
        })
    return cases


def csv_text(rows: list[dict]) -> str:
    with io.StringIO(newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def reports(cases: list[dict], settings: dict, settings_hash: str) -> dict[str, str]:
    rows = []
    for case in cases:
        rows.append({
            "query_id": case["query_id"],
            "query": case["query"],
            "segment": case["segment"],
            "ndcg": f"{case['metrics']['ndcg']:.6f}",
            "recall": f"{case['metrics']['recall']:.6f}",
            "returned": " ".join(hit["poster_id"] for hit in case["results"]),
            "grades": " ".join(str(hit["relevance"]) for hit in case["results"]),
        })

    groups = {"all": cases}
    for segment in sorted({case["segment"] for case in cases}):
        groups[segment] = [case for case in cases if case["segment"] == segment]
    summary = [
        {
            "segment": segment,
            "queries": len(group),
            "ndcg": f"{mean(case['metrics']['ndcg'] for case in group):.6f}",
            "recall": f"{mean(case['metrics']['recall'] for case in group):.6f}",
            "empty_results": sum(not case["results"] for case in group),
        }
        for segment, group in groups.items()
    ]
    details = {
        "dataset_version": settings["dataset_version"],
        "split": settings["evaluation_split"],
        "k": settings["k"],
        "settings_sha256": settings_hash,
        "cases": cases,
    }
    return {
        "validation_baseline.csv": csv_text(rows),
        "validation_baseline_summary.csv": csv_text(summary),
        "validation_baseline_detail.json": json_text(details),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Calculate validation reports")
    run.add_argument("--out", type=Path, default=RESULTS)
    commands.add_parser("check", help="Compare recalculated validation reports with the saved files")
    search = commands.add_parser("search", help="Rank validation posters for a supplied text")
    search.add_argument("--query", required=True)
    args = parser.parse_args()

    raw_settings = SETTINGS.read_bytes()
    settings = json.loads(raw_settings)
    try:
        benchmark = load_validation(settings)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    k = settings["k"]
    index = {
        poster_id: vectorize(tokens(description), benchmark.weights)
        for poster_id, description in benchmark.descriptions.items()
    }
    if args.command == "search":
        query = vectorize(tokens(args.query), benchmark.weights)
        print(json_text(rank(query, index, k)), end="")
        return

    output = reports(evaluate(benchmark, index, k), settings, sha256(raw_settings))
    if args.command == "check":
        for name, content in output.items():
            path = RESULTS / name
            if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
                parser.exit(1, f"Результат отличается от сохранённого: {name}\n")
        print("Все три отчёта validation совпадают побайтно.")
        return

    environment = {
        "implementation": platform.python_implementation(),
        "python": platform.python_version(),
        "system": platform.system(),
        "architecture": platform.machine(),
        "unicode_version": unicodedata.unidata_version,
        "dependencies": "Python standard library",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in {**output, "environment.json": json_text(environment)}.items():
        (args.out / name).write_bytes(content.encode("utf-8"))
    print(output["validation_baseline_summary.csv"], end="")


if __name__ == "__main__":
    main()
