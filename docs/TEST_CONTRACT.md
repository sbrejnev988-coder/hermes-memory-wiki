# Проверки RI-R01 / hybrid checkpoint 1.24.5

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
