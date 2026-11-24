"""Run the controlled Lab 09 TF-IDF experiment with Python 3.9+."""

import argparse
import json
import math
import platform
import unicodedata
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from shutil import copyfile
from statistics import mean
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lab07 import baseline
from lab08.analysis import outcome, ranking_row, summarize

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DECISION = "validation_decision.json"
INPUTS = baseline.DATA
ALLOWED = "demo_allowed"


def normalized_text(text: str, replacements: dict[str, str]) -> str:
    return " ".join(replacements.get(term, term) for term in baseline.tokens(text))


def fit_idf(train: list[dict], replacements: dict[str, str]) -> dict:
    # Same smoothed IDF and rounding as lab06/prepare.py.
    frequency = Counter(
        term for row in train for term in set(normalized_text(row["description"], replacements).split())
    )
    return {
        "fit_split": "train",
        "train_ids": [row["id"] for row in train],
        "weights": {
            term: round(1 + math.log((1 + len(train)) / (1 + count)), 12)
            for term, count in sorted(frequency.items())
        },
    }


def evaluate(benchmark: baseline.Benchmark, index: dict, k: int, replacements: dict) -> list[dict]:
    texts = {query["id"]: query["text"] for query in benchmark.queries}
    queries = [
        {**query, "text": normalized_text(query["text"], replacements)}
        for query in benchmark.queries
    ] if replacements else benchmark.queries
    cases = baseline.evaluate(replace(benchmark, queries=queries), index, k)
    for case in cases:
        case["query"] = texts[case["query_id"]]
    return cases


def rankings(benchmark: baseline.Benchmark, cases: list[dict]) -> str:
    return baseline.csv_text([ranking_row(query, case) for query, case in zip(benchmark.queries, cases)])


def segments(mode: str, benchmark: baseline.Benchmark, cases: list[dict]) -> list[dict]:
    groups = {("total", "all"): cases}
    for query, case in zip(benchmark.queries, cases):
        for key in (("type", query["kind"]), ("genre", query["genre"]), ("outcome", outcome(case))):
            groups.setdefault(key, []).append(case)
    return [
        {"mode": mode, **summarize(dimension, segment, group)}
        for (dimension, segment), group in groups.items()
    ]


def mean_scores(cases: list[dict]) -> dict:
    return {metric: mean(case["metrics"][metric] for case in cases) for metric in ("ndcg", "recall")}


