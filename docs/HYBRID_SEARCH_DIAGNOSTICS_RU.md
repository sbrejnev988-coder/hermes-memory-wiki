# Memory Wiki 1.24.5: профильный hybrid recall и диагностика

Этот patch сохраняет существующие SQLite/Qdrant схемы, модели, ACL и weighted RRF. Он исправляет связанный блок поиска, а не добавляет отдельный сервер или новую панель управления.

## Что изменено

- Native profile ContextVars определяют home запроса. Provider с уже открытой connection не переезжает в другой home; маршрут проверяется до внешнего IO.
- Prefetch передаёт контекст в worker. Embedding cache/singleflight и alias capability разделены по владельцу и поколению настроек.
- FTS5/BM25 и embedding/Qdrant формируют независимые списки. Отказ lexical-ветви не отменяет vector-ветвь; LIKE fallback честно отмечается отдельно от FTS и vector.
- ACL и актуальные eligible IDs применяются до SQL LIMIT и Qdrant top-K. Vector-only кандидаты гидратируются из авторитетной SQLite, затем проходят финальные ACL и output guards.
- Внутренний weighted RRF сохраняет отдельные lexical/vector ranks и вклады. Внешний RRF orchestrator остаётся отдельным уровнем.
- Reranker остаётся условным: safe-candidate threshold, exact/secret query guards, deadline и circuit gates не понижены ради демонстрации вызова.
- Исправлены три находки ревью: `claims.topic` квалифицирован в JOIN; positional/keyword/mixed canonical вызовы получают receipts; настоящий embedding timeout не переписывается в обычный failure, включая coalesced waiter.

## Как прочитать результат одного запроса

Обычный canonical ответ `memory_wiki_query` или `memory_wiki_recall` дополнен полем `retrieval_receipt`. Это frozen snapshot данного вызова, не глобальный «последний запрос».

Основные поля:

- `trace_id` и `entrypoint` связывают ответ с конкретным запросом; расширенные поиски имеют собственные ordinal.
- `identity` содержит фактические importer/request/provider homes, module origin и connection identity. Saved path или Git HEAD сами по себе не доказывают loaded revision.
- `searches` показывает lexical, embedding, Qdrant, fusion и rerank stages: execution, empty result, timeout, failure или skip с причиной, collection/cache и elapsed metadata.
- `fusion.items` содержит отдельные ranks/contributions только для безопасно выданных IDs. Наличие положительного `rrf_score` без реально выполненных обеих ветвей не означает полноценный hybrid.
- `outer_fusion` — отдельный `orchestrator_rrf`; его нельзя выдавать за внутреннее FTS/vector объединение.
- `final` сообщает число emitted claims и сохранённую защиту выдачи.

Receipt не содержит query text/hash, snippets, credential values, provider response bodies, векторы или скрытые IDs. Во внутреннем логе может быть отказ, но он не должен становиться видимым claim или разрешением на IO.

## Установка и профильные targets

Выбирайте exact primary PIN из принятого commit для `default`, metadata-only secondary PIN для остальных участников shared PM. Вторичный вариант отличается от primary только существующим `pyproject.toml`: runtime, tests и docs одинаковы. Сохраните собственные URL/PIN через штатный installer и проверяйте фактические installed bytes. Не копируйте `.env`, credentials, alias или caller identity из соседнего профиля.

Новая версия файла не заменяет уже загруженный Python-модуль. Reload/restart действующего gateway требует отдельного согласования, особенно при multiplexing. После разрешённой загрузки подтверждайте identity и canonical recall каждого обслуживаемого профиля.

Пустой или общий namespace не исправляется слепым назначением root alias. Сначала сверьте разрешённые ID-наборы SQLite/FTS/Qdrant и target registry. Для явно согласованной полной переиндексации используйте штатный public инструмент, отдельный stage budget и сохранение старых targets. Блокированный foreign-vector transfer нельзя обходить подменой caller или прямой записью в SQLite.

## Проверки и ограничения

Для исправленного source сохранены receipts **58 уникальных cases**: 44 профильных/cache/hybrid и 14 новых F1/F2/F3 regressions/controls. Это агрегат шести выбранных завершившихся child runs с нулём failures/errors/skips, **не один новый зелёный прогон на 58 cases**. Первоначальный нормальный 53-case запуск с 7 setup failures и отказ `socket.connect` сохранены. Перепроверялись только затронутые setup-файлы.

SDK/MRO и опубликованный guard проверены в synthetic home; HTTP/health replies явно синтетические. Один historical alias-loader файл использует unavailable-health fixture при сохранённом network fence. Ни этот suite, ни source review не доказывают authenticated provider execution, загрузку текущего gateway, всю историю восстановления или готовность GitHub Release.

При живой приёмке требуется:

1. Смысловой перефраз без lexical/LIKE match возвращает vector-only запись.
2. Смешанный запрос даёт реальные FTS и vector hits с раздельными RRF contributions.
3. Отказ одной ветви обозначен как деградация и не скрывает исправную вторую.
4. Reranker исполняется только при выполненных штатных условиях; cache/skip/failure различимы.
5. Межпрофильный caller, cache и target не расширяют ACL; текущая privacy authority сохраняется.

Отсутствие обязательной native trust-зависимости или неподтверждённая policy — STOP для live admission, не повод отключать защиту. В рамках этого patch не менялись модели, thresholds, privacy authority, DB schema или настройки других профилей.
