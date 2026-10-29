# Наблюдение сохранённого локального документа (P1, plugin-only)

## Внутренний вызываемый интерфейс

```python
from memory_wiki import source_connectors

# provider уже инициализирован владельцем; source_key получен от прежнего
# успешного sync_local_file. Этот вызов НЕ делает sync/ingest.
result = source_connectors.observe_local_file(provider, {
    "source_key": registered_source_key,
    # Необязательные scope_id/repository_id лишь сужают действующий scope.
})
```

Это реальная синхронная Python-операция, подключённая к небольшому модулю
`source_file_observation.py`. Нового MCP/tool dispatch, публичной схемы,
регистрации SDK, фонового worker/daemon/watch или установки нет. Не вызывать
её из non-blocking `sync_turn`: она синхронно читает файл. Scheduler,
coalescing событий, opt-in и автоматическая переиндексация — отдельный блок.

Принимаются только `source_key`, `scope_id`, `repository_id`. `path`, `embed`,
`autoindex` и неизвестные поля отклоняются. Путь берётся исключительно из
уже зарегистрированного активного `local_file` connector текущего владельца.
Обычный document без такого connector, отсутствующая/чужая/удалённая
регистрация и неоднозначные несколько links не дают права читать файл.
Это намеренно более узкий интерфейс, чем ingest или обход папки.

## Авторизация до проверки файла

1. Требуются уже существующий `sqlite3.Connection`, точное совпадение
   `provider._conn is provider._owned_conn`, штатный provider lock,
   lifecycle `ready`/`idle`, отсутствие pending transaction/quarantine и
   известная `database_instance_id`. Нет подключения/создания SQLite,
   schema bootstrap, replay или ленивого получения identity из metadata.
2. Используются настоящий `_document_profile_scope(provider.home)`,
   `_document_access_scope` через `_scope`, `_owner`, `_assert_source_access`,
   `_assert_connector_owner(..., _conn=conn)` и исходный
   `_document_disclosure`/`provider._retain_read_fence`.
3. Сохраняются ORIGINAL actor (home/bot/session/project), db path/identity,
   connection и полные изображения connector/source/revision. Штатный fence
   также сохраняет SQL epochs, namespace, erasure/config/context authority.
   Они повторно проверяются до чтения, между проходами, после I/O и перед
   возвратом. Изменение не становится новым baseline.
4. Только затем проверяются точный зарегистрированный spelling, настоящий
   `_source_id`, URI и `_source_key(..., _existing_only=True)`. Новый private
   флаг `_source_key` запрещает исторический lazy metadata fallback только
   для этого reader; прежние writer callers и формула identity не изменены.
5. Используются действующие `_allowed_path`, `_open_allowed_file` и
   `_file_identity`. Не добавлен второй native/unsafe opener. Windows
   HANDLE/no-reparse/final-root и POSIX descriptor/no-follow ветви остаются
   прежними. Known file-ID, принадлежащий другому source в существующем
   document identity ledger, отклоняется до чтения байтов на обеих ОС.
   На Windows дополнительно вызывается настоящий
   `_assert_ingest_path_alias_owner` с `opened_identity` открытого FD,
   исходными scope/repository и уже инициализированным `conn`. Его проверка
   connector-owner также получает `_conn=conn`, без ленивого `_connect`.
   Это сохраняет отказ для live legacy alias без ledger, известных history
   и неоднозначного активного orphan на том же volume. Guard не записывает
   history/ledger и не enroll-ит alias. Собственный новый file-ID сам по себе
   не запрещён: завершённая до проверки законная замена остаётся допустимой.
   Windows-only scan не переносится на POSIX; там сохраняется ledger veto.

У missing/foreign/retired регистрации единый `not_authorized`, без disclosure
файлового exists. Холодный/непроверенный provider даёт `unavailable_at_check` с
`disk_at_check.state = not_checked`. В обоих случаях indexed IDs/hashes пусты.
Нельзя превращать собственный path, hash или symbolic scope в authorization.

## Evidence сохранённых байтов

Файл открывается один раз через существующий secure opener. Для SHA-256
выполняются два независимых прохода по одному FD с rewind. Каждый проход
читает ровно исходный fstat size блоками не более 1 MiB, без полного файла в
памяти и без `max+1` probe. Применяется существующий
`MEMORY_WIKI_DOCUMENT_MAX_BYTES`: тот же default 128 MiB и те же границы
1 000 000–2 000 000 000 B. Максимальный объём данных — два таких прохода;
это не latency/deadline или OS-sandbox гарантия.

