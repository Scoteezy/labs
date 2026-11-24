# Лабораторная работа № 5

Разведочный анализ набора «Поиск референсов в коллекции афиш». В `data/` лежат исходные материалы ЛР № 4. Реестры, тексты запросов, журнал исключений и 36 SVG взяты из архива «Учебный набор афиш — ЛР 4». Это синтетический набор, созданный [генератором курса](https://github.com/Irina-64/ml-creative-technologies-course/blob/844a315d71ffc11b8462308e158c24fb16253023/demo/project.py). Текст лицензии находится в `LICENSE_LR04.txt`.

## Повторный запуск

Понадобятся Python 3.10 или новее, Pillow и шрифт Arial или DejaVu Sans для подписей графиков. Выполните команды из корня репозитория.

```sh
python -m pip install -r lab05/requirements.txt
python lab05/eda.py
```

Если команда `python` отсутствует, используйте `python3` на macOS или Linux, либо `py` на Windows. После установки Pillow анализ работает локально. Скрипт читает `data/`, повторяет очистку, сверяет её с результатами ЛР № 4, пересчитывает SHA-256 и обновляет `results/`. Поле `image` в исходных записях сохранено как в ЛР № 4. Файлы SVG в этом комплекте лежат в `data/posters/`, поэтому скрипт берёт из поля имя файла.

## Результаты

- [`results/figures/`](results/figures/) — семь PNG-графиков с результатами и интерпретациями.
- [`results/quality_checks.csv`](results/quality_checks.csv) — таблица проверок качества. [`data/exclusions_lr04.csv`](data/exclusions_lr04.csv) содержит исходный журнал исключений, который скрипт проверяет повторным расчётом.
- [`results/split_overlap.csv`](results/split_overlap.csv) — сравнение train, validation и test по ID, авторам, сериям, точным файлам, описаниям, шаблонам и запросам.
- [`results/media_examples.html`](results/media_examples.html) — пять типичных и проблемных записей. Откройте файл локально после клонирования, чтобы отобразились SVG.
- [`results/eda_summary.json`](results/eda_summary.json) — сводка результатов.
- [`data_card_update.md`](data_card_update.md) — обновлённый паспорт набора.