class Experiment:
    def __init__(self):
        config_bytes = (ROOT / "config.json").read_bytes()
        lexicon_bytes = (ROOT / "lexicon.json").read_bytes()
        settings_bytes = baseline.SETTINGS.read_bytes()
        self.config = json.loads(config_bytes)
        self.settings = json.loads(settings_bytes)
        lexicon = json.loads(lexicon_bytes)
        for key in ("dataset_version", "fit_split", "k"):
            if self.config[key] != self.settings[key]:
                raise ValueError(f"Параметр {key} отличается от baseline")
        if self.config["selection_split"] != self.settings["evaluation_split"]:
            raise ValueError("Выборка для решения отличается от ЛР 7")
        if self.config["lexicon_version"] != lexicon["version"]:
            raise ValueError("Версия словаря отличается от конфигурации")

        self.replacements = {
            form: canonical for canonical, forms in lexicon["genre_forms"].items() for form in forms
        }
        self.k = self.config["k"]
        self.clean = json.loads((INPUTS / "clean.json").read_bytes())
        self.posters = {row["id"]: row for row in self.clean}
        train = [row for row in self.clean if row["split"] == self.config["fit_split"]
                 and row["rights_status"] == ALLOWED]
        self.base_idf = json.loads((INPUTS / "idf.json").read_bytes())
        if fit_idf(train, {}) != self.base_idf:
            raise ValueError("Повторный расчёт IDF baseline должен совпадать с ЛР 6")
        self.candidate_idf = fit_idf(train, self.replacements)
        self.idf_text = baseline.json_text(self.candidate_idf)
        self.fingerprints = {
            "config_sha256": baseline.sha256(config_bytes),
            "lexicon_sha256": baseline.sha256(lexicon_bytes),
            "baseline_settings_sha256": baseline.sha256(settings_bytes),
            "baseline_idf_sha256": self.settings["input_sha256"]["idf.json"],
            "candidate_idf_sha256": baseline.sha256(self.idf_text.encode("utf-8")),
        }

    def conditions(self, split: str) -> dict:
        return {**self.settings, "evaluation_split": split}

    def evaluate_mode(self, benchmark: baseline.Benchmark, candidate: bool) -> tuple[dict, list[dict]]:
        replacements = self.replacements if candidate else {}
        weights = self.candidate_idf["weights"] if candidate else self.base_idf["weights"]
        benchmark = replace(benchmark, weights=weights)
        index = {
            poster_id: baseline.vectorize(baseline.tokens(normalized_text(text, replacements)), weights)
            for poster_id, text in benchmark.descriptions.items()
        }
        return index, evaluate(benchmark, index, self.k, replacements)

    def audit_returns(self, cases: list[dict]) -> dict:
        returned = [self.posters[hit["poster_id"]] for case in cases for hit in case["results"]]
        return {
            "returned_cards": len(returned),
            "unauthorized_returns": sum(row["rights_status"] != ALLOWED for row in returned),
            "returns_missing_source": sum(not row["source"].strip() for row in returned),
        }

    def rights_probe(self, benchmark: baseline.Benchmark, settings: dict, indexes: dict) -> dict:
        probe_id, allowed_id, query_id = "CONTROL_UNKNOWN", "P022", "V19"
        probe = {**self.posters[allowed_id], "id": probe_id, "rights_status": "unknown"}
        content = baseline.json_text([*self.clean, probe]).encode("utf-8")
        fixture_settings = {
            **settings, "input_sha256": {**settings["input_sha256"], "clean.json": baseline.sha256(content)},
        }
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            for filename in settings["input_sha256"]:
                copyfile(INPUTS / filename, fixture / filename)
            (fixture / "clean.json").write_bytes(content)
            with patch.object(baseline, "DATA", fixture):
                guarded = baseline.load_validation(fixture_settings)

        query = next(row["text"] for row in benchmark.queries if row["id"] == query_id)
        probes = {}
        for mode, index, replacements, weights in (
            ("baseline", indexes["baseline"], {}, self.base_idf["weights"]),
            ("candidate", indexes["candidate"], self.replacements, self.candidate_idf["weights"]),
        ):
            vector = baseline.vectorize(normalized_text(query, replacements).split(), weights)
            unfiltered = {**index, probe_id: index[allowed_id]}
            filtered = {poster_id: index[poster_id] for poster_id in guarded.descriptions}
            before = [hit["poster_id"] for hit in baseline.rank(vector, unfiltered, self.k)]
            after = [hit["poster_id"] for hit in baseline.rank(vector, filtered, self.k)]
            probes[mode] = {
                "without_filter": before,
                "with_filter": after,
                "passed": probe_id in before and probe_id not in after and allowed_id in after,
            }
        return {"unknown_id": probe_id, "allowed_id": allowed_id, "query_id": query_id, **probes}

    def extra_queries(self, indexes: dict) -> list[dict]:
        rows = []
        for query in ("jazz minimalist", "балет витраж"):
            row = {"query": query}
            for mode, replacements, weights in (
                ("baseline", {}, self.base_idf["weights"]),
                ("candidate", self.replacements, self.candidate_idf["weights"]),
            ):
                vector = baseline.vectorize(normalized_text(query, replacements).split(), weights)
                row[mode] = [hit["poster_id"] for hit in baseline.rank(vector, indexes[mode], self.k)]
            rows.append(row)
        return rows

    def validation(self) -> dict[str, str]:
        settings = self.conditions(self.config["selection_split"])
        benchmark = baseline.load_validation(settings)
        base_index, base = self.evaluate_mode(benchmark, candidate=False)
        candidate_index, candidate = self.evaluate_mode(benchmark, candidate=True)
        for name, content in baseline.reports(base, settings, self.fingerprints["baseline_settings_sha256"]).items():
            if (baseline.RESULTS / name).read_bytes() != content.encode("utf-8"):
                raise ValueError(f"Результат baseline отличается от ЛР 7: {name}")

        indexes = {"baseline": base_index, "candidate": candidate_index}
        base_audit = self.audit_returns(base)
        candidate_audit = self.audit_returns(candidate)
        probe = self.rights_probe(benchmark, settings, indexes)
        base_scores, candidate_scores = mean_scores(base), mean_scores(candidate)
        gain = candidate_scores["ndcg"] - base_scores["ndcg"]
        recall_floor = float(Fraction(self.config["minimum_recall"]))
        limits = {
            "ndcg_gain": gain >= self.config["minimum_ndcg_gain"],
            "recall": candidate_scores["recall"] >= max(base_scores["recall"], recall_floor),
            "rights": all(
                audit["unauthorized_returns"] <= self.config["maximum_unauthorized_returns"]
                and probe[mode]["passed"]
                for mode, audit in (("baseline", base_audit), ("candidate", candidate_audit))
            ),
            "alpha_ndcg": candidate_scores["ndcg"] >= self.config["alpha_minimum_ndcg"],
        }
        h1 = limits["ndcg_gain"] and limits["recall"] and limits["rights"]
        decision = {
            **self.fingerprints,
            "experiment": self.config["experiment"],
            "split": self.config["selection_split"],
            "baseline": base_scores,
            "candidate": candidate_scores,
            "absolute_ndcg_gain": gain,
            "criteria_met": limits,
            "h1_supported": h1,
            "alpha_decision": "include" if h1 and limits["alpha_ndcg"] else "do_not_include",
            "selected_for_test": self.config["candidate"] if h1 else None,
        }
        summary = segments("baseline", benchmark, base) + segments("candidate", benchmark, candidate)
        checks = {
            "queries": len(benchmark.queries),
            "candidates": len(benchmark.descriptions),
            "qrels_pairs": sum(map(len, benchmark.relevance.values())),
            "matches_lab07_reports_bytewise": True,
            "baseline": base_audit,
            "candidate": candidate_audit,
            "rights_probe": probe,
            "probes_outside_validation": self.extra_queries(indexes),
        }
        return {
            "candidate_idf.json": self.idf_text,
            "validation_baseline.csv": rankings(benchmark, base),
            "validation_candidate.csv": rankings(benchmark, candidate),
            "validation_segments.csv": baseline.csv_text(summary),
            "validation_checks.json": baseline.json_text(checks),
            DECISION: baseline.json_text(decision),
        }

    def test(self, decision_bytes: bytes) -> dict[str, str]:
        decision = json.loads(decision_bytes)
        if any(decision[key] != value for key, value in self.fingerprints.items()):
            raise ValueError("Текущие параметры или IDF отличаются от решения на validation")
        if (decision["experiment"] != self.config["experiment"]
                or decision["split"] != self.config["selection_split"]
                or not decision["h1_supported"]
                or decision["selected_for_test"] != self.config["candidate"]):
            raise ValueError("Кандидат должен быть выбран на validation до запуска test")
        settings = self.conditions(self.config["test_split"])
        benchmark = baseline.load_validation(settings)
        _, cases = self.evaluate_mode(benchmark, candidate=True)
        audit = self.audit_returns(cases)
        summary = {
            "split": self.config["test_split"],
            "mode": self.config["candidate"],
            "validation_decision_sha256": baseline.sha256(decision_bytes),
            "queries": len(benchmark.queries),
            "candidates": len(benchmark.descriptions),
            **mean_scores(cases),
            **audit,
        }
        return {
            "test_candidate.csv": rankings(benchmark, cases),
            "test_segments.csv": baseline.csv_text(segments("candidate", benchmark, cases)),
            "test_summary.json": baseline.json_text(summary),
        }