Сохраняются все шесть образцов: path-before, FD-open, FD-between-passes,
FD-after-read, path-after и final-FD. Volume/device + file ID и size должны
совпасть между всеми образцами. Полные metadata images, включая nanosecond
mtime и ctime, сравниваются **внутри одного API**: path-before с path-after,
а четыре FD-fstat между собой. Windows path-stat и FD-fstat могут иметь
разные стабильные timestamp domains; их timestamps не приравниваются и не
нормализуются. Ранняя проверка path-before/FD-open также сравнивает только
physical identity/size. Оба полных hash должны совпасть. Reparse/
allowlist повторно проверяются после чтения. Early EOF, truncate/grow,
замена пути/FD identity во время проверки, metadata drift или разные hashes
не получают `current_at_check`; неполный/нестабильный digest не возвращается.
FD закрывается ровно одним владельцем, одной попыткой. Pending body fatal
сохраняет точную identity даже при другом cleanup fatal. Если body fatal нет,
cleanup `KeyboardInterrupt`/`SystemExit`/иной fatal выходит наружу, а не
поглощается обычным `not_authorized` из pending authority refusal. Ordinary
cleanup не подменяет pending primary. Фиксированная UNKNOWN note добавляется
best-effort: даже fatal из optional диагностики не заменяет выбранное
исключение. Неизвестный результат close не разрешает retry integer FD.

Это ограниченное point-in-time наблюдение сохранённого файла, не snapshot
lease и не обещание будущего: файл может измениться сразу после последнего
образца. Стабильная замена, завершённая **до** проверки, сравнивается по
байтам нового образца; равные байты не доказывают прежний file ID. Атакующее
ABA, неотличимое по обоим hashes и всем доступным metadata samples, не
исключено математически. Несохранённый буфер Word/Excel/редактора невидим.

## Результат

Ответ содержит только кодовые состояния и разрешённые evidence:

- `status`;
- `indexed_revision = {state, revision_id, file_hash}`;
- `disk_at_check = {state, file_hash}`;
- `checked_at` — Unix seconds UTC окончания disk sample (для отказа — время
  отказа; `not_checked` явно означает отсутствие проверки файла);
- `parser_validity = not_checked`.

| Условие | `status` | Disk hash |
|---|---|---|
| Стабильные bytes равны пригодной indexed revision | `current_at_check` | полный SHA-256 |
| Стабильные bytes отличаются | `changed_at_check` | полный SHA-256 |
| Bytes стабильны, но indexed tuple непригоден/неполон | `indexed_revision_unavailable` | полный SHA-256 |
| Изменение/неполное чтение в ходе I/O | `unstable_at_check` | `null` |
| Файл отсутствует до чтения | `missing_at_check` | `null` |
| Windows sharing/lock refusal до чтения | `locked_at_check` | `null` |
| Неподдерживаемое расширение / превышен лимит | `unsupported_at_check` / `too_large_at_check` | `null` |
| Недоступный файл/guard/platform | `unavailable_at_check` | `null` |
| Нет подтверждённого source owner / неверные аргументы | `not_authorized` / `invalid_request` | `null` |

Пригодность indexed tuple означает согласованную активную сохранённую
source/revision/connector связку с успешным ingestion status и ненулевым
unit_count. Она **не** удостоверяет истинность/безопасность текста, полноту
parser или embedding. Несогласованность pointers не исправляется выбором
произвольной superseded revision: indexed evidence становится unavailable.

Отсутствуют content/text, raw exceptions, paths, display_uri, bot/session и
чужие identifiers. Missing/locked/unsupported/unavailable состояние диска
сохраняет последнюю пригодную indexed revision в ответе; сама операция не
меняет её. Нет ingest, parse, embed, external_sources UPDATE, retirement,
удаления оригинала/ревизий, journal/outbox записи или новых SQL writers.
Штатный read fence использует собственные read-savepoints, не schema/DML.

## Регрессии и граница доказательств

`tests/test_source_file_observation_source.py` инертен при collection. Его
явная factory повторно использует существующий devtools SOURCE bootstrap,
bound reader и stdlib unittest lifecycle. В author phase тесты, factory,
helpers, collection и product bodies **не исполнялись**; только AST/raw hashes
и локальная Git metadata. Отдельный parent admission обязателен.

Подготовлены pure-policy controls для current/changed, corrupt/unusable
indexed tuples, сохранения старого index при nonstable disk, bounded hashing,
short/oversized/nonbytes reads, всех шести metadata samples, replacement и
typed safe errors. AST controls проверяют настоящую wiring wrapper,
исходный scope/owner/fence, существующий FD opener, read bounds, отсутствие
writers/ingest и cleanup. SOURCE исполняет только малый policy на authored
bytes/stamps и authored closer callbacks: synthetic data не создают
native/SQLite/owner authority. Distinct-domain positive связан с двумя
bounded hashes и current/changed decision; для каждого из шести samples
сохраняются identity/size/mtime/ctime negatives. Cleanup primitive готов к
pure fault-composition проверкам body ordinary/fatal × cleanup ordinary/fatal
и healthy controls, exact exception identity и hostile diagnostic failures.
Actual wrapper wiring и existing legacy/history/orphan/replacement branches
alias guard проверяются только как AST, не synthetic owner classifier.

Ни один input этого SOURCE entry не превышает 1 MB. Oversized `__init__.py`
не является input, explicit binding, extracted suffix или compressed payload.
Сам wrapper и FD/SQL/SDK/MCP/watch/Windows/Linux/E2E пути остаются NOT_RUN до
отдельной применимой квалификации. AST wiring не доказывает их исполнения;
исторические PASS не переносятся на новый блок.

