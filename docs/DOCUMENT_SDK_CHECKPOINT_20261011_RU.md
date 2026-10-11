# Document authority / host-erasure / SDK qualifier — source checkpoint

Принятый source PIN: `5d8a8b57319a8fa27ef8edd15f97bfb0a1f06ed1`, baseline `d61268f5da18e11824a5285e4e4096fdd65672e6`. Эта кодовая дельта заменяет прежний незавершённый локальный `b04b67d`; тот checkpoint не был опубликован или установлен. Manifest/project/runtime остаются **1.24.5**; новая release-version и tag не объявлены.

## Что исправлено

- Private document record commit H1 использует настоящий зарегистрированный provider writer lifetime. Commit/rollback receipts соответствуют фактическому SQLite return, а UNKNOWN сохраняет exact owner и primary.
- Ingest H2 удерживает original caller/source/actor admissions у фактического owning stage до COMMIT. Проверка не теряется при legal joined transaction, после возврата child или позднего journal callback. Несколько joins сохраняют первый и последний admission; повторный source не заменяет прежний actor новой authority. Поддерживаемые joins не запрещены blanket-refusal.
- Host removal/erasure использует правильный connection/lock/transaction lifetime. Raw BEGIN больше не quarantinе собственный writer, после чего raw context-manager мог реально commit retirement при неверном owner ledger. Durable privacy intent, rollback, restart и exact primary/UNKNOWN сохранены; cached ingest не восстанавливает удалённое знание. Поздний lifecycle отказ не переименовывается в первый setter исторического запуска.
- SDK result qualifier требует явные supervisor `errors=[]` и `primary_error=null`. Complete pipes/ownership и exit0 не стирают error ledger; missing/malformed поля отказывают. Отсутствующий disposition recovered error не считается успехом.

## Проверки точного объединённого дерева

**87/87 component PASS**, actual child exit0, audit0, 261 setup/call/teardown reports. Настоящие direct MemoryProvider/trust/SQLite и явно авторские retained-cache/file-backed fixtures. Parser worker не подменялся; этот компонентный путь не cold-parser или whole SDK/bootstrap proof.

**18/18 UNIT PASS**, отдельный child exit0, audit0. Это tooling qualifier/security-unit scope, не ещё 18 native integration cases. Уникальные cases и слои сведены отдельно; прежние и повторные прогоны в эту сумму не добавлены.

Actual runtime execution PIN: `3f33a9dc48385273749f8d2633903c63458bf0eb`. В final source PIN `5d8a8b57319a8fa27ef8edd15f97bfb0a1f06ed1` после этого изменён только SOURCE descriptor discriminator. Сравнение всех runtime/test/entry bytes подтвердило перенос прежнего component proof; нового component87 запуска на final PIN не заявляется. UNIT18 выполнен на final PIN.

Первое независимое review обнаружило lost original authority у outer joined owner и сохранилось как FAIL. Контрпример реально воспроизведён; согласованная A-owner коррекция прошла повторное review именно содержательной дельты. Итоговое независимое correction review — PASS, а родитель проверил actual packets, Git/tree/raw hashes и принял только local source/direct-component/UNIT границу. Блокеры и setup refusals не удалены из evidence.

## Что остаётся BLOCKED / UNKNOWN

- Cold native parser и полный native SDK/config bootstrap не допущены; once allowance остаётся0. Source-bound descriptor с `resolved_native_sdk_core` не является capability grant.
- Сохранённый полный bootstrap capture содержит26 отказов в registration/config loading: hostname1, `/proc` open24, Popen1. Primitive caller chains сохранены; exact native creation payload UNKNOWN, `_winapi.CreateProcess` events0, process grant0. Functional callback success не превращает этот gate в PASS.
- Полная regression/integration/security кампания release scope, другие Python/OS, live user memory и loaded owners/fleet не квалифицированы этим пакетом. Старые broad-suite failures на иной ревизии не объявлены устранёнными.
- Historical resource breaches остаются историей; сжатие fixtures не доказывает прошлый peak cap. Полный owner inventory/compliance UNKNOWN; лимиты и C-floor не повышены этой публикацией.

## Публикация и rollout

Это **source-checkpoint, не готовый GitHub Release**. Tree содержит прежний FTS и recovery fix плюс указанную document/host-erasure correction. Core/SDK/PM, profile config, модели, keys, user DB/indices не менялись. Новый wheel/secondary virtual PIN, установка, enable/reload/restart не выполнялись; старые installed PIN и wheel не выдаются за этот runtime.

Source-only push публикует exact runtime/tests и данный guide. CI намеренно не запускается этим checkpoint и отсутствие checks не означает PASS. Перед rollout нужны собственные current scanner/PM/liveness/owner и runtime gates; existing consent на иные bytes автоматически не переносится.