def write_reports(directory: Path, reports: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in reports.items():
        (directory / filename).write_bytes(content.encode("utf-8"))


def verify_reports(directory: Path, reports: dict[str, str]) -> None:
    for filename, content in reports.items():
        if (directory / filename).read_bytes() != content.encode("utf-8"):
            raise ValueError(f"Результат отличается от сохранённого: {filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validation", "test", "check"))
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args()
    try:
        experiment = Experiment()
        if args.command == "validation":
            reports = experiment.validation()
            environment = {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "system": platform.system(),
                "architecture": platform.machine(),
                "unicode_version": unicodedata.unidata_version,
                "dependencies": "Python standard library",
            }
            write_reports(args.out, {**reports, "environment.json": baseline.json_text(environment)})
            print(reports[DECISION], end="")
        elif args.command == "test":
            reports = experiment.test((args.out / DECISION).read_bytes())
            write_reports(args.out, reports)
            print(reports["test_summary.json"], end="")
        else:
            reports = experiment.validation()
            verify_reports(args.out, reports)
            decision_bytes = (args.out / DECISION).read_bytes()
            if json.loads(decision_bytes)["selected_for_test"]:
                test_reports = experiment.test(decision_bytes)
                verify_reports(args.out, test_reports)
                reports.update(test_reports)
            print(f"Совпали побайтно {len(reports)} файлов результатов.")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
