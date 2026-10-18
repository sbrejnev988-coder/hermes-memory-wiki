# Проверки публикационного кандидата 1.24.6

Текущий локальный release packet использует самостоятельные shipped entries
через существующий controller: SOURCE/extracted bodies, generic SQLite,
in-memory HTTP и canonical synthetic release metadata. Это не обычный FULL
pytest/native SDK gate. Временный `TMPDIR` должен принадлежать исполнителю;
для admin/restore/bootstrap entries передаётся отдельный новый `--scratch`.

Current-source raw pins перепривязаны к 1.24.6. Исторические graph-aggregate
oracles сверены с owning-TX intent, а HTTP read oracle — с bounded EOF probe.
Исходные failed captures/gold сохраняются, safety/ACL/owner assertions не
пропускаются и guards не отключаются. Обычная native collection дополнительно
требует правильного standalone `make_suite`/CARRIER setup, подлинных SDK/trust
companions и разрешённых synthetic settings fixtures. Локальный packet не
заявляет, что эти prerequisites или cross-platform FULL уже выполнены.

## Причинная диагностика collection (SOURCE-блок 2026-10-18)

`tests/helpers/collection_evidence.py` — общий **тестовый reporter**, не новый
controller/bootstrap. Оба existing entries загружают этот stdlib-модуль напрямую,
не импортируя `tests/conftest.py`. Native preflight/origin/MRO/ownership guards,
`cold_plan`, SDK/trust prerequisites и исходные pytest arguments сохранены.

- `packaging/run_native_regressions.py`: root — уже объявленный isolated
  `.hermes-ci` либо `.hermes-release`; evidence — `<home>/collection-evidence/`.
- `tests/cold_lane_entry.py`: root — `<runroot>/public`; тот же evidence namespace.
  Existing `phases.json` остаётся в `public`, с прежними полями `collected`,
  `phases`, `collection_errors` (список nodeid), `session_finished`, `exitstatus`.
  Его bounded/exclusive persistence теперь проходит через тот же reporter.
- `pytest_collectreport(report)` сохраняет каждый failed report, включая повторный
  nodeid, целиком: literal `nodeid`, `longreprtext` как `longrepr`, полный qualified
  `report_type` и `longrepr_type`, `when=collect`, исходный `outcome`. Никакой
  реконструкции исторических ошибок и парсинга предполагаемого exception type.
- `pytest_exception_interact(node, call, report)` отдельно сохраняет настоящие
  qualified type и message из `call.excinfo.value` для collection. Этот hook
  передаёт CallInfo до collectreport в проверенном pytest source. Если он не
  вызван, точный Python exception type **неизвестен**; representation type и
  полный предоставленный pytest текст всё равно сохраняются. Source-тесты
  используют явно synthetic reports/CallInfo, не исполняют pytest renderer.

### Durable/UTF-8 контракт и refusal

`errors.jsonl` создаётся эксклюзивно, первым идёт `started` с `complete=false`.
Каждый целый event записывается binary write-loop → flush → fsync **до возврата
hook**, без ожидания sessionfinish. `collection_error`/`collection_exception`
также полностью отражаются в stderr с префиксом
`MEMORY_WIKI_COLLECTION_EVIDENCE `: будущий обычный CI сохраняет причинный текст
в console log даже без нового artifact uploader. `sessionfinish` — отдельное
наблюдение, а `returned_exitstatus` и `primary_type` — фактический выход wrapper;
они не выдаются друг за друга.

JSON — UTF-8, `ensure_ascii=True`, без нормализации, усечения или замены invalid
Unicode: round-trip сохраняет в том числе astral characters, literal escapes,
NUL и lone surrogates. Лимиты считают **сериализованные bytes вместе с newline**:
2,000,000 B journal, 256,000 B/event, 1,024 B journal reserve для первого refusal
и sessionfinish, 1,000,000 B phases, по 8,192 B для status/refusal. До encoder
действуют также bounded primitive/cardinality/character/depth проверки. Верхняя
граница новых файлов reporter — 3,016,384 B; отражение stderr считается отдельно.
Формирование самого pytest `longreprtext` не является bounded работой reporter.

`status.json` схемы `memory-stack.collection-evidence/v1` содержит counts
failed/saved/uncaptured reports, type-detail count, раздельные session/return/
primary facts, подтверждённые written/fsynced bytes, phase status, cleanup и
первые восемь точных diagnostic refusals плюс `refusal_count/refusals_omitted`.
Первая callback-refusal по возможности fsync-ится в reserved journal tail сразу;
при повреждённом journal он не «ремонтируется» правдоподобной JSON-строкой.

**Complete reporting требует одновременно** валидный `status.json` с
`complete=true`, исключительно созданный `complete/` и отсутствие `refusal.json`.
Commit-marker создаётся только после закрытия всех файлов, успешного final
status fsync/close и console reporting. Это означает полноту диагностики, **не
pytest PASS**: допустимы сохранённые exit2 либо original exception. Missing,
partial, overflow, I/O/console/close failures — INCOMPLETE/REFUSED, не ноль ошибок
и не truncated-success. Late status/commit refusal сохраняется отдельно в
`refusal.json` и stderr; если сам root/I/O недоступен, fallback — явный stderr
refusal, отсутствие complete marker, сохранённые partial bytes. Невозможность
записать ни файл, ни stderr остаётся неполной доставкой, а не успехом.

