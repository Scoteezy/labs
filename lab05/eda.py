"""Reproducible EDA for the Lab 4 poster fixture used in Lab 5.

Run from this directory with Python and Pillow:
    python eda.py

The program reads the archived Lab 4 records in data/ and creates all result
files in results/. It does not regenerate or alter the input data.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import textwrap
from collections import Counter, defaultdict
from functools import lru_cache
from html import escape
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
COLORS = ("#2563a6", "#d97706", "#059669", "#7c3aed", "#dc2626", "#0f766e")


def load_json(name: str) -> list[dict]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@lru_cache
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    mac_name = "Arial Bold.ttf" if bold else "Arial.ttf"
    windows_name = "arialbd.ttf" if bold else "arial.ttf"
    linux_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        Path("/System/Library/Fonts/Supplemental") / mac_name,
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / windows_name,
        Path("/usr/share/fonts/truetype/dejavu") / linux_name,
        linux_name,
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    raise OSError("Для подписей графиков нужен шрифт Arial или DejaVu Sans.")


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_size(draw: ImageDraw.ImageDraw, text: str, typeface: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=typeface)
    return box[2] - box[0], box[3] - box[1]


def bar_chart(name: str, title: str, subtitle: str, labels: list[str], values: list[int], note: str) -> Path:
    """Draw a readable horizontal bar chart using only Pillow."""
    width, height = 1500, max(820, 390 + len(labels) * 110)
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 148), fill="#eff6ff")
    draw.text((72, 42), title, font=font(38, True), fill="#102a43")
    draw.text((72, 96), subtitle, font=font(22), fill="#486581")
    max_value = max(values) or 1
    label_x, bar_x, bar_width, start_y = 72, 570, 760, 205
    for index, (label, value) in enumerate(zip(labels, values)):
        y = start_y + index * 105
        draw.text((label_x, y + 17), label, font=font(26, True), fill="#243b53")
        draw.rounded_rectangle((bar_x, y, bar_x + bar_width, y + 52), radius=10, fill="#e5edf5")
        length = round(bar_width * value / max_value)
        if length:
            draw.rounded_rectangle((bar_x, y, bar_x + length, y + 52), radius=10, fill=COLORS[index % len(COLORS)])
        draw.text((bar_x + bar_width + 28, y + 8), str(value), font=font(30, True), fill="#102a43")
    rule_y = height - 130
    draw.line((72, rule_y, width - 72, rule_y), fill="#bcccdc", width=2)
    draw.multiline_text((72, rule_y + 28), textwrap.fill(note, width=82), font=font(22), fill="#334e68", spacing=8)
    output = FIGURES / f"{name}.png"
    image.save(output, format="PNG", optimize=False)
    return output


def grouped_chart(name: str, title: str, subtitle: str, categories: list[str], series: list[tuple[str, list[int], str]], note: str) -> Path:
    width, height = 1500, 900
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 148), fill="#eff6ff")
    draw.text((72, 42), title, font=font(38, True), fill="#102a43")
    draw.text((72, 96), subtitle, font=font(22), fill="#486581")
    left, right, top, bottom = 185, 1380, 670, 250
    max_value = max(value for _, values, _ in series for value in values) or 1
    draw.line((left, top, right, top), fill="#486581", width=3)
    draw.line((left, top, left, bottom), fill="#486581", width=3)
    for tick in range(0, max_value + 1, max(1, max_value // 6)):
        y = top - (top - bottom) * tick / max_value
        draw.line((left, y, right, y), fill="#e5edf5", width=1)
        draw.text((left - 45, y - 12), str(tick), font=font(18), fill="#486581")
    category_width = (right - left) / len(categories)
    unit = min(80, category_width / (len(series) + 2))
    for c_index, category in enumerate(categories):
        center = left + category_width * (c_index + 0.5)
        for s_index, (_, values, color) in enumerate(series):
            x0 = center - len(series) * unit / 2 + s_index * unit
            y0 = top - (top - bottom) * values[c_index] / max_value
            draw.rounded_rectangle((x0, y0, x0 + unit - 12, top), radius=7, fill=color)
            draw.text((x0 + 8, y0 - 32), str(values[c_index]), font=font(20, True), fill="#102a43")
        w, _ = text_size(draw, category, font(24, True))
        draw.text((center - w / 2, top + 27), category, font=font(24, True), fill="#243b53")
    legend_x = 870
    for index, (series_name, _, color) in enumerate(series):
        x = legend_x + index * 240
        draw.rounded_rectangle((x, 174, x + 27, 201), radius=5, fill=color)
        draw.text((x + 40, 174), series_name, font=font(22), fill="#243b53")
    draw.line((72, 730, width - 72, 730), fill="#bcccdc", width=2)
    draw.multiline_text((72, 760), textwrap.fill(note, width=82), font=font(22), fill="#334e68", spacing=8)
    output = FIGURES / f"{name}.png"
    image.save(output, format="PNG", optimize=False)
    return output


def normalize_svg_template(svg: bytes, record_id: str) -> str:
    """Replace the record identifier that is printed inside the fixture SVG."""
    return hashlib.sha256(svg.replace(record_id.encode("utf-8"), b"P000", 1)).hexdigest()


def split_overlap(clean: list[dict], queries: list[dict], templates: dict[str, set[str]]) -> list[dict]:
    rows = []
    for left, right in combinations(("train", "validation", "test"), 2):
        left_cards = [row for row in clean if row["split"] == left]
        right_cards = [row for row in clean if row["split"] == right]
        row = {"split_a": left, "split_b": right}
        for field in ("id", "author", "series", "sha256", "description"):
            row[f"shared_{field}"] = len({x[field] for x in left_cards} & {x[field] for x in right_cards})
        row["shared_svg_templates"] = len(templates[left] & templates[right])
        row["shared_query_texts"] = len(
            {q["text"] for q in queries if q["split"] == left}
            & {q["text"] for q in queries if q["split"] == right}
        )
        rows.append(row)
    return rows


def make_media_examples(raw: list[dict]) -> list[str]:
    """Link the actual archived SVGs, including excluded raw records."""
    details = {
        "P001": "Типичный минималистичный макет, 2 круга",
        "P002": "Типичный детализированный макет, 7 кругов",
        "D001": "Тот же файл и SHA-256, что у P001",
        "X001": "Тот же файл, что у P001. Статус допуска unknown",
        "X003": "Ссылка на P016. Поле description пусто",
    }
    records = {row["id"]: row for row in raw}
    items = []
    for identifier, detail in details.items():
        filename = escape(Path(records[identifier]["image"]).name, quote=True)
        items.append(
            f'<figure><img src="../data/posters/{filename}" alt="Макет {identifier}">'
            f'<figcaption><strong>{identifier}</strong><br>{detail}</figcaption></figure>'
        )
    page = """<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Примеры афиш из исходного реестра</title>
