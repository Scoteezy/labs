"""Build and verify the controlled synthetic cosmetic-package pilot dataset.

Run from repository root:
    python -m lab04.generate
    python -m lab04.generate --check
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
IMAGES = DATA / "images"
SEED = 20261124
DATASET_VERSION = "1.0"
CANVAS = (224, 288)
PRODUCTS = 24
CASES_PER_PRODUCT = 8
FAMILIES = [f"F{number:02d}" for number in range(1, 13)]
SPLIT = {
    "dataset_version": DATASET_VERSION,
    "seed": SEED,
    "unit": "family_id",
    "train": FAMILIES[:6],
    "validation": FAMILIES[6:9],
    "test": FAMILIES[9:],
}
PALETTES = (
    ((241, 227, 211), (129, 69, 53), (56, 34, 28)),
    ((215, 231, 228), (54, 105, 98), (26, 51, 49)),
    ((227, 218, 235), (91, 70, 126), (42, 32, 59)),
    ((238, 232, 204), (133, 106, 36), (59, 46, 20)),
    ((216, 226, 240), (54, 92, 132), (25, 45, 71)),
    ((234, 215, 218), (143, 65, 80), (66, 29, 37)),
)
FORMULAS = ("CREAM 50", "SERUM 30", "BALM 75", "GEL 40", "MASK 60", "OIL 25")
LOGOS = ("VIVA", "NOVA", "LUMA", "ORBI", "MIRA", "SOLA")
VARIATIONS = (
    ("background_warm", 0, "none"),
    ("background_cool", 0, "none"),
    ("lighting_up", 0, "none"),
    ("lighting_down", 0, "none"),
    ("text_warm", 1, "text"),
    ("logo_cool", 1, "logo"),
    ("shape_up", 1, "shape"),
    ("text_down", 1, "text"),
)


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def color_shift(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, channel + amount)) for channel in color)


def make_background(rng: random.Random, variation: str) -> Image.Image:
    warm = variation.endswith("warm")
    cool = variation.endswith("cool")
    if warm:
        base = (236, 218, 200)
    elif cool:
        base = (204, 221, 235)
    else:
        base = (224, 224, 217)
    image = Image.new("RGB", CANVAS, base)
    draw = ImageDraw.Draw(image)
    for _ in range(14):
        radius = rng.randrange(16, 52)
        x = rng.randrange(-10, CANVAS[0] + 10)
        y = rng.randrange(-10, CANVAS[1] + 10)
        tint = color_shift(base, rng.choice((-12, -8, 8, 12)))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=tint)
    return image.filter(ImageFilter.GaussianBlur(radius=7))


def product_geometry(product_index: int, shift_x: int, shift_y: int) -> tuple[int, int, int, int, str]:
    style = ("bottle", "tube", "jar")[product_index % 3]
    if style == "bottle":
        box = (69 + shift_x, 57 + shift_y, 155 + shift_x, 239 + shift_y)
    elif style == "tube":
        box = (63 + shift_x, 50 + shift_y, 161 + shift_x, 240 + shift_y)
    else:
        box = (51 + shift_x, 104 + shift_y, 173 + shift_x, 208 + shift_y)
    return (*box, style)


def draw_product(
    image: Image.Image,
    product_index: int,
    product_id: str,
    variation: str,
    defect_type: str,
    shift_x: int,
    shift_y: int,
) -> tuple[list[int], list[int] | None]:
    """Draw a package and return product box and the intentional defect region."""
    palette = PALETTES[product_index % len(PALETTES)]
    _, fill, dark = palette
    x0, y0, x1, y1, style = product_geometry(product_index, shift_x, shift_y)
    draw = ImageDraw.Draw(image)
    defect_region = None
    shadow = (x0 + 7, y1 - 3, x1 + 14, y1 + 10)
    draw.ellipse(shadow, fill=(165, 165, 162))

    if style == "bottle":
        body = (x0 + 9, y0 + 35, x1 - 9, y1)
        neck = (x0 + 27, y0 + 10, x1 - 27, y0 + 42)
        cap = (x0 + 24, y0, x1 - 24, y0 + 15)
        draw.rounded_rectangle(body, radius=14, fill=fill, outline=dark, width=3)
        draw.rounded_rectangle(neck, radius=5, fill=color_shift(fill, 12), outline=dark, width=2)
        draw.rounded_rectangle(cap, radius=3, fill=dark)
    elif style == "tube":
        body = (x0 + 6, y0 + 13, x1 - 6, y1 - 20)
        cap = (x0 + 23, y1 - 23, x1 - 23, y1)
        draw.polygon(
            [(x0 + 15, y0), (x1 - 15, y0), (x1 - 6, y1 - 20), (x0 + 6, y1 - 20)],
            fill=fill,
            outline=dark,
            width=3,
        )
        draw.rounded_rectangle(cap, radius=4, fill=dark)
    else:
        body = (x0, y0 + 20, x1, y1)
        cap = (x0 + 7, y0, x1 - 7, y0 + 29)
        draw.rounded_rectangle(body, radius=18, fill=fill, outline=dark, width=3)
        draw.rounded_rectangle(cap, radius=9, fill=color_shift(fill, -26), outline=dark, width=2)

    label = (body[0] + 7, body[1] + 24, body[2] - 7, body[1] + 82)
    draw.rounded_rectangle(label, radius=5, fill=(244, 242, 232), outline=dark, width=2)
    formula = FORMULAS[product_index % len(FORMULAS)]
    logo = LOGOS[(product_index * 2) % len(LOGOS)]
    text_defects = ("CR?AM 50", "SERUM 80")
    label_width = label[2] - label[0] - 8
    labels = (formula, logo, product_id, *text_defects, "V1VA")
    for size in range(12, 5, -1):
        font = ImageFont.load_default(size=size)
        if max(draw.textlength(line, font=font) for line in labels) <= label_width:
            break
    center = (label[0] + label[2]) // 2
    logo_at = (center, label[1] + 8)
    formula_at = (center, label[1] + 28)
    if defect_type == "text":
        formula = text_defects[0] if variation.endswith("warm") else text_defects[1]
        defect_region = [label[0] + 3, label[1] + 27, label[2] - 2, label[1] + 41]
    if defect_type == "logo":
        logo = "V1VA"
        defect_region = [label[0] + 3, label[1] + 7, label[2] - 2, label[1] + 21]
    draw.text(logo_at, logo, fill=dark, font=font, anchor="mt")
    draw.text(formula_at, formula, fill=dark, font=font, anchor="mt")
    draw.text((center, label[1] + 43), product_id, fill=dark, font=font, anchor="mt")

    if defect_type == "shape":
        if style == "jar":
            defect_region = [x1 - 21, y0 + 34, x1 + 1, y0 + 69]
            draw.polygon(
                [(x1 - 17, y0 + 36), (x1 + 1, y0 + 45), (x1 - 9, y0 + 66)],
                fill=color_shift(fill, 24),
                outline=dark,
            )
        else:
            defect_region = [x1 - 13, y0 + 42, x1 + 6, y0 + 85]
            draw.polygon(
                [(x1 - 12, y0 + 43), (x1 + 6, y0 + 57), (x1 - 11, y0 + 85)],
                fill=color_shift(fill, 24),
                outline=dark,
            )

    return [x0 - 8, y0 - 3, x1 + 8, y1 + 3], defect_region


def build_pair(
    pair_id: str,
    product_index: int,
    product_id: str,
    variation: str,
    defect_type: str,
    label: int,
) -> tuple[Image.Image, Image.Image, list[int], list[int], list[int] | None]:
    original_rng = random.Random(f"{SEED}|{product_id}|original")
    candidate_rng = random.Random(f"{SEED}|{pair_id}|candidate")
    original = make_background(original_rng, "neutral")
    candidate = make_background(candidate_rng, variation)
    original_box, _ = draw_product(original, product_index, product_id, "neutral", "none", 0, 0)
    shift_x, shift_y = candidate_rng.choice((-2, -1, 0, 1, 2)), candidate_rng.choice((-2, -1, 0, 1, 2))
    candidate_box, defect_region = draw_product(
        candidate, product_index, product_id, variation, defect_type, shift_x, shift_y
    )
    if variation.endswith("_up"):
        candidate = candidate.point(lambda value: min(255, int(value * 1.12)))
    if variation.endswith("_down"):
        candidate = candidate.point(lambda value: max(0, int(value * 0.80)))
    return original, candidate, original_box, candidate_box, defect_region


def pair_rows() -> list[dict]:
    rows = []
    for product_index in range(PRODUCTS):
        product_id = f"COSM{product_index + 1:03d}"
        family_id = FAMILIES[product_index // 2]
        original_name = f"{product_id}_original.png"
        for case_index, (variation, label, defect_type) in enumerate(VARIATIONS, start=1):
            pair_id = f"PAIR{product_index + 1:03d}_{case_index:02d}"
            candidate_name = f"{pair_id}_candidate.png"
            original, candidate, original_box, candidate_box, defect_region = build_pair(
                pair_id, product_index, product_id, variation, defect_type, label
            )
            yield {
                "pair_id": pair_id,
                "product_id": product_id,
                "family_id": family_id,
                "original": f"lab04/data/images/{original_name}",
                "candidate": f"lab04/data/images/{candidate_name}",
                "original_box": original_box,
                "candidate_box": candidate_box,
                "label": label,
                "defect_type": defect_type,
                "variation": variation,
                "source": "controlled_synthetic",
                "rights_status": "project_generated",
                "defect_region": defect_region,
                "_original": original,
                "_candidate": candidate,
            }


def write_dataset() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    rows = []
    originals_written = set()
    for row in pair_rows():
        original_path = ROOT.parent / row["original"]
        candidate_path = ROOT.parent / row["candidate"]
        if original_path not in originals_written:
            row["_original"].save(original_path, optimize=True)
            originals_written.add(original_path)
        row["_candidate"].save(candidate_path, optimize=True)
        rows.append({key: value for key, value in row.items() if not key.startswith("_")})
    payload = {"dataset_version": DATASET_VERSION, "seed": SEED, "pairs": rows}
    (DATA / "pairs.json").write_text(json_text(payload), encoding="utf-8")
    (ROOT / "split.json").write_text(json_text(SPLIT), encoding="utf-8")
    write_registry(rows)
    write_manifest()


def write_registry(rows: list[dict]) -> None:
    fields = (
        "pair_id",
        "product_id",
        "family_id",
        "source",
        "rights_status",
        "label",
        "defect_type",
        "variation",
    )
    with (ROOT / "source_registry.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_manifest() -> None:
    paths = sorted(path for path in DATA.rglob("*") if path.is_file())
    manifest = {
        "dataset_version": DATASET_VERSION,
        "generator": "lab04/generate.py",
        "seed": SEED,
        "files_sha256": {
            path.relative_to(ROOT.parent).as_posix(): digest(path)
            for path in paths
            if path.name != "manifest.json"
        },
    }
    (DATA / "manifest.json").write_text(json_text(manifest), encoding="utf-8")


def check() -> None:
    payload = json.loads((DATA / "pairs.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    if payload["dataset_version"] != DATASET_VERSION or payload["seed"] != SEED:
        raise ValueError("Версия или seed набора не совпадают с генератором")
    rows = payload["pairs"]
    if len(rows) != PRODUCTS * CASES_PER_PRODUCT:
        raise ValueError("Количество пар отличается от спецификации")
    if Counter(row["label"] for row in rows) != {0: 96, 1: 96}:
        raise ValueError("Баланс классов нарушен")
    if Counter(row["defect_type"] for row in rows) != {"none": 96, "text": 48, "logo": 24, "shape": 24}:
        raise ValueError("Состав типов дефектов нарушен")
    if set().union(*[set(SPLIT[name]) for name in ("train", "validation", "test")]) != set(FAMILIES):
        raise ValueError("Split не покрывает семейства")
    splits = ("train", "validation", "test")
    if any(
        set(SPLIT[left]) & set(SPLIT[right])
        for left in splits
        for right in splits
        if left < right
    ):
        raise ValueError("Семейства пересекаются между частями")
    required = {
        "pair_id", "product_id", "family_id", "original", "candidate", "original_box",
        "candidate_box", "label", "defect_type", "variation", "source", "rights_status",
    }
    for row in rows:
        if not required <= row.keys() or row["source"] != "controlled_synthetic":
            raise ValueError(f"Неверная запись {row.get('pair_id')}")
        for name in ("original", "candidate"):
            path = ROOT.parent / row[name]
            if not path.exists():
                raise ValueError(f"Нет файла {path}")
            with Image.open(path) as image:
                width, height = image.size
                if image.mode != "RGB" or image.format != "PNG":
                    raise ValueError(f"Ожидался RGB PNG: {path}")
            box_name = "original_box" if name == "original" else "candidate_box"
            x0, y0, x1, y1 = row[box_name]
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError(f"Некорректная область товара: {row['pair_id']}")
    for name, expected in manifest["files_sha256"].items():
        path = ROOT.parent / name
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Контрольная сумма не совпала: {name}")
    print(
        f"Проверено {len(rows)} пар, {len({row['product_id'] for row in rows})} дизайна, "
        f"{len(FAMILIES)} семейств, классы 0/1: 96/96."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only verify the saved release")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        write_dataset()
        check()


if __name__ == "__main__":
    main()
