# Повышение качества Hermes Memory Wiki — 21 сентября 2026 года

Релиз: **v1.23.0**.

## Краткий вывод

Memory Wiki уже был сильнее простого vector store: SQLite оставался источником истины, у claims были происхождение, временная валидность и области видимости, а FTS/Qdrant дополнялись графами, журналом и резервными копиями. Главный разрыв качества находился между диалогом и этой структурой: слишком мало реплик становилось пригодной памятью, разные типы памяти искались разными маршрутами, а обратная связь после recall почти не влияла на жизненный цикл.

В этом обновлении закрыты основные архитектурные разрывы:

- полный низкодоверенный эпизодический журнал реплик с парным контекстом user/assistant;
- отдельный семантический индекс эпизодов в Qdrant с SQLite как источником истины;
- планировщик recall для русского и английского языков;
- единый evidence-first recall поверх claims, эпизодов, событий, наблюдений и графа;
- append-only event ledger и производные наблюдения с неизменяемыми версиями и ссылками на доказательства;
- grounded-извлечение claims через OpenRouter и ограниченное автоматическое обогащение графа;
- явные исходы recall вместо ошибочного вывода «не использовано = нерелевантно»;
- TTL/LRU/single-flight cache для эмбеддингов;
- серверные ACL-фильтры Qdrant и повторная авторизация по SQLite;
- исправления temporal supersession и лексического RRF;
- воспроизводимый полный probe на 500 вопросах LongMemEval.
- числовые стабильные FTS docid и инкрементальные счётчики удержания для больших журналов;
- опциональную очередь фоновых задач с lease, бюджетами и восстановлением по идентификаторам;
- host-only OCR-доказательства с привязкой к исходному изображению и удалением по источнику.

Это создаёт техническую основу для конкуренции с ведущими memory-системами. Звание «топ-1» требует общего end-to-end QA-протокола с той же моделью ответа, judge, бюджетом контекста, стоимостью и задержкой. Текущий измеренный результат относится к извлечению доказательств и не подменяет такой рейтинг.

## Что было не так

| Разрыв | Практическое последствие | Реализация |
|---|---|---|
| Claims покрывали малую часть диалога | Агент забывал корректные факты, которые extractor не превратил в claim | Эпизоды сохраняют guard-safe пары реплик и возвращают их с цитатами |
| Лексический rank присваивался широким fallback-кандидатам | Нерелевантные свежие записи получали искусственное преимущество | RRF начисляется только реальным BM25/FTS попаданиям |
| Temporal supersession мог пересекать ACL-разделы | Изменение в одном разделе могло повлиять на другой | Slot и partition стали частью ключа supersession |
| Qdrant получал недостаточный payload | ACL применялся поздно и требовал лишней гидратации | Версионированный payload и server-side owner/scope filter, затем авторитетная проверка SQLite |
| Семантический путь эпизодов отсутствовал | Перефразированные воспоминания находились хуже | Отдельная manifest-bound коллекция эпизодов, hybrid RRF и безопасный fallback |
| Источники памяти искались разными инструментами | Модель должна была угадывать правильный маршрут | `memory_wiki_recall` объединяет источники и возвращает стабильные `[M:*]` citation IDs |
| Повторяющиеся события не формировали устойчивое знание | Система не могла накапливать подтверждения без LLM-summary | Детерминированные observations с evidence links, версиями и confidence по независимым turn IDs |
| Session extractor мог принять неподтверждённый или плохо привязанный вывод | Ошибочная долговременная память | Строгий JSON schema, точная цитата, speaker/index grounding, фильтры plans/injection/secrets |
| Граф требовал ручного запуска | Связи отставали от новых claims | Opt-in auto enrichment только новых grounded relation-like claims с caps/deadline |
| Молчание после recall считалось негативной обратной связью | Полезные записи теряли вес без доказательства | Нейтральный retrieval и явные outcomes: used/helpful/irrelevant/contradicted/harmful |
| Повторные embedding-запросы тратили сеть и время | Высокая задержка и стоимость | Нормализованный query cache, точный document cache, fingerprint и single-flight |

## Измеренный эффект

