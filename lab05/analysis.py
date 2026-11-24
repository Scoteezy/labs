"""Reproducible quality checks and EDA for packaging-image pairs."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "lab04" / "data"
PAIRS = DATA / "pairs.json"
SPLIT = ROOT / "lab04" / "split.json"
HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FIG = OUT / "figures"
REQUIRED = {"pair_id", "product_id", "family_id", "original", "candidate",
            "original_box", "candidate_box", "label", "defect_type",
            "variation", "source", "rights_status"}
SPLITS = ("train", "validation", "test")
DEFECTS = ("none", "text", "logo", "shape")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def box_ok(box, size):
    return (isinstance(box, list) and len(box) == 4 and
            all(type(v) is int for v in box) and
            0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])


def add_split(rows, split):
    memberships = {family: name for name, families in split.items() for family in families}
    return [{**row, "split": memberships.get(row["family_id"], "missing")} for row in rows]


def inspect(rows):
    findings, hashes = [], defaultdict(list)
    ids = Counter(row.get("pair_id") for row in rows)
    for row in rows:
        pair = str(row.get("pair_id", "missing"))
        missing = sorted(REQUIRED - set(row))
        if missing:
            findings.append(("required_fields", pair, "fail", ",".join(missing)))
            continue
        if ids[pair] != 1:
            findings.append(("unique_pair_id", pair, "fail", "duplicate identifier"))
        if row["label"] not in (0, 1) or row["defect_type"] not in DEFECTS:
            findings.append(("label_schema", pair, "fail", "unsupported label or type"))
        if row["label"] != int(row["defect_type"] != "none"):
            findings.append(("label_consistency", pair, "fail", "label and defect_type conflict"))
        if row["source"] != "controlled_synthetic" or row["rights_status"] != "project_generated":
            findings.append(("provenance", pair, "fail", "unexpected source or rights"))
        for side in ("original", "candidate"):
            path = ROOT / row[side]
            try:
                with Image.open(path) as image:
                    image.load()
                    if image.mode not in ("RGB", "RGBA"):
                        findings.append(("image_mode", pair, "fail", side + "=" + image.mode))
                    if not box_ok(row[side + "_box"], image.size):
                        findings.append(("box_bounds", pair, "fail", side + " box invalid"))
                hashes[(side, sha(path))].append(pair)
            except (OSError, ValueError) as error:
                findings.append(("image_readable", pair, "fail", side + ": " + str(error)))
    for (side, value), pairs in hashes.items():
        if side == "candidate" and len(pairs) > 1:
            findings.append(("candidate_hash_duplicate", ",".join(pairs), "fail", value))
    return findings


def counter(rows, field):
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def plot_bar(path, title, values, xlabel, colors=None):
    labels, values = list(values), list(values.values())
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    bars = axis.bar(labels, values, color=colors or "#4F7CAC")
    axis.bar_label(bars, padding=3)
    axis.set(title=title, xlabel=xlabel, ylabel="Число пар")
    axis.set_ylim(0, max(values, default=1) * 1.2)
    axis.grid(axis="y", alpha=.2)
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot_split(path, rows):
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    lower = np.zeros(3)
    for label, color in (("0", "#4F7CAC"), ("1", "#D1495B")):
        values = np.array([sum(row["split"] == split and str(row["label"]) == label
                               for row in rows) for split in SPLITS])
        bars = axis.bar(SPLITS, values, bottom=lower, label="label=" + label, color=color)
        axis.bar_label(bars, label_type="center", fmt="%d")
        lower += values
    axis.set(title="Классы по групповому split", ylabel="Число пар")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot_variation(path, rows):
    grouped = defaultdict(Counter)
    for row in rows:
        grouped[row["variation"]][str(row["label"])] += 1
    labels = sorted(grouped)
    x = np.arange(len(labels))
    zero = [grouped[name]["0"] for name in labels]
    one = [grouped[name]["1"] for name in labels]
    figure, axis = plt.subplots(figsize=(8.8, 4.2))
    axis.bar(x, zero, color="#4F7CAC", label="label=0")
    axis.bar(x, one, bottom=zero, color="#D1495B", label="label=1")
    axis.set_xticks(x, labels, rotation=20, ha="right")
    axis.set(title="Вариации сцены по метке", ylabel="Число пар")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot_area(path, rows):
    values = {"0": [], "1": []}
    for row in rows:
        left, top, right, bottom = row["candidate_box"]
        values[str(row["label"])].append((right-left) * (bottom-top))
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    boxes = axis.boxplot([values["0"], values["1"]], tick_labels=["label=0", "label=1"],
                         patch_artist=True)
    for patch, color in zip(boxes["boxes"], ("#4F7CAC", "#D1495B")):
        patch.set_facecolor(color)
    axis.set(title="Площадь области товара по метке", ylabel="Пиксели")
    axis.grid(axis="y", alpha=.2)
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def media_sheet(path, rows):
    selected = []
    for label in (0, 1):
        for defect in ("none", "text", "logo", "shape"):
            item = next((row for row in rows if row["label"] == label and
                         row["defect_type"] == defect), None)
            if item and item not in selected:
                selected.append(item)
    selected = selected[:4]
    sheet = Image.new("RGB", (960, 260 * len(selected)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(selected):
        top = index * 260
        for x, side in ((0, "original"), (300, "candidate")):
            with Image.open(ROOT / row[side]) as source:
                size = source.size
                preview = source.convert("RGB").resize((240, 240))
            sheet.paste(preview, (x, top+18))
            left, upper, right, lower = row[side+"_box"]
            draw.rectangle((x+left*240/size[0], top+18+upper*240/size[1],
                            x+right*240/size[0], top+18+lower*240/size[1]),
                           outline="#D1495B", width=2)
        draw.text((0, top), "original", fill="black")
        draw.text((300, top), "candidate", fill="black")
        draw.text((560, top+25), row["pair_id"], fill="black")
        draw.text((560, top+50), "label=" + str(row["label"]), fill="black")
        draw.text((560, top+75), "defect=" + row["defect_type"], fill="black")
    sheet.save(path)
    return [row["pair_id"] for row in selected]


def write_reports(rows, findings, examples):
    OUT.mkdir(parents=True, exist_ok=True)
    warnings = []
    for field in ("variation", "split"):
        for value, labels in sorted(_field_labels(rows, field).items()):
            if len(labels) == 1:
                warnings.append(("proxy_label_association", "*", "warn",
                                 field + "=" + value + " only label=" + str(next(iter(labels)))))
    with (OUT / "quality_checks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("check", "pair_id", "status", "detail"))
        writer.writerow(("pairs_total", "*", "pass", len(rows)))
        writer.writerow(("families_total", "*", "pass", len({row["family_id"] for row in rows})))
        writer.writerow(("split_coverage", "*", "pass" if all(row["split"] in SPLITS for row in rows)
                         else "fail", json.dumps(counter(rows, "split"), ensure_ascii=False)))
        writer.writerows(findings + warnings)
    failed = sum(item[2] == "fail" for item in findings)
    warning_text = [row[3] for row in warnings]
    (HERE / "quality_review.md").write_text(_review(rows, failed, warning_text, examples), encoding="utf-8")
    (HERE / "data_card_update.md").write_text(_card(rows, failed), encoding="utf-8")
    summary = {
        "dataset_version": "1.0",
        "pairs": len(rows),
        "families": len({row["family_id"] for row in rows}),
        "label_counts": {key: int(value) for key, value in counter(rows, "label").items()},
        "split_counts": {key: int(value) for key, value in counter(rows, "split").items()},
        "defect_type_counts": {key: int(value) for key, value in counter(rows, "defect_type").items()},
        "schema_or_file_failures": failed,
        "proxy_warnings": warning_text,
        "media_examples": examples,
        "figures": [
            "01_split_labels.png", "02_defect_types.png", "03_variations.png",
            "04_roi_area.png", "05_families_by_split.png", "06_media_examples.png",
        ],
        "scope": "controlled_synthetic_pilot",
    }
    (OUT / "eda_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _field_labels(rows, field):
    values = defaultdict(set)
    for row in rows:
        values[str(row[field])].add(row["label"])
    return values


def _review(rows, failed, warnings, examples):
    labels, splits = counter(rows, "label"), counter(rows, "split")
    return f"""# Проверка качества данных ЛР 5

