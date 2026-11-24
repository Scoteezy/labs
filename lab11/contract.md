# Контракт API

`POST /inspect` принимает объект JSON в UTF-8 с `Content-Type: application/json` и одним `Content-Length`. Размер тела до 3 000 000 байт. Дополнительные поля игнорируются.

| Поле | Тип и ограничение |
|---|---|
| `original_base64`, `candidate_base64` | Непустые строки Base64. После декодирования до 1 048 576 байт на картинку. PNG с одним кадром в режиме RGB, каждая сторона до 2048 пикселей. |
| `original_box`, `candidate_box` | Массив из четырёх целых чисел `[left, top, right, bottom]`. Правая и нижняя границы исключаются. Прямоугольник как минимум 4 × 4 и целиком внутри соответствующего изображения. |

Области должны охватывать одни и те же части приблизительно фронтального товара. Подготовка приводит обе к 128 × 128, используя яркость RGB. Соответствие сцен и пригодность результата проверяет дизайнер.

## Ответ HTTP 200

| Поле | Значение |
|---|---|
| `status` | `ok` при штатном расчёте, `fallback` при переходе с экспериментального режима на baseline |
| `assessment` | `passed`, если оценка ниже порога, или `suspected_distortion`, если она равна порогу или выше |
| `mode` и `fallback_reason` | Фактический `baseline` или `candidate`. При переходе указывается `candidate_scoring_failed`, в прочих случаях `null`. |
| `score`, `threshold` | Числа от 0 до 1. Для baseline оценка равна 1 − SSIM с ограничением диапазона. При fallback используются оценка и порог baseline. |
| `model_version`, `dataset_version` | Версии метода и контрольного набора |
| `human_decision_required` | `true` для обоих результатов |
| `input`, `message` | Размеры и координаты областей, краткое пояснение для дизайнерской проверки |

Score измеряет различие фрагментов. Статус `passed` сообщает только о прохождении порога. Решение об использовании рекламного кадра принимает дизайнер.

## Ошибки

JSON ошибки содержит `status=error` или `unavailable`, поле `error` и `human_decision_required=false`.

| HTTP | `error` | Условие |
|---|---|---|
| 400 | `invalid_json`, `invalid_content_length`, `incomplete_body` | Тело или заголовок некорректны или запрос прочитан не полностью |
| 400 | `object_required` | Значение верхнего уровня имеет неподходящий тип |
| 400 | `original_must_be_base64_string`, `original_invalid_base64`, `original_empty`, `original_invalid_image` | Сбой проверки изображения. Для второго используется префикс `candidate_`. |
| 400 | `original_box_must_be_four_integers`, `candidate_box_must_be_four_integers`, `invalid_box` | Неверный тип, размер или положение области |
| 404 | `not_found` | Маршрут отсутствует |
| 413 | `body_too_large` | Тело превышает предел HTTP |
| 413 | `original_too_large`, `original_dimensions_too_large` | Изображение превышает лимит байт или сторон. Для второго используется префикс `candidate_`. |
| 415 | `unsupported_media_type`, `original_must_be_png`, `original_must_be_single_rgb` | Неподходящий Content-Type или формат, режим или число кадров изображения. Для второго используется префикс `candidate_`. |
| 503 | `model_unavailable` | Артефакт решения не прошёл загрузку или штатное вычисление недоступно |

Модуль работает локально, принимает закодированные данные изображения и использует зафиксированные пороги. Внешняя модель и шаблон промпта ему не требуются. [Примеры](results/api_examples.json)