Полный offline production-path probe обработал 500 официальных вопросов LongMemEval, 10 960 реплик и 896 размеченных gold turns. Каждый вопрос выполнялся в отдельной временной базе и отдельном bot partition. Использовались реальные `sync_turn`, guard и production `query_episodes`, но без генерации ответа, OpenRouter embeddings и Qdrant.

| Метрика | Только 8 claims | 3 claims + 5 эпизодов |
|---|---:|---:|
| Вопросы хотя бы с одним gold source | 0,63% | **83,92%** |
| Вопросы со всеми gold sources | 0,00% | **56,78%** |
| Найденные gold turns | 0,33% | **62,39%** |
| Episode search p50 | — | **6,80 мс** |
| Episode search p95 | — | **9,67 мс** |

Дополнительный изолированный замер embedding cache на 20 одинаковых циклах дал 1 HTTP-вызов вместо 20 и 52,58 мс вместо 1006,22 мс: на повторной нагрузке это примерно 19,1 раза быстрее и на 95% меньше сетевых вызовов. Первая удалённая семантическая выдача всё ещё зависит от провайдера и сети.

Финальный изолированный масштабный замер с **1 000 000 синтетических событий** прошёл на реальной схеме SQLite/FTS с квотами по разделам и производственном API запроса. База заняла 991 МБ; редкий запрос имел p50 0,76 мс и p95 0,89 мс, частый p50 68,89 мс и p95 69,42 мс, холодный запуск 521 мс. Удаление 1 000 записей заняло 74 мс, `quick_check=ok`. Вставка заняла 179 секунд (5573 строк/с) без параллельной нагрузки. Это синтетическая пакетная вставка, которая не включает стоимость guard, OpenRouter, Qdrant или модели ответа. Скрипт: [`benchmarks/scale_event_ledger.py`](benchmarks/scale_event_ledger.py). Отдельный замер FTS эпизодов на 100 000 строк удалил 2 000 записей за 193 мс, p95 одной операции 0,18 мс; стабильность docid после `VACUUM` проверена.

Машиночитаемый результат: [`benchmarks/oracle_episode_8slot_full_planned.json`](benchmarks/oracle_episode_8slot_full_planned.json). Provenance: [`benchmarks/oracle_episode_8slot_full_planned.provenance.json`](benchmarks/oracle_episode_8slot_full_planned.provenance.json). Скрипт: [`benchmarks/full_oracle_episode_probe.py`](benchmarks/full_oracle_episode_probe.py). Дизайн и ограничения: [`EPISODIC-FALLBACK-DESIGN.md`](EPISODIC-FALLBACK-DESIGN.md).

## Архитектура после обновления

```text
host sync_turn / memory write / session end
    ├─ guard-safe episodic turns ── FTS + Qdrant episode collection
    ├─ append-only events ───────── event evidence links
    │                                  └─ deterministic observations + immutable versions
    ├─ grounded OpenRouter extractor ─ claims ─ FTS + Qdrant claim collection
    │                                      └─ bounded auto graph enrichment
    └─ journal / audit / scoped backup

user memory query
    → multilingual recall plan and bounded expansions
    → claims + episodes + events + observations (+ graph in deep mode)
    → source-specific ACL and guard checks
    → deterministic reciprocal-rank fusion
    → bounded evidence, trust metadata, timestamps and stable citations
    → abstain/clarify policy when admissible evidence is absent
```

Каждый производный слой сохраняет ссылку на источник. SQLite остаётся авторитетным хранилищем; Qdrant ускоряет поиск, но не решает ACL и не определяет итоговую видимость. Наблюдения не генерируют новый текст: текущая формулировка и каждая версия копируют проверенное событие-представитель, а evidence IDs показывают основание.

## Сравнение с ведущими подходами