EDA анализирует контролируемый синтетический пилот ЛР 4. Он подтверждает работоспособность
конвейера, но не качество на реальных результатах генеративного редактирования.

| Проверка | Результат | Решение |
|---|---:|---|
| Число пар | {len(rows)} | Готовить к ЛР 6 после проверки CSV |
| Семейства | {len({row["family_id"] for row in rows})} | Держать семьи целиком в одном split |
| Label 0 / 1 | {labels.get("0", 0)} / {labels.get("1", 0)} | Считать F1 и полноту критичных изменений |
| Split train / validation / test | {splits.get("train", 0)} / {splits.get("validation", 0)} / {splits.get("test", 0)} | Выбирать порог только по validation |
| Ошибки схемы и файлов | {failed} | {"Исправить до подготовки." if failed else "Проверка пройдена."} |
| Возможные proxy-связи | {len(warnings)} | Проверить баланс вариаций до обобщающих выводов |

## Вопросы анализа

1. Оба класса по split показаны на 01_split_labels.png.
2. Типы дефектов показаны на 02_defect_types.png.
3. Вариации сцены по метке показаны на 03_variations.png.
4. Размер области товара по метке показан на 04_roi_area.png.
5. Семейства по split показаны на 05_families_by_split.png.
6. Схема, PNG, границы и точные дубли перечислены в results/quality_checks.csv.
7. Пары {", ".join(examples)} представлены на 06_media_examples.png.

