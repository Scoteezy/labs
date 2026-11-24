"""Input validation and local image assessment for Lab 11."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, UnidentifiedImageError

from lab06.prepare import prepare_pair
from lab07 import baseline
from lab09 import experiment


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
DEFAULT_CONFIG = ROOT / "config.json"
DECISION_PATH = REPOSITORY / "lab09" / "results" / "decision.json"
MODEL_VERSIONS = {"baseline": "ssim_1.0", "candidate": "local_ssim_q90_1.0"}


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def read_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("host") != "127.0.0.1":
        raise ValueError("Сервис допускает только localhost")
    for key in ("port", "max_body_bytes", "max_image_bytes", "max_image_side"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"Некорректное число в config: {key}")
    if config.get("port", 0) > 65535 or config.get("required_image_format") != "PNG":
        raise ValueError("Некорректный config")
    if config.get("default_mode") not in ("selected", *MODEL_VERSIONS):
        raise ValueError("Некорректный default_mode")
    if not isinstance(config.get("decision_sha256"), str) or len(config["decision_sha256"]) != 64:
        raise ValueError("Некорректный decision_sha256")
    return config


def _decode(value: object, field: str, config: dict[str, Any]) -> Image.Image:
    if not isinstance(value, str):
        raise ApiError(400, f"{field}_must_be_base64_string")
    try:
        content = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError):
        raise ApiError(400, f"{field}_invalid_base64")
    if not content:
        raise ApiError(400, f"{field}_empty")
    if len(content) > config["max_image_bytes"]:
        raise ApiError(413, f"{field}_too_large")
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format != config["required_image_format"]:
                raise ApiError(415, f"{field}_must_be_png")
            if source.width > config["max_image_side"] or source.height > config["max_image_side"]:
                raise ApiError(413, f"{field}_dimensions_too_large")
            if source.mode != "RGB" or getattr(source, "is_animated", False):
                raise ApiError(415, f"{field}_must_be_single_rgb")
            image = source.convert("RGB")
    except ApiError:
        raise
    except Image.DecompressionBombError as error:
        raise ApiError(413, f"{field}_dimensions_too_large") from error
    except (UnidentifiedImageError, OSError, ValueError):
        raise ApiError(400, f"{field}_invalid_image")
    return image


def _box(value: object, field: str) -> Sequence[int]:
    if not isinstance(value, list) or len(value) != 4 or any(type(item) is not int for item in value):
        raise ApiError(400, f"{field}_must_be_four_integers")
    return value


@dataclass
class InspectionService:
    config: dict[str, Any]
    decision: dict[str, Any] | None
    resource_error: str | None = None

    @classmethod
    def load(cls, config_path: Path = DEFAULT_CONFIG, force_mode: str | None = None) -> "InspectionService":
        config = read_config(config_path)
        try:
            decision_text = DECISION_PATH.read_text(encoding="utf-8")
            if hashlib.sha256(decision_text.encode("utf-8")).hexdigest() != config["decision_sha256"]:
                raise ValueError("Контрольная сумма решения ЛР 9 не совпадает")
            decision = json.loads(decision_text)
            mode = decision["mode"]
            if (mode not in MODEL_VERSIONS or decision["selected_model_version"] != MODEL_VERSIONS[mode]
                    or decision["selected_threshold"] != decision[f"{mode}_threshold"]):
                raise ValueError("Некорректный выбор режима в решении ЛР 9")
            for name in MODEL_VERSIONS:
                threshold = decision[f"{name}_threshold"]
                if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
                    raise ValueError("Порог вне диапазона [0, 1]")
            effective = force_mode or config["default_mode"]
            if effective != "selected":
                if effective not in MODEL_VERSIONS:
                    raise ValueError("Неизвестный принудительный режим")
                decision["mode"] = effective
                decision["selected_threshold"] = decision[f"{effective}_threshold"]
                decision["selected_model_version"] = MODEL_VERSIONS[effective]
            return cls(config, decision)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return cls(config, None, str(error))

    @property
    def host(self) -> str:
        return self.config["host"]

    @property
    def port(self) -> int:
        return self.config["port"]

    def inspect(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ApiError(400, "object_required")
        if self.decision is None:
            raise ApiError(503, "model_unavailable")
        original_box = _box(payload.get("original_box"), "original_box")
        candidate_box = _box(payload.get("candidate_box"), "candidate_box")
        with (_decode(payload.get("original_base64"), "original", self.config) as original,
              _decode(payload.get("candidate_base64"), "candidate", self.config) as candidate):
            try:
                reference, compared = prepare_pair(original, candidate, original_box, candidate_box)
            except ValueError as error:
                raise ApiError(400, "invalid_box") from error
            original_size = list(original.size)
            candidate_size = list(candidate.size)

        selected = self.decision["mode"]
        fallback_reason = None
        if selected == "candidate":
            try:
                score = checked_score(experiment.candidate_score, reference, compared)
            except (ValueError, ArithmeticError, RuntimeError):
                selected = "baseline"
                fallback_reason = "candidate_scoring_failed"
        if selected == "baseline":
            try:
                score = checked_score(baseline.baseline_score, reference, compared)
            except (ValueError, ArithmeticError, RuntimeError) as error:
                raise ApiError(503, "model_unavailable") from error
        threshold = self.decision[f"{selected}_threshold"]
        assessment = "suspected_distortion" if score >= threshold else "passed"
        return {
            "status": "fallback" if fallback_reason else "ok",
            "assessment": assessment,
            "mode": selected,
            "fallback_reason": fallback_reason,
            "score": score,
            "threshold": threshold,
            "model_version": MODEL_VERSIONS[selected],
            "dataset_version": "1.0",
            "human_decision_required": True,
            "input": {
                "original_size": original_size,
                "candidate_size": candidate_size,
                "original_box": list(original_box),
                "candidate_box": list(candidate_box),
            },
            "message": (
                "Оценка ниже порога. Дизайнер принимает решение о кадре."
                if assessment == "passed"
                else "Требуется проверить упаковку, этикетку и форму товара."
            ),
        }


def checked_score(score_function, reference, compared) -> float:
    score = score_function(reference, compared)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Оценка вне диапазона [0, 1]")
    return score