| Система/подход | Сильная сторона | Позиция Memory Wiki после обновления |
|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Простая интеграция, multi-signal retrieval, опубликованные production benchmark claims | Сопоставимый гибридный поиск; подробнее provenance, локальная изоляция, journal/recovery и несколько доменных графов. Не хватает общего QA-прогона на одной модели |
| [Hindsight](https://github.com/vectorize-io/hindsight) | Retain/recall/reflect и обучаемые observations/mental models | Event ledger и evidence-backed observations закрывают базовый слой обучения. Hindsight зрелее в опубликованном end-to-end benchmark и управляемом сервисе |
| [Graphiti](https://github.com/getzep/graphiti) | Temporal knowledge graph с episodes и provenance | Memory Wiki теперь соединяет episodes, temporal claims и graph provenance, а также имеет code/document graphs. Graphiti сильнее как специализированный масштабируемый temporal graph framework |
| [Letta MemFS](https://github.com/letta-ai/letta-docs-md/blob/main/concepts/memfs/index.md) | Git-backed редактируемая память и удобная файловая модель | Wiki/pages, journal и scoped backups дают прозрачность, а Qdrant/FTS включены в основной retrieval. MemFS проще вручную инспектировать и переносить как обычный Git repo |

Главное отличие Memory Wiki — сочетание evidence-first recall, строгих bot/chat/project разделов, локального authoritative store, восстановления, secret-aware guard, диалоговой памяти и графов кода/документов. Главный оставшийся разрыв к рыночному лидерству — публично воспроизводимое end-to-end качество на стандартных наборах и реальная эксплуатационная статистика.

## Что ещё нужно для доказанного лидерства

1. **Общий QA benchmark.** Прогнать LongMemEval, LoCoMo, BEAM и LongMemEval-V2 одной моделью ответа и judge, зафиксировать prompts, token budget, latency, стоимость, abstention и confidence intervals.
2. **Мультимодальность.** Host-only OCR evidence, source registry и каскадное удаление реализованы. Для реальных изображений Hermes должен предоставить доверенный attachment/OCR hook; плагин не читает пиксели и не запускает vision-модель сам.
3. **Подлинный trust core.** Установить и аттестовать `hermes_trust_core`, затем включить `HERMES_SECURITY_STRICT=1`. Локальный guard остаётся полезным fallback, но не равен подписанной доверенной границе.
4. **Асинхронная консолидация.** Durable очередь с lease, retry, dead-letter, бюджетами и ограниченным восстановлением реализована, но по умолчанию выключена. Её event-задачи принимают только chat/пустой project, чтобы не расширить ACL; для профильного проекта требуется отдельный безопасный контекст исполнителя.
5. **Онлайн evaluation loop.** Агрегированные recall latency/hit/error и явная обратная связь реализованы. Citation precision, first-token impact и стоимость модели требуют дополнительных сигналов Hermes, которые плагин не получает.
6. **Масштабные профили.** 1M событий проверен изолированно; 10M, длительная конкуренция с WAL, эксплуатационный RTO и отказоустойчивость Qdrant требуют отдельных прогонов.
7. **Публичный compatibility contract.** Версионированные MCP-схемы, migration ledger, fail-closed будущее user_version и release verifier внедрены. Совместимость с внешними клиентами ещё требует полевых проверок.

## Режимы качества

- `fast`: локальный FTS, минимальная задержка, без event/graph expansion.
- `auto`: гибрид claims + episodes + events + observations, ограниченный контекст по умолчанию.
- `deep`: те же источники плюс graph traversal и больший исследовательский охват.

Для повседневного Hermes рекомендуется `auto`. `deep` нужен для расследования связей и сложных многошаговых вопросов. Ограничения `max_results`, `max_chars`, TTL и scope являются защитой качества и стоимости; они настраиваются и не являются жёстким пределом продукта.

## Критерий готовности релиза

Релиз считается готовым после одновременного выполнения всех условий:

- полный `pytest` проходит;
- schema cache и `plugin.yaml` совпадают с runtime tools;
- `py_compile`, `git diff --check` и release verifier проходят;
- security diff scan не содержит открытых reportable findings;
- базы всех профилей имеют согласованные backup и `quick_check=ok`;
- Qdrant collections переиндексированы новым payload manifest и alias переключён только после reconciliation;
- каждый gateway перезапущен на той же версии и проходит read-only smoke;
- секреты не входят в diff, отчёты, benchmark artifacts и логи.
