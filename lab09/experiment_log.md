# Журнал эксперимента LR09-E01

| Этап | Время по Москве | Команда или артефакт | Результат |
|---|---|---|---|
| Фиксация протокола | 24.11.2026 11:59:45 | [Коммит протокола](https://github.com/Scoteezy/labs/commit/217920a14ea54b176c631a75d11fc5134535bf65) | Зафиксированы H1, словарь 1.0 и критерии |
| Validation | 24.11.2026 12:01:03 | `python3 -m lab09.experiment validation` · [Решение JSON](results/validation_decision.json) | NDCG@3 0,238525 → 0,857373. H1 выполнена на validation |
| Фиксация выбора | 24.11.2026 12:01:34 | [Коммит решения](https://github.com/Scoteezy/labs/commit/6d5dac87c8d5165387b289b0e0933e1bd2f32099) | Для test выбран режим жанровой нормализации |
| Test | 24.11.2026 12:01:34 | `python3 -m lab09.experiment test` · [Результат JSON](results/test_summary.json) | NDCG@3 0,355740. Качество на отложенной группе ниже 0,70 |

Команда test выполнена после успешного создания коммита с решением. Оба действия попали в одну секунду. Исполнитель прогона и расчётов — Codex. Использовался CPython 3.9.6 на macOS arm64, Unicode 13.0.0 и стандартная библиотека. Случайные операции отсутствуют. [Окружение](results/environment.json) · [Код запуска](experiment.py) · [Конфигурация](config.json)

## Контрольные суммы SHA-256

| Артефакт | SHA-256 |
|---|---|
| [IDF baseline](../lab06/data/idf.json) | `e8b846746c618ab93b6f65edf2c42568f42030888bab39d18865e87243607260` |
| [IDF кандидата](results/candidate_idf.json) | `e3503434a993dbe1b1e09c48fd1d3550f75df437b657689d7720eb6c3e6cd697` |
| [Словарь 1.0](lexicon.json) | `d3e9d4d8466ececd9f31f0efe8ff853814881f7c0a37bcd67ec49e645fd1c0f5` |
| [Решение перед test](results/validation_decision.json) | `1b9480d3fdad61e773d5ad2f00b1167f9e2becf89f9a7e2f6d6647af63397d2c` |

Веса кандидата отличаются из-за пересчёта частот документов после замен на train. Код сверяет повторно рассчитанный IDF baseline с ЛР 6, затем проверяет совпадение трёх отчётов baseline с ЛР 7. Для результата test сохраняется SHA-256 решения по validation. [Попарные результаты и интерпретация](comparison.md) · [Итоговое решение](decision.md)