<style>
body{font:18px system-ui;max-width:1100px;margin:36px auto;padding:0 20px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:20px}
figure{margin:0}img{display:block;width:100%;height:240px;object-fit:contain}
figcaption{margin-top:10px}
</style><h1>Примеры афиш из исходного реестра</h1><main>"""
    output = RESULTS / "media_examples.html"
    output.write_text(page + "\n".join(items) + "</main></html>\n", encoding="utf-8")
    return [str(output.relative_to(ROOT))]


def replay_cleanup(raw: list[dict]) -> tuple[list[dict], dict[str, str]]:
    clean, exclusions, accepted_hashes = [], {}, set()
    for row in raw:
        if row["rights_status"] != "demo_allowed":
            exclusions[row["id"]] = "unknown_rights"
        elif not row["description"].strip():
            exclusions[row["id"]] = "empty_description"
        elif row["sha256"] in accepted_hashes:
            exclusions[row["id"]] = "duplicate_image"
        else:
            clean.append(row)
            accepted_hashes.add(row["sha256"])
    return clean, exclusions


def run() -> int:
    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    raw, clean, queries = load_json("raw.json"), load_json("clean.json"), load_json("queries.json")
    with (DATA / "exclusions_lr04.csv").open(encoding="utf-8", newline="") as stream:
        exclusions = list(csv.DictReader(stream))
    required = {"id", "description", "genre", "style", "author", "series", "split", "source", "rights_status", "synthetic", "width", "height", "objects", "image", "sha256"}
    raw_missing_required = [r["id"] for r in raw if set(r) != required or any(r[k] is None for k in required)]
    clean_missing_required = [r["id"] for r in clean if set(r) != required or any(r[k] is None for k in required)]
    svg_errors, hash_mismatches, templates = [], [], defaultdict(set)
    clean_id_set = {row["id"] for row in clean}
    for row in raw:
        # The archived records retain their original project-relative path
        # (demo/data/posters/...). In this self-contained EDA bundle the same
        # SVG files live directly in data/posters/.
        path = DATA / "posters" / Path(row["image"]).name
        try:
            payload = path.read_bytes()
            svg = ElementTree.fromstring(payload)
            valid_dimensions = (int(svg.attrib["width"]), int(svg.attrib["height"])) == (row["width"], row["height"])
            if svg.tag != "{http://www.w3.org/2000/svg}svg" or not valid_dimensions:
                svg_errors.append(row["id"])
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != row["sha256"]:
                hash_mismatches.append(row["id"])
            if row["id"] in clean_id_set:
                templates[row["split"]].add(normalize_svg_template(payload, row["id"]))
        except (FileNotFoundError, ValueError, KeyError, ElementTree.ParseError):
            svg_errors.append(row["id"])
    raw_ids, clean_ids = [r["id"] for r in raw], [r["id"] for r in clean]
    duplicate_raw_ids = len(raw_ids) - len(set(raw_ids))
    duplicate_clean_ids = len(clean_ids) - len(set(clean_ids))
    duplicate_clean_hashes = len(clean) - len({r["sha256"] for r in clean})
    sizes = [r["width"] * r["height"] for r in clean]
    sorted_sizes = sorted(sizes)
    q1, q3 = sorted_sizes[len(sizes) // 4], sorted_sizes[3 * len(sizes) // 4]
    iqr = q3 - q1
    outlier_count = sum(x < q1 - 1.5 * iqr or x > q3 + 1.5 * iqr for x in sizes)
    replayed_clean, replayed_exclusions = replay_cleanup(raw)
    logged_exclusions = {row["id"]: row["reason"] for row in exclusions}
    cleanup_matches = replayed_clean == clean and replayed_exclusions == logged_exclusions
    overlap_rows = split_overlap(clean, queries, templates)
    group_overlap = sum(
        row[f"shared_{field}"] for row in overlap_rows for field in ("id", "author", "series", "sha256")
    )
    unknown_clean = sum(row["rights_status"] != "demo_allowed" for row in clean)
    empty_clean = sum(not row["description"].strip() for row in clean)
    exact_extra_raw = len(raw) - len({row["sha256"] for row in raw})
    valid_genres = {"джаз", "театр", "кино", "выставка", "электроника", "фестиваль"}
    valid_styles = {"минимализм", "детализация"}
    valid_splits = {"train", "validation", "test"}
    unexpected_categories = [
        row["id"] for row in raw
        if row["genre"] not in valid_genres or row["style"] not in valid_styles
        or row["split"] not in valid_splits or row["rights_status"] not in {"demo_allowed", "unknown"}
    ]
    quality_rows = [
        {"check": "Число исходных записей", "actual": len(raw), "expected": 42, "status": "пройдено" if len(raw) == 42 else "ошибка", "details": "raw.json"},
        {"check": "Число очищенных записей", "actual": len(clean), "expected": 36, "status": "пройдено" if len(clean) == 36 else "ошибка", "details": "clean.json"},
        {"check": "Повторяющиеся ID в raw", "actual": duplicate_raw_ids, "expected": 0, "status": "пройдено" if not duplicate_raw_ids else "ошибка", "details": "Проверка уникальности идентификаторов"},
        {"check": "Повторяющиеся ID в clean", "actual": duplicate_clean_ids, "expected": 0, "status": "пройдено" if not duplicate_clean_ids else "ошибка", "details": "Проверка уникальности идентификаторов"},
        {"check": "Повторяющиеся SHA-256 в clean", "actual": duplicate_clean_hashes, "expected": 0, "status": "пройдено" if not duplicate_clean_hashes else "ошибка", "details": "Хеши файлов SVG"},
        {"check": "Неизвестный допуск в clean", "actual": unknown_clean, "expected": 0, "status": "пройдено" if not unknown_clean else "ошибка", "details": "rights_status"},
        {"check": "Пустое description в clean", "actual": empty_clean, "expected": 0, "status": "пройдено" if not empty_clean else "ошибка", "details": "description"},
        {"check": "Неполные поля в raw", "actual": len(raw_missing_required), "expected": 0, "status": "пройдено" if not raw_missing_required else "ошибка", "details": ", ".join(raw_missing_required) or "нет"},
        {"check": "Неполные поля в clean", "actual": len(clean_missing_required), "expected": 0, "status": "пройдено" if not clean_missing_required else "ошибка", "details": ", ".join(clean_missing_required) or "нет"},
        {"check": "Значения вне словаря категорий", "actual": len(unexpected_categories), "expected": 0, "status": "пройдено" if not unexpected_categories else "ошибка", "details": ", ".join(unexpected_categories) or "нет"},
        {"check": "Ошибки SVG или размеров", "actual": len(svg_errors), "expected": 0, "status": "пройдено" if not svg_errors else "ошибка", "details": ", ".join(svg_errors) or "нет"},
        {"check": "Несовпадения SHA-256 с файлами", "actual": len(hash_mismatches), "expected": 0, "status": "пройдено" if not hash_mismatches else "ошибка", "details": ", ".join(hash_mismatches) or "нет"},
        {"check": "IQR-выбросы площади", "actual": outlier_count, "expected": 0, "status": "пройдено" if not outlier_count else "наблюдение", "details": f"Q1={q1}; Q3={q3}; IQR={iqr}"},
        {"check": "Согласованность журнала исключений", "actual": int(cleanup_matches), "expected": 1, "status": "пройдено" if cleanup_matches else "ошибка", "details": "Причина фиксируется первым сработавшим правилом"},
        {"check": "Пересечения ID, авторов, серий и SHA-256 между выборками", "actual": group_overlap, "expected": 0, "status": "пройдено" if not group_overlap else "ошибка", "details": "Подробности в split_overlap.csv"},
    ]
    write_csv(RESULTS / "quality_checks.csv", quality_rows)
    write_csv(RESULTS / "split_overlap.csv", overlap_rows)

    genre_counts = Counter(r["genre"] for r in clean)
    style_by_split = {split: Counter(r["style"] for r in clean if r["split"] == split) for split in ("train", "validation", "test")}
    cards_by_split = Counter(r["split"] for r in clean)
    queries_by_split = Counter(r["split"] for r in queries)
    reasons = Counter(r["reason"] for r in exclusions)
    orientation_by_style = defaultdict(Counter)
    for r in clean:
        orientation_by_style[r["style"]]["Портрет" if r["height"] > r["width"] else "Альбом"] += 1
    figures = []
    figures.append(bar_chart("01_genres", "Жанры очищенного набора", "Вопрос. Представлены ли жанры равномерно?", list(genre_counts), list(genre_counts.values()), "Вывод. По 6 карточек каждого жанра. Веса классов не нужны для этого учебного набора, однако баланс задан генератором."))
    figures.append(grouped_chart("02_styles_splits", "Стили в каждой выборке", "Вопрос. Сбалансированы ли стили в train, validation и test?", ["train", "validation", "test"], [("минимализм", [style_by_split[s]["минимализм"] for s in ("train", "validation", "test")], "#2563a6"), ("детализация", [style_by_split[s]["детализация"] for s in ("train", "validation", "test")], "#d97706")], "Вывод. В каждом split по 6 карточек каждого стиля. Одного равенства объёмов недостаточно для исключения утечки."))
    figures.append(grouped_chart("03_volumes_splits", "Объём карточек и запросов", "Вопрос. Равны ли размеры частей набора?", ["train", "validation", "test"], [("карточки", [cards_by_split[s] for s in ("train", "validation", "test")], "#059669"), ("запросы", [queries_by_split[s] for s in ("train", "validation", "test")], "#7c3aed")], "Вывод. В каждой части 12 карточек и 12 запросов. Группы авторов, серий и точные хеши дополнительно проверены в split_overlap.csv."))
    labels = {"duplicate_image": "точный дубликат изображения", "unknown_rights": "неизвестный допуск", "empty_description": "пустое описание"}
    figures.append(bar_chart("04_exclusions", "Причины исключения исходных записей", "Вопрос. Почему raw сократился с 42 до 36 записей?", [labels[k] for k in reasons], list(reasons.values()), "Вывод. Исключены 3 точных дубля, 2 записи с неизвестным допуском и 1 запись без описания. Причины взаимоисключающие по порядку проверок."))
    figures.append(grouped_chart("05_orientation_style", "Ориентация изображения и стиль", "Вопрос. Есть ли proxy-признак, раскрывающий стиль?", ["минимализм", "детализация"], [("портрет", [orientation_by_style[s]["Портрет"] for s in ("минимализм", "детализация")], "#2563a6"), ("альбом", [orientation_by_style[s]["Альбом"] for s in ("минимализм", "детализация")], "#d97706")], "Риск. Ориентация полностью совпадает со стилем. Размеры и ориентацию нельзя использовать как свидетельство художественного стиля в дальнейшей модели."))
    figures.append(bar_chart("06_raw_problems", "Проблемы исходных записей", "Единица счёта — запись raw. Категории могут пересекаться", ["неизвестный допуск", "пустое описание", "лишние записи по SHA-256"], [sum(r["rights_status"] == "unknown" for r in raw), sum(not r["description"].strip() for r in raw), exact_extra_raw], "У всех шести контрольных записей повторяются изображения. Три записи исключены раньше по допуску или описанию."))
    overlap_labels = [
        ("описания", "shared_description"),
        ("шаблоны SVG", "shared_svg_templates"),
        ("тексты запросов", "shared_query_texts"),
        ("точные файлы по SHA-256", "shared_sha256"),
    ]
    figures.append(bar_chart(
        "07_split_overlap", "Совпадения между выборками",
        "Число общих уникальных значений в паре train и test",
        [label for label, _ in overlap_labels],
        [overlap_rows[1][field] for _, field in overlap_labels],
        "В остальных двух парах результат такой же. Для оценки переноса нужны независимые шаблоны и запросы.",
    ))
    media_paths = make_media_examples(raw)
    chart_meta = [str(path.relative_to(ROOT)) for path in figures]
    summary = {
        "source": "Архив ЛР 4 Учебный набор афиш — ЛР 4.zip, локальная копия data/",
        "input_counts": {"raw": len(raw), "clean": len(clean), "queries": len(queries), "svg_files": len(list((DATA / "posters").glob("*.svg")) )},
        "clean_distribution": {"genres": dict(genre_counts), "styles": dict(Counter(r["style"] for r in clean)), "cards_by_split": dict(cards_by_split), "queries_by_split": dict(queries_by_split)},
        "exclusions": dict(reasons),
        "extra_raw_records_by_sha256": exact_extra_raw,
        "quality_checks_passed": all(r["status"] == "пройдено" for r in quality_rows),
        "quality_check_rows": quality_rows,
        "split_overlap": overlap_rows,
        "known_problem_examples": {"D001": "точный дубль P001 по SHA-256, исключён", "X001": "файл есть, rights_status=unknown, исключён", "X003": "файл есть, description пусто, исключён"},
        "proxy_risk": "Ориентация и размеры полностью связаны со стилем: минимализм 600×800, детализация 800×600.",
        "template_risk": "После замены ID в SVG между каждой парой split совпадают 12 шаблонов, а также все 12 текстов запросов. Разбиение защищает авторов и точные файлы, но не подтверждает перенос на независимые шаблоны.",
        "figures": chart_meta,
        "media_examples": media_paths,
    }
    write_json(RESULTS / "eda_summary.json", summary)
    print(json.dumps({"figures": chart_meta, "media_examples": media_paths, "checks_passed": summary["quality_checks_passed"]}, ensure_ascii=False, indent=2))
    return int(not summary["quality_checks_passed"])


if __name__ == "__main__":
    raise SystemExit(run())
