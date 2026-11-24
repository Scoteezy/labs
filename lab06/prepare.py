"""Prepare registered product regions for the packaging-distortion pilot.

The module deliberately has no fitted transform.  It validates the regions
given by the caller, crops them, converts them to grayscale, and scales every
pair to the fixed 128 by 128 representation used by Labs 7, 9, and 11.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
LAB04 = ROOT / "lab04"
DATA = Path(__file__).resolve().parent / "data"
TARGET_SIZE = (128, 128)
REQUIRED_FIELDS = {
    "pair_id", "product_id", "family_id", "original", "candidate",
    "original_box", "candidate_box", "label", "defect_type", "variation",
    "source", "rights_status",
}
VALID_DEFECTS = {"none", "text", "logo", "shape"}
VALID_SPLITS = {"train", "validation", "test"}


def _box(box: Sequence[object], image: Image.Image, name: str) -> tuple[int, int, int, int]:
    """Validate a right/bottom-exclusive crop rectangle for one source image."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError(f"{name} must have four integer coordinates")
    if any(type(value) is not int for value in box):
        raise ValueError(f"{name} coordinates must be integers")
    left, top, right, bottom = box
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        raise ValueError(f"{name} is outside the image")
    if right - left < 4 or bottom - top < 4:
        raise ValueError(f"{name} must be at least 4 by 4 pixels")
    return left, top, right, bottom


def _array(image: Image.Image, box: Sequence[object], name: str) -> np.ndarray:
    if not isinstance(image, Image.Image):
        raise ValueError(f"{name} source must be a PIL image")
    checked_box = _box(box, image, name)
    # RGB is the only supported source representation. Palette and grayscale
    # images are made explicit RGB files by Lab 4 before they reach this step.
    if image.mode != "RGB":
        raise ValueError(f"{name} source must have RGB mode")
    crop = image.crop(checked_box).resize(TARGET_SIZE, Image.Resampling.LANCZOS)
    rgb = np.asarray(crop, dtype=np.float32) / 255.0
    gray = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    return np.ascontiguousarray(gray, dtype=np.float32)


def prepare_pair(
    original: Image.Image,
    candidate: Image.Image,
    original_box: Sequence[object],
    candidate_box: Sequence[object],
) -> tuple[np.ndarray, np.ndarray]:
    """Return aligned 128×128 grayscale float arrays in the closed [0, 1] range.

    ``original_box`` and ``candidate_box`` are x0, y0, x1, y1 coordinates.
    They are supplied by the manifest for offline evaluation or by the designer
    in the local alpha.  This function does not infer, alter, or store regions.
    """
    reference = _array(original, original_box, "original")
    inspected = _array(candidate, candidate_box, "candidate")
    if reference.shape != TARGET_SIZE[::-1] or inspected.shape != TARGET_SIZE[::-1]:
        raise AssertionError("unexpected prepared image shape")
    if not (np.isfinite(reference).all() and np.isfinite(inspected).all()):
        raise ValueError("prepared arrays must be finite")
    return reference, inspected


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_row(row: object, family_splits: dict[str, str]) -> dict:
    if not isinstance(row, dict) or REQUIRED_FIELDS - row.keys():
        missing = sorted(REQUIRED_FIELDS - set(row) if isinstance(row, dict) else REQUIRED_FIELDS)
        raise ValueError(f"pair has missing fields: {missing}")
    if row["label"] not in (0, 1):
        raise ValueError(f"{row['pair_id']}: label must be 0 or 1")
    if row["defect_type"] not in VALID_DEFECTS:
        raise ValueError(f"{row['pair_id']}: invalid defect type")
    if (row["label"] == 0) != (row["defect_type"] == "none"):
        raise ValueError(f"{row['pair_id']}: label and defect type disagree")
    if row["source"] != "controlled_synthetic" or row["rights_status"] != "project_generated":
        raise ValueError(f"{row['pair_id']}: unsupported source or rights status")
    for field in ("pair_id", "product_id", "family_id", "original", "candidate", "variation"):
        if not isinstance(row[field], str) or not row[field]:
            raise ValueError(f"{row['pair_id']}: {field} must be a non-empty string")
    split = family_splits.get(row["family_id"])
    if split not in VALID_SPLITS:
        raise ValueError(f"{row['pair_id']}: family is missing from split")

    original_path = ROOT / row["original"]
    candidate_path = ROOT / row["candidate"]
    try:
        with Image.open(original_path) as original, Image.open(candidate_path) as candidate:
            reference, inspected = prepare_pair(original, candidate, row["original_box"], row["candidate_box"])
    except (OSError, ValueError) as exc:
        raise ValueError(f"{row['pair_id']}: invalid image or region: {exc}") from exc

    prepared = dict(row)
    prepared.update({
        "split": split,
        "original_sha256": sha256(original_path),
        "candidate_sha256": sha256(candidate_path),
        "prepared_shape": list(reference.shape),
        "prepared_range": [float(min(reference.min(), inspected.min())), float(max(reference.max(), inspected.max()))],
    })
    return prepared