Reporter не меняет session/testsfailed/exitstatus, не бросает diagnostic exception
поверх исходного pytest return/primary (включая BaseException) и не превращает
telemetry refusal в новый test exit. Consumers должны оценивать test outcome и
reporting integrity **раздельно**. Старый `classify_phases` сам по себе не является
валидатором нового terminal collection evidence. Новые diagnostic names ещё не
включены в allowlist hosted artifact collector; его будущая приёмка отдельна.

Root должен быть явно объявленным, quiescent, exclusively owned fixture root;
допускается создать только сам отсутствующий root при существующих ancestors.
Lexical traversal/Win32 aliases/ADS/devices, symlink/reparse ancestors, changed
no-follow directory identity и collisions отказывают. Files создаются только
`xb`, чужие bytes не перезаписываются/не удаляются; закрытие descriptors
проверяется на всех путях, неподтверждённый close остаётся UNKNOWN в evidence. Проверки не
обещают атомарную OS containment против враждебной concurrent подмены ancestors.

### Проверка и сохранённые non-goals

Новый применимый packet исполняет `tests/test_collection_evidence.py` (exact
stdlib module + extracted actual `collection_reporter`/`run_tests` bodies),
реальные fixture files и synthetic callbacks/metadata/fault actors. Guards и
actual callable bodies не подменяются; symlink/reparse negatives — явно
synthetic no-follow stat data под неизменным guard, не native link proof.
Физический peer layout: этот test, `tests/helpers/collection_evidence.py`,
`tests/cold_lane_entry.py`, `packaging/run_native_regressions.py`. Обычная
discovery нового test не требует отсутствия чужого global provider singleton.

В `COLD_LANES.json` добавлены **только** SOURCE-explicit записи для уже принятого
`tests/test_ci_lifecycle_observer.py` и нового `tests/test_collection_evidence.py`.
Это не повтор observer9 и не исправление прежних 44 unpartitioned baseline
файлов, binder/routing или FULL union. Все прежние rows, native/core/trust null
bindings и blockers остаются. Historical Ubuntu/release6 и Windows7 node IDs /
longrepr не восстановлены. Native/pytest/cold/FULL/CI, SDK/provider/SQL/host,
network/models/install/restart/publication в этом SOURCE-блоке **NOT_RUN**.

## Исторический RI-R01 / hybrid checkpoint 1.24.5

Это SOURCE checkpoint, не новый релиз, не native SDK acceptance и не установленный/loaded runtime.

## Состав и запуск

- Canonical main: `6a7486e5f99d2115ebe76bd823da9ec3bd994969`. Все его tracked paths и modes сохранены; перенесены только 17 принятых runtime-файлов и применимые regression/setup deltas.
- `tests/ci_owned/doc_code_carrier_cases.py`: шесть current SOURCE-групп. Используется существующий SOURCE AST selector и SQLite fixture из `tests/helpers/cases_*.py`, а не SDK stand-in или новый fixture framework.
- Entry требует `DEVTOOLS_INPUTS`, `devtools_read_bound`, `DEVTOOLS_SCRATCH` и `devtools_case_started` от существующего stdlib-only SOURCE controller. Controller связывает реальные repo-relative source bytes и объявляет credential-free scratch; обычный import root `__init__.py` не выполняется. Выполненный пакет не объявляется portable pytest/native integration.
- Три direct/AST файла перечислены отдельно в `COLD_LANES.json`. Native strict, genuine legacy и recovery lanes остаются отдельными cold processes. Их SDK origins/MRO, trust/dependency closure и bootstrap должны быть реально приняты до запуска. JSON-план не является execution authority.
- Для самостоятельного AST pytest использовать `--noconftest --confcutdir=<repo>/tests`, отключить autoload plugins и разместить capture/cache/log/basetemp в собственном scratch. Один `--noconftest` не исключает ancestor Package.setup: native import возможен до fixtures.

## Сохранённые границы

Healthy roster: 13 public doc/code/source handlers, настоящие semantic restrictions и exact code representation. Negative groups: withdrawal после actual serialization; оригинальный genuine shared owner через private reader close; actor/project/erasure/SQL ABA; последние guard/native-scope/journal callbacks перед original reread; тот же primary/cleanup UNKNOWN на верхнем public caller с quarantine/retained owner до fixture safety close. Prefix-only assertion не заменяет exact field/identity withdrawal.

Исторический SOURCE6 receipt SHA256 `6f108bbce135a8d1427dda92534285299592d1774fc9f354aecb2e731eda8a37` сохраняет три BEFORE vulnerable witnesses. Public current packet исполняет healthy roster и пять отрицательных групп на текущих bytes, не восстанавливает неизвестный baseline и не выдаёт current source за BEFORE. Guard/ACL/negative gold не удалены. Исторический G4-only full-file/trust oracle сохранён отдельно; текущая cumulative composition проверяет protected `_metadata` scope и actual current provider raw SHA, не заявляя доверенный native trust import.

Версии 1.24.5, 121 cached schema dictionaries, packaging globs, `schema.sql` и `migrations.py` сохранены. `get_tool_schemas()` и provider initialization не вызываются ради SOURCE cache equality. Build/readback проверяет настоящий wheel METADATA через email parser, полный RECORD/ZIP membership и byte correspondence, не установленный import/Doctor/runtime.

Сканирование final install payload, liveness, hosted CI, native lifecycle/recovery, live services/providers/models, profile reinstall и owner reload остаются отдельными gates. Python audit — не OS sandbox/continuous lease. После настоящего существенного business/build failure сохраняется capture; неизменённый полный packet автоматически не повторяется.
