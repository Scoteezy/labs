# Проверка контракта ЛР 11

Ожидания заданы в [verify.py](verify.py). Фактические ответы получены от локального HTTP-сервера. Полные входы и выходы сохранены в [api_examples.json](results/api_examples.json).

| Случай и вход | Ожидание | Фактический ответ |
|---|---|---|
| `normal`, «афиша крупным акцентом» | 200, `ok`, P001 P011 P027 | 200, `ok`, P001 P011 P027 |
| `trimmed`, тот же запрос с внешними пробелами | 200, те же карточки | 200, `ok`, P001 P011 P027 |
| `synonym_baseline`, «саксофон» в baseline | 200, `no_matches` | 200, `no_matches`, пусто |
| `synonym_candidate`, «саксофон» в candidate | 200, `ok`, P006 P005 P004 | 200, `ok`, P006 P005 P004, совпавший терм «джаз» |
| `unknown_language`, `jazz minimalist` | 200, `no_matches` | 200, `no_matches`, пусто |
| `empty`, строка из пробелов | 400, `empty_query` | 400, `empty_query` |
| `max_length`, 300 букв «я» | 200, `no_matches` | 200, `no_matches`, пусто |
| `long`, 301 буква «я» | 400, `query_too_long` | 400, `query_too_long` |
| `bad_type`, число 42 в `query` | 400, `query_must_be_string` | 400, `query_must_be_string` |
| `missing_query`, пустой объект | 400, `query_must_be_string` | 400, `query_must_be_string` |
| `not_object`, массив | 400, `object_required` | 400, `object_required` |
| `bad_json`, оборванный JSON | 400, `invalid_json` | 400, `invalid_json` |
| `oversize_body`, 4097 байт | 413, `body_too_large` | 413, `body_too_large` |
| `wrong_media_type`, `text/plain` | 415, `unsupported_media_type` | 415, `unsupported_media_type` |
| `unknown_route`, `POST /unknown` | 404, `not_found` | 404, `not_found` |
| `fallback`, обычный запрос при недоступном словаре | 200, `fallback`, baseline, P001 P011 P027 | 200, `fallback`, baseline, P001 P011 P027, `candidate_unavailable` |
| `fallback_no_matches`, английский запрос при недоступном словаре | 200, `no_matches`, причина переключения сохранена | 200, `no_matches`, пусто, `candidate_unavailable` |
| `unavailable`, недоступны базовые веса | 503, `catalog_unavailable` | 503, `catalog_unavailable` |

Для последних трёх сценариев проверка создаёт временную копию конфигурации без хеша соответствующего ресурса. Набор и модели в репозитории остаются доступными для штатного запуска.
