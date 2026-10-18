# Collection diagnostics: CI dispatch and bounded transfer

## Граница

`ci_child.main()` сохраняет прежние native export/origin/MRO и fixture-home
проверки и только после них передаёт настоящий `pytest.main` в
`dispatch_pytest`. В CLI нет tooling/native bypass. Прямой вызов dispatcher в
изолированных fixtures проверяет **tooling component**, не SDK/bootstrap,
Memory Wiki, FULL, hosted CI, installed или loaded runtime.

`collection_reporter` загружает существующий `tests/helpers/collection_evidence.py`
по файлу, без package `tests` или source `__init__.py`. Helper не скопирован и не
изменён. Он сам получает настоящие pytest `pytest_exception_interact`,
`pytest_collectreport` и `pytest_sessionfinish`. `Recorder` отдельно сохраняет
прежние `collected`, `phases`, `collection_errors`, `session_finished`,
`exitstatus`. `collection_errors` остаётся списком nodeid, а полный longrepr,
настоящий report/longrepr class и exception type находятся в journal.

`dispatch_pytest` возвращает **тот же объект**, который вернул pytest, включая
IntEnum; исходный BaseException повторно выбрасывается тем же объектом.
Небросающий helper finalizer пишет `phases.json` с прежней схемой; отказ
диагностики не заменяет primary/return. При этом неполные diagnostics не дают
зелёный artifact gate даже после return0. Phase completeness не является
collection diagnostics completeness и наоборот.

## Закрытый artifact contract

Существующие native lane 24,000,000 B, JSON/log/JUnit caps, metadata no-follow,
regular-file/single-link/physical-identity и точные matrix groups сохранены.
Добавлен только один явный namespace `collection-evidence/`:

| Член | Верхняя граница B | Роль |
|---|---:|---|
| `errors.jsonl` | 2,000,000 | fsynced journal accepted helper |
| `status.json` | 8,192 | terminal status accepted helper |
| `refusal.json` | 8,192 | явный отказ; не допускает completion |
| `complete.json` | 1,024 | переносимый witness, не результат тестов |
| `pending.json` | 1,024 | только локальный незавершённый transfer, не upload |
| `complete/` | 0 файлов | исходный exclusively-created helper marker |

Суммарный diagnostics cap — сумма пяти file caps. `phases.json` дополнительно
ограничен helper cap 1,000,000 B. Эти bytes входят в прежний lane cap, а не
добавляют к нему резерв.

GitHub artifact не переносит пустые каталоги. Поэтому после helper finish
`ci_child` проверяет его complete marker, status и отсутствие refusal, затем
через существующий helper writer создаёт `pending.json`: schema
`memory-stack.collection-transfer/v1`, `complete=true`, bytes/SHA256 именно
`errors.jsonl` и `status.json`. Только после fsync/закрытия без новых refusals
файл переименовывается в `complete.json`. Close failure оставляет pending,
не complete. Ошибка seal не заменяет pytest outcome.

Producer требует исходный пустой `complete/` **и** `complete.json`; downloaded
receiver требует переносимый `complete.json`, не потерянный пустой каталог.
Любой refusal, pending, missing marker/status, неизвестный member, unsafe
identity, cap overflow или malformed/mismatched transfer/status закрывает gate.
После **всего** lane/matrix metadata admission читаются только три явно
ограниченных diagnostics файла. Status должен подтверждать complete cleanup,
sessionfinish, phase evidence, нулевые refusals, совпавшие collect counts,
возвращённый/session exitstatus и fsynced journal bytes. Hash witness не
аутентификация и не SDK/provenance authority. Контракт требует собственного
quiescent snapshot; не заявляется OS sandbox, concurrent-writer fence или
producer disk/RSS limit.

Workflow добавляет только четыре буквальных upload paths: errors, status,
complete и refusal JSON. Нет directory wildcard. Непригодный snapshot не
передаётся; прежний крошечный `ci-output-admission.json` сообщает refusal.
Pre-pytest bootstrap snapshot без phases по-прежнему может пройти capacity-only
admission с `collection_complete=false`: это сохраняет раннюю диагностику и
**не** делает receipt/FULL зелёным. Если phases уже есть, отсутствие reporter
namespace — `collection_missing`, а не «нулевые collection errors».
Полная diagnostics при collection exit2 допускается к передаче, но не меняет
этот nonzero exit на успех.

## Воспроизводимые tooling проверки

