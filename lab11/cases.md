# Проверка сложных случаев

Проверка выполняет реальные HTTP-запросы к временным локальным серверам. Полные входы, ожидания и фактические ответы сохранены в [api_examples.json](results/api_examples.json).

| Случай | Ожидание | Фактический ответ |
|---|---|---|
| `normal_passed` | Допустимое изменение фона | 200, `passed` |
| `normal_suspected` | Изменён текст упаковки | 200, `suspected_distortion` |
| `forced_candidate` | Использован экспериментальный режим | 200, `mode=candidate`, `suspected_distortion` |
| `not_object` | Массив вместо объекта отклонён | 400, `object_required` |
| `invalid_json` | Оборванный JSON отклонён | 400, `invalid_json` |
| `invalid_base64` | Неподходящая строка отклонена | 400, `original_invalid_base64` |
| `wrong_format` | JPEG вместо PNG отклонён | 415, `original_must_be_png` |
| `invalid_box` | Область за пределами изображения отклонена | 400, `invalid_box` |
| `wrong_media_type` | Запрос text/plain отклонён | 415, `unsupported_media_type` |
| `unknown_route` | Маршрут не найден | 404, `not_found` |
| `body_too_large` | Заявленное тело больше лимита | 413, `body_too_large` |
| `unavailable` | При отсутствующем решении оценка недоступна | 503, `model_unavailable` |
| `candidate_fallback` | При контролируемом сбое используется baseline | 200, `fallback`, `mode=baseline`, `candidate_scoring_failed` |

Корректные пары созданы генератором ЛР 4. Проверка показывает поведение интерфейса на контролируемых входах. Отдельные модульные тесты проверяют двойной сбой вычисления и вызов сервера в новом процессе.
