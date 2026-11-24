"""Build and verify the versioned Lab 06 poster dataset. Python 3.9+."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import tempfile
import unicodedata
from collections import Counter
from itertools import combinations
from pathlib import Path

from artwork import DETAILED, MINIMAL, MIN_RADIUS, REVIEW, SIZE
from artwork import geometry_sha256, inspect_svg, render_poster, style_for_count

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "lab05" / "data"
INPUTS = ROOT / "inputs"
DATA = ROOT / "data"
SPLITS = ("train", "validation", "test")
GENRES = ("джаз", "театр", "кино", "выставка", "электроника", "фестиваль")
LABELS = (MINIMAL, DETAILED, REVIEW)
JOURNAL_FIELDS = ("poster_id", "visual_label", "svg_label", "final_label", "reason", "instruction_version")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, payload) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def write_csv(path: Path, fields, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def unique_index(rows: list[dict], field: str) -> dict:
    lookup = {row[field]: row for row in rows}
    if len(lookup) != len(rows):
        raise ValueError(f"Повторяющееся значение поля {field}")
    return lookup


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё0-9]+", unicodedata.normalize("NFKC", text).casefold())


def clean_source(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    by_id = unique_index(rows, "id")
    clean, exclusions = [], []
    seen_hashes = set()
    for row in sorted(rows, key=lambda row: row["id"]):
        reason = None
        if row["rights_status"] != "demo_allowed":
            reason = "unknown_rights"
        elif not row["description"].strip():
            reason = "empty_description"
        if reason:
            exclusions.append({"id": row["id"], "reason": reason})
            continue
        name = Path(row["image"]).name
        content = (SOURCE / "posters" / name).read_bytes()
        if sha256(content) != row["sha256"]:
            raise ValueError(f"SHA-256 исходного SVG не совпадает для {row['id']}")
        # The original poster owns any aliases of its source path.
        target_id = Path(name).stem
        if target_id != row["id"]:
            original = by_id.get(target_id)
            if original is None or original["sha256"] != row["sha256"]:
                raise ValueError(f"Не найдена исходная карточка для {row['id']}")
            if original["rights_status"] != "demo_allowed" or not original["description"].strip():
                raise ValueError(f"Исходная карточка для {row['id']} исключена")
            exclusions.append({"id": row["id"], "reason": "duplicate_image"})
        elif row["sha256"] in seen_hashes:
            exclusions.append({"id": row["id"], "reason": "duplicate_image"})
        else:
            seen_hashes.add(row["sha256"])
            clean.append(row)
    return clean, exclusions


def make_posters(source_rows: list[dict], policy: dict) -> list[dict]:
    groups = unique_index(policy["groups"], "author")
    for field in ("series", "family"):
        unique_index(policy["groups"], field)
    if set(group["split"] for group in groups.values()) != set(SPLITS):
        raise ValueError("Зафиксированы не все выборки")
    posters = []
    for row in source_rows:
        group = groups[row["author"]]
        if row["series"] != group["series"]:
            raise ValueError(f"Серия карточки {row['id']} не соответствует зафиксированной группе")
        family_index = int(group["family"][1:]) - 1
        content = render_poster(GENRES.index(row["genre"]), family_index)
        posters.append({
            "id": row["id"], "genre": row["genre"], "author": row["author"],
            "series": group["series"], "family": group["family"], "split": group["split"],
            "rights_status": row["rights_status"], "synthetic": True,
            "source": "ЛР 5 v1.0 → ЛР 6 v2.0",
            "source_sha256": row["sha256"], "svg": content,
        })
    return posters


def pilot_items(posters: list[dict], policy: dict) -> dict:
    seed = policy["pilot_order_seed"]
    ordered = sorted(
        (poster for poster in posters if poster["split"] == "train"),
        key=lambda poster: sha256(f"{seed}:{poster['id']}".encode("utf-8")),
    )
    return {f"B{index:02d}": poster for index, poster in enumerate(ordered, 1)}


def write_pilot_board(out: Path, pilot: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for blind_id, poster in pilot.items():
        (out / f"{blind_id}.svg").write_bytes(poster["svg"])
    cards = "\n".join(
        f'<article><h2>{blind_id}</h2><img src="{blind_id}.svg" width="288" height="288" '
        f'alt="Макет {blind_id}"><p><i></i> Эталон 32 единицы SVG</p></article>'
        for blind_id in pilot
    )
    page = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Визуальная разметка афиш</title>
<style>
body {{ font: 16px system-ui, sans-serif; margin: 2rem; color: #17253a; }}
main {{ display: grid; grid-template-columns: repeat(auto-fit, 306px); gap: 18px; }}
article {{ border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; }}
h2, p {{ margin: 6px; }}
i {{ display: inline-block; width: {2 * MIN_RADIUS * 288 / SIZE}px; aspect-ratio: 1;
     border-radius: 100%; background: currentColor; vertical-align: middle; }}
</style>
<h1>Визуальная разметка афиш</h1>
<p>Посчитайте крупные круги по инструкции 1.0. Используйте код над карточкой.</p>
<main>{cards}</main>
</html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


def fit_idf(clean: list[dict]) -> dict:
    train = [row for row in clean if row["split"] == "train"]
    frequency = Counter(term for row in train for term in set(tokens(row["description"])))
    return {
        "fit_split": "train",
        "train_ids": [row["id"] for row in train],
        "weights": {
            term: round(math.log((1 + len(train)) / (1 + count)) + 1, 12)
            for term, count in sorted(frequency.items())
        },
    }


def vector(text: str, idf: dict) -> dict:
    weights = idf["weights"]
    counts = Counter(tokens(text))
    values = {term: counts[term] * weights[term] for term in sorted(counts) if term in weights}
    norm = math.sqrt(sum(weight * weight for weight in values.values()))
    return {term: round(value / norm, 12) for term, value in values.items()} if norm else {}


def pilot_results(pilot: dict, structural: dict, version: str) -> tuple[list[dict], list[dict], dict]:
    visual = unique_index(read_csv(INPUTS / "visual_pilot.csv"), "blind_id")
    decisions = unique_index(read_csv(INPUTS / "adjudication.csv"), "poster_id")
    if set(pilot) != set(visual):
        raise ValueError("Первичные ответы должны покрывать все коды пилота")

    results, journal = [], []
    for blind_id, poster in pilot.items():
        poster_id = poster["id"]
        row = visual[blind_id]
        initial = row["label"]
        count = int(row["circle_count"]) if row["circle_count"] else None
        if (
            initial not in LABELS
            or row["confidence"] not in {"высокая", "средняя", "низкая"}
            or not row["comment"].strip()
            or (initial == REVIEW and row["confidence"] != "низкая")
            or (count is not None and count < 0)
            or (initial != REVIEW and (count is None or style_for_count(count) != initial))
        ):
            raise ValueError(f"Некорректная первичная метка {blind_id}")
        svg_count, svg_label, svg_evidence = structural[poster_id]
        mismatch = initial != svg_label or count != svg_count or initial == REVIEW
        final = svg_label
        if mismatch:
            decision = decisions.pop(poster_id, None)
            if decision is None:
                raise ValueError(f"Требуется решение по карточке {poster_id}")
            if (
                (decision["visual_label"], decision["svg_label"]) != (initial, svg_label)
                or decision["final_label"] not in LABELS
                or decision["instruction_version"] != version
                or not decision["reason"].strip()
            ):
                raise ValueError(f"Некорректная запись ревизии {poster_id}")
            final = decision["final_label"]
            journal.append(decision)
        results.append({
            "blind_id": blind_id, "poster_id": poster_id,
            "visual_count": count, "visual_label": initial, "confidence": row["confidence"],
            "visual_comment": row["comment"], "svg_count": svg_count, "svg_label": svg_label,
            "svg_evidence": svg_evidence, "final_label": final, "reviewed": mismatch,
        })

    if decisions:
        raise ValueError(f"Лишние записи журнала ревизии: {sorted(decisions)}")
    count_matches = sum(row["visual_count"] == row["svg_count"] for row in results)
    label_matches = sum(row["visual_label"] == row["svg_label"] for row in results)
    stats = {
        "method": "Визуальная разметка Codex и проверка геометрии SVG",
        "split": "train",
        "cards": len(results),
        "count_matches": count_matches,
        "label_matches": label_matches,
        "label_match_rate": label_matches / len(results),
        "journal_entries": len(journal),
        "visual_distribution": dict(Counter(row["visual_label"] for row in results)),
        "svg_distribution": dict(Counter(row["svg_label"] for row in results)),
        "final_distribution": dict(Counter(row["final_label"] for row in results)),
    }
    return results, journal, stats


def make_clean(posters: list[dict], descriptions: dict, structural: dict, pilot: list[dict]) -> tuple[list[dict], list[dict]]:
    pilot_by_id = unique_index(pilot, "poster_id")
    if set(descriptions) != {poster["id"] for poster in posters}:
        raise ValueError("Новые описания должны покрывать все исходные карточки")
    clean, excluded = [], []
    for poster in posters:
        poster_id = poster["id"]
        count, label, _ = structural[poster_id]
        pilot_row = pilot_by_id.get(poster_id)
        if pilot_row:
            label = pilot_row["final_label"]
        if label == REVIEW:
            excluded.append({"id": poster_id, "reason": "unresolved_style"})
            continue
        description = descriptions[poster_id].strip()
        if not tokens(description) or {MINIMAL, DETAILED} & set(tokens(description)):
            raise ValueError(f"Пустое описание или явная метка стиля у {poster_id}")
        clean.append({
            **{key: value for key, value in poster.items() if key != "svg"},
            "description": description, "style": label, "objects": count,
            "style_source": "visual_svg_pilot" if pilot_row else "svg_rule",
            "image": f"posters/{poster_id}.svg",
            "width": SIZE, "height": SIZE,
            "sha256": sha256(poster["svg"]),
            "geometry_sha256": geometry_sha256(poster["svg"]),
        })
    return clean, excluded


def make_queries(source_queries: list[dict], query_texts: dict) -> list[dict]:
    by_id = unique_index(source_queries, "id")
    if set(by_id) != set(query_texts):
        raise ValueError("Новые тексты должны покрывать все запросы")
    queries = []
    for row in source_queries:
        text = query_texts[row["id"]].strip()
        if not tokens(text) or row["split"] not in SPLITS or row["genre"] not in GENRES:
            raise ValueError(f"Некорректный запрос {row['id']}")
        queries.append({
            "id": row["id"], "split": row["split"], "genre": row["genre"],
            "kind": row["kind"], "text": text, "target_style": MINIMAL,
            "source": "Синтетический бриф ЛР 6 на основе запроса ЛР 5",
        })
    return queries


def check_split(clean: list[dict], queries: list[dict]) -> tuple[dict, list[dict]]:
    cards_by_split = {split: [row for row in clean if row["split"] == split] for split in SPLITS}
    queries_by_split = {split: [row for row in queries if row["split"] == split] for split in SPLITS}
    fields = ("id", "author", "series", "family", "source_sha256", "sha256", "geometry_sha256")
    signatures = {}
    splits = {}
    for split in SPLITS:
        cards, split_queries = cards_by_split[split], queries_by_split[split]
        pairs = Counter((row["genre"], row["style"]) for row in cards)
        if pairs != Counter((genre, style) for genre in GENRES for style in (MINIMAL, DETAILED)):
            raise ValueError(f"Изменилась представленность жанров или стилей в {split}")
        if Counter((row["genre"], row["kind"]) for row in split_queries) != Counter(
            (genre, kind) for genre in GENRES for kind in ("literal", "synonym")
        ):
            raise ValueError(f"Изменилась представленность запросов в {split}")

        signatures[split] = {
            **{f"card_{field}": {row[field] for row in cards} for field in fields},
            "description": {tuple(tokens(row["description"])) for row in cards},
            "query_id": {row["id"] for row in split_queries},
            "query_text": {tuple(tokens(row["text"])) for row in split_queries},
        }
        for field in ("card_id", "card_sha256", "description", "query_id", "query_text"):
            expected = len(split_queries) if field.startswith("query_") else len(cards)
            if len(signatures[split][field]) != expected:
                raise ValueError(f"Есть повторы по {field} внутри {split}")
        splits[split] = {
            "poster_ids": [row["id"] for row in cards],
            "query_ids": [row["id"] for row in split_queries],
            "authors": sorted(signatures[split]["card_author"]),
            "series": sorted(signatures[split]["card_series"]),
            "families": sorted(signatures[split]["card_family"]),
        }

    overlaps = []
    for left, right in combinations(SPLITS, 2):
        counts = {field: len(values & signatures[right][field]) for field, values in signatures[left].items()}
        if any(counts.values()):
            raise ValueError(f"Пересечение {left}/{right}: {counts}")
        overlaps.append({"split_a": left, "split_b": right, **counts})
    return splits, overlaps


def qrels_for(clean: list[dict], queries: list[dict]) -> list[dict]:
    rows = []
    for query in queries:
        for poster in clean:
            if query["split"] == poster["split"]:
                score = 0
                if query["genre"] == poster["genre"]:
                    score = 2 if poster["style"] == query["target_style"] else 1
                rows.append({"query_id": query["id"], "poster_id": poster["id"],
                             "split": query["split"], "relevance": score})
    return rows


def input_digests() -> dict:
    paths = [
        SOURCE / "raw.json", SOURCE / "queries.json", ROOT / "annotation_guideline.md",
        ROOT / "artwork.py", ROOT / "prepare.py",
        *(path for path in INPUTS.iterdir() if path.is_file()),
    ]
    return {str(path.relative_to(ROOT.parent)): sha256(path.read_bytes().replace(b"\r\n", b"\n"))
        for path in sorted(paths)}


def build(out: Path, posters: list[dict], exclusions: list[dict], pilot: dict, policy: dict) -> None:
    texts = read_json(INPUTS / "texts.json")
    structural = {poster["id"]: inspect_svg(poster["svg"]) for poster in posters}
    results, journal, pilot_stats = pilot_results(pilot, structural, policy["instruction_version"])
    clean, unresolved = make_clean(posters, texts["descriptions"], structural, results)
    exclusions = [*exclusions, *unresolved]
    queries = make_queries(read_json(SOURCE / "queries.json"), texts["queries"])
    splits, overlaps = check_split(clean, queries)
    qrels = qrels_for(clean, queries)
    idf = fit_idf(clean)
    features = {
        "posters": {row["id"]: vector(row["description"], idf) for row in clean},
        "queries": {row["id"]: vector(row["text"], idf) for row in queries},
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "posters").mkdir(exist_ok=True)
    included = {row["id"] for row in clean}
    for poster in posters:
        if poster["id"] in included:
            (out / "posters" / f"{poster['id']}.svg").write_bytes(poster["svg"])
    write_json(out / "clean.json", clean)
    write_json(out / "queries.json", queries)
    write_json(out / "split.json", splits)
    write_json(out / "idf.json", idf)
    write_json(out / "tfidf.json", features)
    write_csv(out / "qrels.csv", ("query_id", "poster_id", "split", "relevance"), qrels)
    write_csv(out / "exclusions.csv", ("id", "reason"), exclusions)
    write_csv(out / "pilot_results.csv", results[0].keys(), results)
    write_csv(out / "decision_log.csv", JOURNAL_FIELDS, journal)
    write_csv(out / "split_overlap.csv", overlaps[0].keys(), overlaps)
    write_json(out / "statistics.json", {
        "dataset_version": policy["dataset_version"],
        "instruction_version": policy["instruction_version"],
        "raw_cards": len(posters) + len(exclusions) - len(unresolved),
        "clean_cards": len(clean),
        "exclusions": dict(Counter(row["reason"] for row in exclusions)),
        "styles": dict(Counter(row["style"] for row in clean)),
        "circle_counts": dict(sorted(Counter(row["objects"] for row in clean).items())),
        "genres": dict(Counter(row["genre"] for row in clean)),
        "by_split": {
            split: {
                "cards": len(info["poster_ids"]), "queries": len(info["query_ids"]),
                "styles": dict(Counter(row["style"] for row in clean if row["split"] == split)),
            }
            for split, info in splits.items()
        },
        "qrel_counts": dict(sorted(Counter(row["relevance"] for row in qrels).items())),
        "train_vocabulary_size": len(idf["weights"]),
        "queries_with_empty_tfidf": [
            row["id"] for row in queries if not features["queries"][row["id"]]
        ],
        "pilot": pilot_stats,
    })
    write_json(out / "manifest.json", {
        "dataset_version": policy["dataset_version"],
        "instruction_version": policy["instruction_version"],
        "inputs_sha256": input_digests(),
        "files_sha256": tree_hashes(out, omit_manifest=True),
    })


def tree_hashes(directory: Path, omit_manifest: bool = False) -> dict:
    return {
        path.relative_to(directory).as_posix(): sha256(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not (omit_manifest and path == directory / "manifest.json")
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    actions = cli.add_mutually_exclusive_group()
    actions.add_argument("--out", type=Path, default=DATA, help="Папка для подготовленного набора")
    actions.add_argument("--check", action="store_true", help="Сверить опубликованный набор с пересборкой")
    actions.add_argument("--pilot-board", type=Path, help="Создать слепой лист для первичной разметки")
    args = cli.parse_args()
    policy = read_json(INPUTS / "split_policy.json")
    source_rows, exclusions = clean_source(read_json(SOURCE / "raw.json"))
    posters = make_posters(source_rows, policy)
    pilot = pilot_items(posters, policy)
    if args.pilot_board:
        write_pilot_board(args.pilot_board, pilot)
        print(f"Лист пилота: {args.pilot_board / 'index.html'}")
    elif args.check:
        with tempfile.TemporaryDirectory() as temp:
            build(Path(temp), posters, exclusions, pilot, policy)
            published, reproduced = tree_hashes(DATA), tree_hashes(Path(temp))
            if published != reproduced:
                changed = sorted(name for name in published.keys() | reproduced.keys()
                                 if published.get(name) != reproduced.get(name))
                raise SystemExit(f"Подготовленные файлы различаются: {', '.join(changed)}")
        print(f"Воспроизводимость подтверждена, файлов: {len(published)}")
    else:
        build(args.out, posters, exclusions, pilot, policy)
        print(f"Набор {policy['dataset_version']}: {args.out}")


if __name__ == "__main__":
    main()