Красная рамка обозначает область товара. Примеры содержат одну допустимую вариацию и
контролируемые изменения текста, логотипа и формы. Они помогают проверить инструкцию
разметки, но не считаются независимой оценкой модели.

## Ограничения

Изображения созданы процедурно. Пути, идентификаторы, split, метка, тип дефекта и размеры
области товара не передаются модели. Отдельные имена вариаций встречаются только с одной
меткой. Это proxy-риск пилота. Следующая версия должна сочетать каждый фон и свет с обоими
классами. Реальные данные с другим светом, ракурсами, бликами, перекрытиями и результатами
сторонней генерации требуют новой проверки.
"""


def _card(rows, failed):
    return f"""# Обновление Data Card после ЛР 5

Версия 1.0 содержит {len(rows)} пар исходного и изменённого рекламного изображения.
Метка 1 означает контролируемое критичное изменение текста, логотипа или формы. Метка 0
означает допустимую вариацию сцены при сохранённом товаре.

Проверки структуры, PNG, границ областей, идентификаторов, меток и группового split
{"пройдены" if not failed else "не пройдены"}. Подробности находятся в results/quality_checks.csv.
Набор не содержит персональных данных или внешних рекламных материалов. До практического
применения нужны реальные согласованные данные и независимая разметка.
"""


def run():
    payload = read(PAIRS)
    if payload.get("dataset_version") != "1.0" or not isinstance(payload.get("pairs"), list):
        raise ValueError("Ожидался pairs.json версии 1.0")
    split_payload = read(SPLIT)
    split = {name: split_payload.get(name) for name in SPLITS}
    if set(split) != set(SPLITS) or any(not isinstance(families, list) for families in split.values()):
        raise ValueError("split.json должен содержать train, validation и test")
    rows = add_split(payload["pairs"], split)
    findings = inspect(rows)
    family_split = defaultdict(set)
    for row in rows:
        family_split[row["family_id"]].add(row["split"])
    for family, names in family_split.items():
        if len(names) != 1 or "missing" in names:
            findings.append(("family_split", family, "fail", str(sorted(names))))
    FIG.mkdir(parents=True, exist_ok=True)
    plot_split(FIG / "01_split_labels.png", rows)
    plot_bar(FIG / "02_defect_types.png", "Типы контролируемых изменений",
             counter(rows, "defect_type"), "Тип изменения",
             ["#4F7CAC", "#D1495B", "#E9A23B", "#7A5EA6"])
    plot_variation(FIG / "03_variations.png", rows)
    plot_area(FIG / "04_roi_area.png", rows)
    plot_bar(FIG / "05_families_by_split.png", "Семейства товаров по split",
             {name: len(split[name]) for name in SPLITS}, "Split")
    examples = media_sheet(FIG / "06_media_examples.png", rows)
    write_reports(rows, findings, examples)
    return {"pairs": len(rows), "figures": 6, "findings": len(findings)}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
