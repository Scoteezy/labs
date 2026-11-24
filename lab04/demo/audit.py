"""Verify the Lab 4 poster fixture after `python3 demo/project.py run`.

The audit deliberately checks data and split integrity, not retrieval quality.
It uses only the Python standard library.
"""
from __future__ import annotations

import csv
import hashlib
import json
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo" / "data"
RESULTS = ROOT / "demo" / "results"


def load_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    raw = load_json("raw.json")
    clean = load_json("clean.json")
    queries = load_json("queries.json")
    expected = {
        "raw_records": 42,
        "clean_records": 36,
        "svg_files": 36,
        "unknown_rights_in_clean": 0,
        "empty_descriptions_in_clean": 0,
        "duplicate_hashes_in_clean": 0,
        "author_overlap_between_splits": 0,
        "series_overlap_between_splits": 0,
        "image_path_hash_mismatches": 0,
        "svg_dimension_or_parse_errors": 0,
    }
    split_names = ("train", "validation", "test")
    authors = {name: {r["author"] for r in clean if r["split"] == name} for name in split_names}
    series = {name: {r["series"] for r in clean if r["split"] == name} for name in split_names}
    author_overlap = len((authors["train"] & authors["validation"]) |
                         (authors["train"] & authors["test"]) |
                         (authors["validation"] & authors["test"]))
    series_overlap = len((series["train"] & series["validation"]) |
                         (series["train"] & series["test"]) |
                         (series["validation"] & series["test"]))
    mismatches = []
    malformed = []
    layout_hashes = {name: set() for name in split_names}
    for record in clean:
        svg_path = ROOT / record["image"]
        if not svg_path.is_file():
            mismatches.append(record["id"])
            continue
        svg_bytes = svg_path.read_bytes()
        if hashlib.sha256(svg_bytes).hexdigest() != record["sha256"]:
            mismatches.append(record["id"])
        try:
            svg = ElementTree.fromstring(svg_bytes)
            if (int(svg.attrib["width"]), int(svg.attrib["height"])) != (record["width"], record["height"]):
                malformed.append(record["id"])
        except (ElementTree.ParseError, KeyError, ValueError):
            malformed.append(record["id"])
        normalized = svg_bytes.replace(record["id"].encode(), b"P000", 1)
        layout_hashes[record["split"]].add(hashlib.sha256(normalized).hexdigest())
    actual = {
        "raw_records": len(raw),
        "clean_records": len(clean),
        "svg_files": len(list((DATA / "posters").glob("*.svg"))),
        "unknown_rights_in_clean": sum(r["rights_status"] != "demo_allowed" for r in clean),
        "empty_descriptions_in_clean": sum(not r["description"].strip() for r in clean),
        "duplicate_hashes_in_clean": len(clean) - len({r["sha256"] for r in clean}),
        "author_overlap_between_splits": author_overlap,
        "series_overlap_between_splits": series_overlap,
        "image_path_hash_mismatches": len(mismatches),
        "svg_dimension_or_parse_errors": len(malformed),
    }
    overlap = []
    for left, right in combinations(split_names, 2):
        left_cards = [row for row in clean if row["split"] == left]
        right_cards = [row for row in clean if row["split"] == right]
        left_queries = {query["text"] for query in queries if query["split"] == left}
        right_queries = {query["text"] for query in queries if query["split"] == right}
        pair = {"split_a": left, "split_b": right}
        for field in ("id", "author", "series", "sha256", "description"):
            pair[field] = len({row[field] for row in left_cards} & {row[field] for row in right_cards})
        pair["svg_templates"] = len(layout_hashes[left] & layout_hashes[right])
        pair["query_texts"] = len(left_queries & right_queries)
        overlap.append(pair)
    rows = [{"check": key, "actual": actual[key], "expected": expected[key],
             "passed": actual[key] == expected[key]} for key in expected]
    RESULTS.mkdir(exist_ok=True)
    write_csv(RESULTS / "reproducibility_audit.csv", rows)
    write_csv(RESULTS / "split_overlap.csv", overlap)
    summary = {
        "passed": all(row["passed"] for row in rows),
        "raw_fixture_policy": {
            "duplicate_records": ["D001", "D002", "D003"],
            "unknown_rights_records": ["X001", "X002"],
            "empty_description_record": "X003",
        },
        "split_groups": {name: {"authors": sorted(authors[name]), "series": sorted(series[name])}
                         for name in split_names},
        "hash_mismatch_ids": mismatches,
        "svg_dimension_or_parse_error_ids": malformed,
        "split_overlap": overlap,
    }
    (RESULTS / "reproducibility_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