### Correction01: статус доказательств

Три parent-confirmed findings `OBS-SRC-01-WINDOWS-STAT-DOMAINS`,
`OBS-SEC-02-LEGACY-PHYSICAL-OWNER`, `OBS-LIFETIME-03-FATAL-CLEANUP`
исправляются одним связанным source-блоком. Это условные SOURCE-механизмы,
не установленный runtime incident. Новый graph input — только AST малого
`document_knowledge_graph.py`; его guards/SQL/native paths не исполняются.
Author correction не запускает TestCase, helpers, collection, SOURCE,
unittest/pytest, SQL/native FD/SDK/worker/model/network/CI. Старый parent
packet 26 PASS / 85 subtests относится только к исходным observation524 и
outboxa3, не квалифицирует correction и не получает новую попытку. Exact
current commit/tree и metadata exits — в correction01/RESULT.json; допуск
affected proof, независимое review, интеграция и приёмка остаются родителю.


## Композиция с текущим f64 (CODE-only, 2026-10-29)

Эта ветка переносит **полную** принятую дельту `d6fb1b7→e5aacc6`, а не
только её correction, на `f64ed2ccadfa5f32a6b7c3074ec4856ea5187741`.
Общий graph не заменён старым файлом: единственная его правка — передача
`_conn=conn` из `_assert_ingest_path_alias_owner` в `_assert_connector_owner`.
Обратная замена восстанавливает весь точный f64 graph. Два owning reader
`document_unit_context` / `document_neighbors`, `_document_lookup_revision`,
их авторизация, SQL predicates, schema и disclosure owners остаются byte-exact.
Текущий alias guard совпадал с donor **origin**, но не с конечным e5: именно
недостающий connection handoff перенесён, прочие ветви сохранены.

В connectors добавлены только принятые observation declarations, imports и
private `_existing_only=False` ветвь `_source_key`. Инверсия этих additions
восстанавливает весь f64 connector. Поздние `_RECORD_INGEST_HOOK`, managed
record/cache, owner/commit/rollback/UNKNOWN fences не заменены donor-версиями.
`__init__.py`, MCP schema cache, COLD/partition/witness/gold и остальные тесты
не меняются. Публичного инструмента, enrollment/history/ledger writer,
watcher/scheduler, регистрации исходного пользовательского пути или autoindex нет.

### Новые подготовленные controls

Прежние 21 donor control и его `make_suite`/main сохранены. Дополнительная
`make_current_composition_suite` использует тот же обычный unittest lifecycle
и literal ordered roster; это test-only entry, не новый runner/controller.
Она принимает точные frozen source **strings** и raw SHA/diagnostic bindings,
не читает соседние worktrees и ничего не запускает при обычной collection.

- 6 `CURRENT_STATIC` cases: exact conn handoff + full graph inverse; full
  connector inverse и negative с изменённым late record guard; default writer
  identity и existing-only observer; raw preservation version-bound lookup и
  graph owners/schema; authorization-before-revision + revision SQL predicates
  и их отрицательный counterpart; exact e5 observation closure на current f64.
- 2 отдельные `PARENT_STATIC` cases: неизменные целые native/cache bytes,
  отсутствие public observer и полное равенство двух revision-bound schema
  records с optional literal `expected_revision_id`.

Large `__init__.py` доступен только последней **metadata-only** группе через
явные parent-STATIC strings. Это не SOURCE input/binding, extracted executable
или обход per-file admission. В новой группе definitions не исполняются даже
после setup: только AST/JSON/raw metadata. Малые source inputs остаются <1 MB.
Все 29 prepared cases (21 прежний + 6 current + 2 parent-STATIC), обе factory,
collection и product/test bodies на этой CODE-фазе — **NOT_RUN**. Никакой новый
SOURCE/native/SQL/SDK/model/CI/network/install/restart допуск не выдан.

### Исторические pins — не current qualification

`BASELINE_CONNECTOR_LF_SHA256` в отдельном explicit-source-only
`test_document_publication_readiness_source.py` остаётся исходным historical
whole-file control. Он больше не совпадает с candidate connectors: replay его
полного DP01 entry на current bytes потребовал бы отдельного oracle-owner
handoff, а не механической замены pin или ослабления assertions. Этот модуль
имеет `__test__ = False`, factory/main вызываются явно; существующий CI SOURCE
roster его не вызывает. CI failure из одного наличия pin не следует.

Старый `test_document_revision_integration_source.py` Case16 сохраняет
историческую unchanged-outside-lookup premise; он не переписан для нового
alias handoff. Прежние Source17 17/42 на f64 и 3PARENT_STATIC NOT_RUN остаются
историческими, их PASS не переносится на новый graph. COLD/partition текущего
candidate не квалифицированы и не переписываются этим блоком. Независимое
composition review и отдельно допущенный применимый execution остаются
родителю. Текущие commit/tree, raw SHA и actual metadata exits записываются
один раз в `development/document-observation-integration-20261029/AUTHOR_RESULT.json`.
