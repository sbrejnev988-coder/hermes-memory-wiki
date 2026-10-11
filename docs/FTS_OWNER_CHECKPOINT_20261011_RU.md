# FTS/transaction-owner source checkpoint — не новый релиз

## Точные исходники и назначение

Проверенный source commit: [`ad4d14f42ef967993158a2e07e3a2d8a73dcd7c8`](https://github.com/sbrejnev988-coder/hermes-memory-wiki/commit/ad4d14f42ef967993158a2e07e3a2d8a73dcd7c8). Версия manifest/project остаётся **1.24.5**; новый tag/GitHub Release этим checkpoint не создаётся.

Runtime `__init__.py` SHA256: `a58d9ea3c072560cc8f3215c445bf559e4b8423e127530953cf4c4abc1b65e39`.
Регрессия `tests/test_fts_transaction_handoff.py` SHA256: `7166d420ffd6ea6c1a19db6a05dfd4332a5f80b16e67ab133279e6ee285c46e7`.

Изменены только четыре метода runtime и добавлен отдельный callable component packet. Никаких schema/DDL/migration/model/config/core изменений.

## Что исправлено

Ранее FTS rebuild использовал raw SQLite `BEGIN EXCLUSIVE`, не регистрируя writer lifetime. Повторный `_connect` из `_meta_text` мог пометить собственный writer как unowned; после завершения SQL оставался quarantine, а terminal выдавал `terminal_owner_quarantine_UNKNOWN`.

Теперь EXCLUSIVE maintenance проходит через существующий `_claim_transaction`; stale-marker update присоединяется к тому же owned transaction. Второй raw cleanup/commit после отказа удалён: confirmed rollback восстанавливает schema, genuine UNKNOWN удерживает конкретный handle и первичную ошибку. Для fast recall необходимая maintenance завершается **до** первого original disclosure image; snapshot после callbacks не переякоривается. Terminal admission остаётся IMMEDIATE, с исходными owner/thread/epoch/erasure/trigger-effect fences.

Первый setter реального live gateway не был установлен этим изолированным воспроизведением и остаётся UNKNOWN. Кодовая коррекция не сбрасывает уже удержанный live quarantine и не открывает пользовательскую DB в обход owner.

## Исторический принятый component proof

На SDK source `90a7cccb1a243af60c5dfdf44868803d9da8ebec` и Python 3.14.7 фактически прошёл **22/22, child exit 0, audit violations=[]**, с настоящими `MemoryProvider`, `MemoryManager`, trust guard и собственным file-backed SQLite store. Это исполнение до Git commit; runtime/regression bytes совпадают с опубликованным source PIN выше.

Проверены save/query/nonempty prefetch, dirty FTS repair, accounting commit, registered sharing, native private writer expiry, same-path foreign/wrong-thread deny, DDL rollback, trigger effects, cancellation, late erasure, restart и retained UNKNOWN. Одно независимое read-only review приняло эту **компонентную** дельту. Оно не принимало full bootstrap/SDK extension, non-importer-home positives, OS/fleet или весь релиз.

## Совместимость после обновления SDK — отдельный отказ

После обновления SDK до `79b45d1647f6b5680768d851c4c406e8cc550a1e` старый receipt не объявляется новым proof. Изменились четыре bound SDK modules. Выполнен один связанный текущий component packet после устранения конкретных carrier prerequisites: ordinary YAML dependencies и явный opt-in event ledger только в собственном fixture.

Все **22 функциональные проверки прошли**, но итоговый **child exit 1**: при новой native registration/config loading аудит сохранил **26 refused bootstrap attempts** — `socket.gethostname` (1), read attempts `cgroup`/`mountinfo` (24), `subprocess.Popen` (1). Они не удалены, allowlist ради GREEN не расширен, core/SDK не патчились. Поэтому новый полный auditenvelope/native admission **не принят**. Частичный functional result не является новым green gate.

Модельные/сетевые запросы и hosted CI не выполнялись. Старые setup/import/fixture отказы сохранены отдельно; ни отсутствующий report, ни unstarted cases не превращены в PASS.

## Что не закрыто

- Recovery native error-only envelope ошибочно журналируется как `after`, не `error`.
- Recovery history overflow проверяется после committed удаления; этот data-safety дефект остаётся.
- Полные cold lanes не допущены: correctly bound actual core/origin/dependency closure и local recorder/OS contract отсутствуют; прежние holds сохраняются.
- Readonly/foreign-reader positive, non-importer-home generation, universal missing-table/v3-marker first-attempt recall и live/fleet qualification не объявляются выполненными.

## Публикация и установка

Этот документ относится к **source checkpoint**, не к выпуску или установке. Исторические installed primary `11a712bc5f770b95c9347895d2c6f604546c9eff` и secondary `4d0d401465f00579351a6dfbfc5da9003684b3c5` не содержат новый FTS fix. До separately qualified rollout они остаются отдельными installed bindings, а не proof нового runtime.

Checkpoint не задаёт новый secondary/virtual PIN, scanner override, PM/install/liveness grant или restart. Старый wheel не содержит новое исправление; его нельзя выдавать за сборку этого runtime. Источники можно читать и сравнивать по exact PIN; обновление установленного кода требует собственных gates. Release остаётся BLOCKED; CI намеренно не запускается этим source-only продвижением и не объявляется успешным.