def _validate_visual_pilot(pairs: list[dict]) -> dict:
    """Check that the recorded pilot refers to existing train pairs only."""
    path = DATA / "visual_pilot.csv"
    if not path.exists():
        raise ValueError("visual pilot is missing")
    lookup = {row["pair_id"]: row for row in pairs}
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"review_order", "pair_id", "split", "observed_type", "generator_type", "agreement", "observation"}
    if not rows or any(required - set(row) for row in rows):
        raise ValueError("visual pilot has invalid columns")
    seen = set()
    for row in rows:
        pair = lookup.get(row["pair_id"])
        if pair is None or pair["split"] != "train" or row["split"] != "train":
            raise ValueError("visual pilot must refer to train pairs")
        if row["pair_id"] in seen:
            raise ValueError("visual pilot contains a duplicate pair")
        seen.add(row["pair_id"])
        if row["generator_type"] != pair["defect_type"]:
            raise ValueError("visual pilot generator type differs from manifest")
        if row["observed_type"] not in VALID_DEFECTS or row["agreement"] not in {"0", "1"}:
            raise ValueError("visual pilot has an invalid observed type or agreement")
        if int(row["agreement"]) != (row["observed_type"] == row["generator_type"]):
            raise ValueError("visual pilot agreement does not match the compared labels")
        if not row["observation"].strip():
            raise ValueError("visual pilot observation is empty")
    return {
        "rows": len(rows),
        "agreement": sum(row["agreement"] == "1" for row in rows),
        "by_observed_type": dict(sorted(Counter(row["observed_type"] for row in rows).items())),
    }


def build() -> dict:
    """Validate Lab 4 assets and create the versioned Lab 6 prepared manifest."""
    source = _read_json(LAB04 / "data" / "pairs.json")
    split_source = _read_json(LAB04 / "split.json")
    if not isinstance(source, dict) or source.get("dataset_version") != "1.0":
        raise ValueError("Lab 4 dataset version must be 1.0")
    if not isinstance(source.get("pairs"), list):
        raise ValueError("Lab 4 pairs must be a list")
    family_splits = {
        family: split
        for split, families in split_source.items()
        if split in VALID_SPLITS and isinstance(families, list)
        for family in families
    }
    if set(family_splits.values()) != VALID_SPLITS:
        raise ValueError("split must contain train, validation, and test families")
    if len(family_splits) != sum(len(families) for families in split_source.values() if isinstance(families, list)):
        raise ValueError("a family occurs in more than one split")

    pairs = [_validate_row(row, family_splits) for row in source["pairs"]]
    identifiers = [row["pair_id"] for row in pairs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("pair_id values must be unique")
    products = {row["product_id"] for row in pairs}
    if not products:
        raise ValueError("dataset is empty")
    product_splits = {product: {row["split"] for row in pairs if row["product_id"] == product} for product in products}
    leaked = {product: values for product, values in product_splits.items() if len(values) != 1}
    if leaked:
        raise ValueError(f"products cross splits: {sorted(leaked)}")
    if not all(any(row["label"] == label for row in pairs if row["split"] == split)
               for split in VALID_SPLITS for label in (0, 1)):
        raise ValueError("every split must contain both labels")

    pairs.sort(key=lambda row: row["pair_id"])
    pilot = _validate_visual_pilot(pairs)
    summary = {
        "pairs": len(pairs),
        "products": len(products),
        "families": len(family_splits),
        "by_split": dict(sorted(Counter(row["split"] for row in pairs).items())),
        "by_label": dict(sorted(Counter(str(row["label"]) for row in pairs).items())),
        "by_defect_type": dict(sorted(Counter(row["defect_type"] for row in pairs).items())),
        "visual_pilot": pilot,
    }
    return {
        "dataset_version": "1.0",
        "preparation_version": "1.0",
        "source_manifest_sha256": sha256(LAB04 / "data" / "pairs.json"),
        "source_split_sha256": sha256(LAB04 / "split.json"),
        "preprocessing": {
            "source_mode": "RGB only",
            "crop": "manifest rectangle [left, top, right, bottom], right/bottom exclusive",
            "resize": "Pillow LANCZOS to 128x128",
            "grayscale": "BT.709 luminance",
            "range": "float32 [0, 1]",
            "fitted_parameters": "none",
        },
        "summary": summary,
        "pairs": pairs,
    }


def output_files(result: dict) -> dict:
    return {
        DATA / "prepared.json": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        DATA / "summary.json": json.dumps(result["summary"], ensure_ascii=False, indent=2) + "\n",
    }


def check() -> None:
    generated = build()
    for path, content in output_files(generated).items():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"{path.name} is not reproducible")
    print(f"Prepared {generated['summary']['pairs']} pairs: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="regenerate and verify the saved manifest")
    args = parser.parse_args()
    try:
        if args.check:
            check()
        else:
            result = build()
            DATA.mkdir(parents=True, exist_ok=True)
            for path, content in output_files(result).items():
                path.write_text(content, encoding="utf-8", newline="\n")
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
