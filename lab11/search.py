"""Load the Lab 06 catalog and serve the two frozen TF-IDF modes."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from lab07 import baseline
from lab09.experiment import normalized_text


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DATA = "lab06/data/"
MANIFEST = DATA + "manifest.json"
CATALOG = DATA + "clean.json"
SPLIT = DATA + "split.json"
BASE_IDF = DATA + "idf.json"
LEXICON = "lab09/lexicon.json"
CANDIDATE_IDF = "lab09/results/candidate_idf.json"
POSTER_ID = re.compile(r"P[0-9]{3}")
RESOURCE_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError)


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def load_config(path: Path) -> dict:
    config = json.loads(path.read_bytes())
    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна быть JSON-объектом")
    for field in ("k", "max_query_chars", "max_body_bytes", "port"):
        if type(config.get(field)) is not int or config[field] < 1:
            raise ValueError(f"Ожидается положительное целое число: {field}")
    if config["port"] > 65535 or config.get("host") != "127.0.0.1":
        raise ValueError("Нужен адрес 127.0.0.1 и порт от 1 до 65535")
    if config.get("mode") not in ("baseline", "candidate"):
        raise ValueError("Ожидается mode=baseline или mode=candidate")
    for field in ("config_version", "dataset_version", "model_version", "lexicon_version"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError(f"Ожидается непустая версия: {field}")
    if config.get("fit_split") != "train" or config.get("allowed_rights_status") != "demo_allowed":
        raise ValueError("Модуль использует train-IDF и допуск demo_allowed")
    if not isinstance(config.get("sha256"), dict):
        raise ValueError("Отсутствует раздел sha256")
    return config


def checked_bytes(path: Path, digest: str) -> bytes:
    content = path.read_bytes()
    if baseline.sha256(content) != digest:
        raise ValueError(f"Контрольная сумма не совпала: {path.name}")
    return content


def load_json(config: dict, name: str):
    return json.loads(checked_bytes(REPO / name, config["sha256"][name]))


def allowed_record(row: dict, rights_status: str) -> bool:
    return (
        row.get("rights_status") == rights_status
        and isinstance(row.get("source"), str)
        and bool(row["source"].strip())
    )


def load_catalog(config: dict) -> tuple[dict, list[str]]:
    manifest = load_json(config, MANIFEST)
    if manifest["dataset_version"] != config["dataset_version"]:
        raise ValueError("Версия каталога отличается от конфигурации")
    for name in (CATALOG, SPLIT, BASE_IDF):
        if manifest["files_sha256"][name.removeprefix(DATA)] != config["sha256"][name]:
            raise ValueError(f"Артефакт отсутствует в зафиксированном выпуске: {name}")

    cards = {}
    seen = set()
    for row in load_json(config, CATALOG):
        poster_id = row["id"]
        if not POSTER_ID.fullmatch(poster_id) or poster_id in seen:
            raise ValueError("Некорректный или повторный идентификатор афиши")
        seen.add(poster_id)
        if not allowed_record(row, config["allowed_rights_status"]):
            continue
        if any(not isinstance(row.get(field), str) or not row[field].strip()
               for field in ("genre", "style", "description")):
            raise ValueError(f"Карточка неполная: {poster_id}")
        if (row["image"] != f"posters/{poster_id}.svg"
                or row["sha256"] != manifest["files_sha256"][row["image"]]):
            raise ValueError(f"Изображение отсутствует в зафиксированном выпуске: {poster_id}")
        cards[poster_id] = row

    train_ids = load_json(config, SPLIT)[config["fit_split"]]["poster_ids"]
    if (not cards or not train_ids or len(set(train_ids)) != len(train_ids)
            or any(poster_id not in cards or cards[poster_id]["split"] != config["fit_split"]
                   for poster_id in train_ids)):
        raise ValueError("Некорректный набор обучающих карточек")
    return cards, train_ids


def load_weights(config: dict, name: str, train_ids: list[str]) -> dict:
    idf = load_json(config, name)
    if idf["fit_split"] != config["fit_split"] or idf["train_ids"] != train_ids:
        raise ValueError("Разбиение IDF отличается от зафиксированного train")
    weights = idf["weights"]
    if not weights or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                          for value in weights.values()):
        raise ValueError("Веса IDF должны быть конечными и положительными")
    return weights


def load_lexicon(config: dict) -> dict[str, str]:
    lexicon = load_json(config, LEXICON)
    if lexicon["version"] != config["lexicon_version"]:
        raise ValueError("Версия словаря отличается от конфигурации")
    replacements = {}
    for canonical, forms in lexicon["genre_forms"].items():
        if baseline.tokens(canonical) != [canonical] or not isinstance(forms, list):
            raise ValueError("Некорректная форма в словаре")
        for form in forms:
            if baseline.tokens(form) != [form] or form in replacements:
                raise ValueError("Некорректная или повторная форма в словаре")
            replacements[form] = canonical
    if not replacements:
        raise ValueError("Словарь пуст")
    return replacements


@dataclass
class SearchIndex:
    weights: dict
    replacements: dict
    vectors: dict

    @classmethod
    def build(cls, cards: dict, weights: dict, replacements: dict) -> "SearchIndex":
        vectors = {
            poster_id: baseline.vectorize(normalized_text(row["description"], replacements).split(), weights)
            for poster_id, row in cards.items()
        }
        return cls(weights, replacements, vectors)

    def rank(self, query: str, k: int) -> list[dict]:
        terms = normalized_text(query, self.replacements).split()
        vector = baseline.vectorize(terms, self.weights)
        hits = baseline.rank(vector, self.vectors, k)
        for hit in hits:
            hit["matched_terms"] = sorted(vector.keys() & self.vectors[hit["poster_id"]].keys())
        return hits


class SearchService:
    def __init__(self, config: dict):
        self.config = config
        self.host = config["host"]
        self.port = config["port"]
        self.max_body_bytes = config["max_body_bytes"]
        self.cards = {}
        self.indexes = {}
        self.resource_error = None
        self.fallback_reason = None

    @classmethod
    def load(cls, config_path: Path = DEFAULT_CONFIG, mode=None) -> "SearchService":
        config = load_config(config_path)
        if mode is not None:
            if mode not in ("baseline", "candidate"):
                raise ValueError(f"Неизвестный режим: {mode}")
            config["mode"] = mode
        service = cls(config)
        try:
            cards, train_ids = load_catalog(config)
            weights = load_weights(config, BASE_IDF, train_ids)
            service.indexes["baseline"] = SearchIndex.build(cards, weights, {})
            service.cards = cards
        except RESOURCE_ERRORS as exc:
            service.resource_error = str(exc)
            return service

        if config["mode"] == "candidate":
            try:
                replacements = load_lexicon(config)
                weights = load_weights(config, CANDIDATE_IDF, train_ids)
                service.indexes["candidate"] = SearchIndex.build(cards, weights, replacements)
            except RESOURCE_ERRORS as exc:
                service.resource_error = str(exc)
                service.fallback_reason = "candidate_unavailable"
        return service

    def search(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise ApiError(400, "object_required")
        query = payload.get("query")
        if not isinstance(query, str):
            raise ApiError(400, "query_must_be_string")
        query = query.strip()
        if not query:
            raise ApiError(400, "empty_query")
        if len(query) > self.config["max_query_chars"]:
            raise ApiError(400, "query_too_long")
        if "baseline" not in self.indexes:
            raise ApiError(503, "catalog_unavailable")

        reason = self.fallback_reason
        mode = "baseline" if reason else self.config["mode"]
        hits = self.indexes[mode].rank(query, self.config["k"])
        results = [self.result_card(hit) for hit in hits]
        status = "fallback" if reason else "ok"
        return {
            "status": status if results else "no_matches",
            "mode": mode,
            "fallback_reason": reason,
            "model": "tfidf_genre_normalization" if mode == "candidate" else "tfidf",
            "model_version": self.config["model_version"],
            "dataset_version": self.config["dataset_version"],
            "lexicon_version": self.config["lexicon_version"] if mode == "candidate" else None,
            "results": results,
            "human_decision_required": bool(results),
        }

    def result_card(self, hit: dict) -> dict:
        row = self.cards[hit["poster_id"]]
        return {
            "id": row["id"],
            "genre": row["genre"],
            "style": row["style"],
            "score": hit["score"],
            "source": row["source"],
            "rights_status": row["rights_status"],
            "image": f"/posters/{row['id']}",
            "matched_terms": hit["matched_terms"],
        }

    def get_image(self, record_id: str) -> bytes:
        if "baseline" not in self.indexes:
            raise ApiError(503, "catalog_unavailable")
        if record_id not in self.cards:
            raise ApiError(404, "poster_not_found")
        row = self.cards[record_id]
        try:
            return checked_bytes(REPO / DATA / row["image"], row["sha256"])
        except (OSError, ValueError) as exc:
            raise ApiError(503, "image_unavailable") from exc
