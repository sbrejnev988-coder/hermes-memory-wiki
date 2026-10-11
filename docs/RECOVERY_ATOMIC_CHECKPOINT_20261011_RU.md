# Recovery atomic/error source checkpoint — не GitHub Release

Source PIN: `d6fa8b37406f767045183e12c538e1f85bc6e702` на baseline `76e0a2bfc67ede25238a9a16e14ea8e07c09fa58`. Manifest/project остаются **1.24.5**. Новый tag, package/wheel, profile install, PM/liveness/scanner waiver и activation не выполнялись.

## Принятый ограниченный результат

Координатор принял **32/32** текущих focused direct-component проверок: actual child exit **0**, pytest exit **0**, **96** успешных setup/call/teardown reports, audit **0**, capture/ownership complete. Настоящие текущие `MemoryProvider`, `tools.registry.tool_error`, trust guard и file-backed SQLite; native Windows read-only opens — **13**, только существующая pinned функция документа и обычные файлы собственного fixture. Это не blanket ctypes/OS/process/network permission.

Пакет содержит оригинальные шесть recovery assertions, прежние десять controls и шестнадцать corrective controls. Исходные assertions и все test bodies сохранены. Отдельно исправлен собственный fixture: исторический checkpoint helper ожидал dict, actual public API возвращает Optional[Path]. В shipped test объявлена точная fixture projection; original helper/source guard не изменён.

Это **parent corrective verification**, не новое независимое PASS. Первое независимое review отвергло предыдущую дельту и сохранено как FAIL. После одного ограниченного correction block родитель сверил полные source chains и actual public/composed controls. Старые 4PASS/2FAIL, 16functionalPASS/auditBLOCKED и 18PASS/14FAIL corrective receipts не перезаписывались.

## Исправления и causal closure

- Genuine native error-only `tool_error` закрывает journal как `before/error`, без `after` и checkpoint. Native JSON и secrecy не меняются.
- Document delete history admission происходит в actual owning SQLite transaction **до** source/index/pointer эффекта. Overflow501 отказывает без мутации; exact500 остаётся разрешённым. Caps500 entries/12000 chars не увеличены, fixture501 не уменьшен.
- Public journal mutation отказывается при caller-owned pending transaction до boundary, после ожидания повторяет admission и удерживает provider lock до after/checkpoint. Внешний caller не коммитится/не очищается; legal direct joined helpers сохранены. Public commit/rollback и before/after/pointer equality проверены.
- Ingest replay reference checks, полный identity UNION и restoration находятся внутри actual `_ingest_transaction` до commit, не в отдельном post-commit `with conn`. UNION501, exact500, idempotence, hash/parser/revision/counts mismatch, char overflow и joined controls проверены на настоящем authored unchanged-file replay path.
- SQLite competing writer, foreign scope/handle, trigger effect и real rollback denial сохраняют primary/UNKNOWN/quarantine; код не лечит чужой owner reset-ом.

## Границы, которые не объявлены зелёными

Actual parser-worker extraction и private record commit hook H1 / ordinary ingest identity authority H2 этой дельтой не квалифицированы; parser/SDK результата не подменяли. Не приняты full native bootstrap/OS/fleet/live gateway/release и non-importer-home generation.

После пользовательского обновления core до `79b45d1647f6b5680768d851c4c406e8cc550a1e` отдельный MemoryManager/config compatibility packet имел22 functionalPASS, но childexit1 с26 retained bootstrap audit refusals. Этот heavy bootstrap blocker не устранён прямым32-case component proof.

Внутренний родительский planning budget120MB был превышен при сохранении fixtures; observed lower bound и UNKNOWN historical peak записаны. Позднейшее внутреннее перераспределение190MB не делает прежний run compliant задним числом и не повышает owner limits550MB/7GB/Cfloor3GB. Global owner inventory остаётся UNKNOWN. Точные resource samples и исходные отказы сохранены в локальном evidence.

## Публикация

Этот checkpoint — source correction, не весь release. Он включает предыдущий FTS/transaction-owner fix, но его старые runtime hashes относятся только к прежнему source PIN и не переименовываются в текущие. Full-suite counts старого frozen product не переносились на изменённые bytes. CI намеренно не запускался source-only продвижением; pending/absent CI не является PASS.

Перед installed rollout нужны собственные package/scanner/native liveness/owner gates. Старые installed primary/secondary PIN и wheel не содержат эту recovery-коррекцию; новый secondary/virtual PIN не объявлен.