`tests/ci_owned/collection_dispatch_cases.py` содержит stdlib unittest controls
(прямой запуск `python -B tests/ci_owned/collection_dispatch_cases.py`) и
`run_fixture(kind, source=..., root=...)` для одного настоящего pytest9.1.1
запуска **в текущем процессе**, без скрытого subprocess. Fixture kinds:
`collection_error` (RuntimeError), `syntax_error` (настоящий parser/collector),
`healthy` (два обычных passed main cases плюс полный shipped набор из 12
stdlib controls, byte-exact перенесённый вместе с его helper/script/workflow
layout). Failure fixture exit2 — ожидаемый pytest outcome, не failed UNIT;
healthy ожидает exit0, 14 main cases и 42 настоящих phase reports. Assertions
во внешнем квалификаторе отдельно сверяют actual exits,
report/longrepr/exception types, terminal status/marker и отсутствие SDK imports.

Root создаётся отдельно и не является Python package. Точные `--rootdir`,
`--confcutdir`, `-c`, importlib import mode, sys capture и выключенный plugin
autoload исключают ancestor package setup. В закрытом network-denying envelope
выключен только stock JUnit plugin (`-p no:junitxml`): его hostname metadata
probe не разрешён. JUnit не объявляется выполненным и не подделывается;
реальные hooks, longrepr и phase recorder остаются активны. Обычный hosted
`main()` сохраняет прежний stock JUnit аргумент.

Standalone UNIT отдельно покрывает exact primary/return, finalizer/late transfer
close refusals, missing reporter/marker/status, corrupt journal/status, metadata
before payload, lowered existing caps, downloaded transfer без пустого каталога,
refusal CLI и буквальный workflow allowlist. Synthetic UNIT callbacks не
называются real pytest. Принятый неизменённый SOURCE24 не повторяется.
Полные execution/capture/audit/source bindings и frozen candidate находятся в
одном lane RESULT с отдельными primary captures; приёмка и интеграция — у
родителя.

## Фактический ограниченный qualification packet

Первоначальный packet сохранён как **BLOCKED**: standalone import `py` отказал
до controls; healthy выполнил только два обычных cases; generic SyntaxError
дал pytest return2, но child exit3 и 14 `unsafe_token` audit refusals. Поздняя
test-only correction directory/file arguments тогда лишь компилировалась.
Этот исторический результат не переименован в PASS.

В отдельном родительском continuation на frozen `80286a4` действительно прошли
**12/12 standalone stdlib UNIT controls**, child/controller0, audit0. Новый
bounded passive witness установил caller всех 14 повторённых Syntax DENY:
CPython3.14 `traceback._find_keyword_typos` → `codeop.compile_command`/`tokenize`
пытаются читать pseudo filenames `<input>`/`<string>`. Исторический caller без
такого witness остаётся неизвестным; новый диагностический child exit3 не PASS.

Исправлен только producer syntax fixture: вместо generic `invalid syntax`
использован **настоящий parser SyntaxError об unterminated string literal**.
Он сохраняет реальную pytest collection/exception/longrepr ветвь, но не включает
необязательный keyword-typo compiler. Guards, pytest/SDK/Core, helper и CI
runtime bytes не менялись. Все 38 assertion subtrees и остальной AST тестового
модуля сохранены (кроме единственного syntax payload и сдвига comment locations).
Generic keyword-typo formatting под этим строгим envelope остаётся unqualified.

После shared argument/roster correction свежо исполнены **все три affected
fixture kinds** на execution commit
`bfe45ece8b3053a83e66ab1618738f2d719228a7`:
- healthy: **14 main cases, 42 setup/call/teardown reports PASS**, child0;
  из них два обычных pytest controls и 12 synthetic-callback tooling UNIT;
- RuntimeError collection: один настоящий failed CollectReport с exception
  details и longrepr, ожидаемый child/pytest exit2;
- parser SyntaxError collection: один настоящий failed CollectReport с
  CollectError/SyntaxError details и longrepr, ожидаемый child/pytest exit2.

Все три controller exits0, audit0, complete capture/reap/ownership и пустые
supervisor errors с primary=null; все diagnostics seals/status проверены.
Отдельные 12 standalone UNIT пересекаются с healthy14 и не прибавляются к14.
Фактически создано **9 children** за весь блок, exits
`[1,0,2,3,0,3,0,2,2]`; прежние bootstrap/capture/audit отказы сохранены отдельно.
Последующая doc-only qualification note не является новым тестовым запуском.

Это проверка reporting/artifact **tooling component**, не Memory Wiki behavior,
SDK origin/MRO/bootstrap, stock JUnit, hosted CI, FULL, installed или loaded
runtime. Независимая source review и parent acceptance/integration отдельны.
