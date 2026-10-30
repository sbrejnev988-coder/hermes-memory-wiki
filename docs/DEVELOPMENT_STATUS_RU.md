# Статус разработки Memory Wiki

Этот документ различает опубликованный код, изолированные проверки и фактическую работу в Gateway. Публикация checkpoint не означает stable release, установку или полную runtime-квалификацию.

## Опубликованный основной код

- Основная линия: `ac8edb6b8f91bb5a7d8af020183d3848e4726739` (`main`).
- Упаковочный counterpart: `650f59cd24cb160baa35e0569b267d0a7b08ab2d` (`release/document-observation-virtual-20261029`).
- Для этой пары ранее подтверждена code-only установка и побайтовая проверка пяти профилей. Это не доказательство полной загрузки и пользовательского E2E каждого профиля.

## G1 privacy fixture

Checkpoint `4b32def39cb9272fae54f15859e82563eb78c95f`, tree `10d98c9efe032aafe45d04f10f4107e3b47d02d6`, опубликован в `fix/g1-privacy-oracle-20261030`. Дельта относительно `main` затрагивает только три тестовых файла; production privacy guards не изменены.

Оракул разделяет здоровую видимость до privacy mutation и законный отказ раскрытия после erasure. Для прямого internal document API проверяется поле `disclosure`, а не поле публичного wrapper. Первое независимое SOURCE-ревью выдало HOLD. После минимального исправления ревью дельты и родительская проверка закрыли его; исходный HOLD сохранён.

Один явно разрешённый затронутый case выполнен на настоящем Hermes SDK и собственной SQLite/FTS: **1 PASS из 1**, SDK/controller/внешняя команда завершились с exit 0; тайм-аутов, audit refusals и повторов нет. Проверены сохранность archived/retired rows, retained links и erasure ledger, отсутствие resurrection удалённого claim и `disclosure=withheld` с пустым `results` после privacy mutation.

Это не свежий полный G1-прогон. Исторические восемь G1 cases с 7 PASS/1 fixture ERROR и отдельный FAIL более раннего fixture сохранены; вместе с последним case учтено десять G1 SDK test children.

## Принятый outbox CODE-checkpoint

Ветка [`fix/addressed-outbox-retry-20261025`](https://github.com/sbrejnev988-coder/hermes-memory-wiki/tree/fix/addressed-outbox-retry-20261025) содержит принятый кумулятивный CODE-checkpoint `cc40abee53e734b5720b1833462738417f733e18`, tree `be85726f2f5e385da98d8664ce32235a95e7e3a8`. Исправление ограничивает повторную попытку адресованной собственной outbox-задачей и сохраняет неопределённость при отказе progress callback. Первоначальные HOLD и корректирующие ревью сохранены; принят полный итоговый source-блок.

Этот checkpoint **не интегрирован в актуальный `main` и не установлен**: whole donor tree не подменяет текущий код. Все 44 подготовленных TestCase methods на `cc40`, семь public/native obligations, Linux и FULL остаются без свежей runtime-квалификации; отдельный UNKNOWN teardown prerequisite не закрыт публикацией.

Его точные предки `d6fb1b7e7d3f0077c20fbac5bccc0d9dd27ebb78` (подготовленные inert witness/census) и `346778f6e315143a5e0072cf3d0a686980d79c5f` (document revision lookup) также доставлены на GitHub. Последний lookup ранее выборочно интегрирован в основную линию; отсутствие отдельной старой ветки не означает отсутствие этой функциональности. Census — метаданные подготовленных проверок, не фактически выполненный полный набор.

Для обеих новых code-checkpoint веток проверены точные удалённые ref, commit/tree и полный набор path/mode/type/blob OIDs. `main` и ранее установленная пара оставлены неизменными; новые hosted CI, release, install или restart не выполнялись.

## Текущий незакрытый P0

Последняя проверка после перезапуска подтвердила согласованные home/SQLite connection default-провайдера и доступность семантического backend. Снимок compiled entrypoint совпал с текущим исходником, но полная загруженная сборка и текущие callable fields не аттестованы. Публичный dashboard всё ещё может возвращать `disclosure_status=withheld`; пустые счётчики такого ответа не являются здоровой пустой БД или доказанным повреждением. Точная причина текущего veto не установлена.

Положительный live-путь сохранение → поиск → итоговый контекст, обычная грамматика фактов и automatic session-end extraction требуют отдельной квалификации. Более ранний поддержанный synthetic model/store/FTS/prefetch/context PASS получен в изолированной среде; он не подменяет live Gateway.

## Дальнейший порядок

1. Установить причину публичного withholding законным ограниченным наблюдением, без прямого обхода ACL/guard.
2. Довести разрешённый связный source-блок и применимые регрессии; не смешивать его с чужими interrupted или rejected changes.
3. Квалифицировать реальные пользовательские save/recall/context и документный путь добавить → вопрос → точный источник → обновить → синхронизировать → исключить старую current-выдачу.
4. Сохранять Linux/Windows совместимость и независимые FULL/CI/recovery/security gates. SOURCE или один Windows case не аттестуют Linux.
5. Выпускать принятые логические точки с exact remote readback; install и loaded/runtime остаются самостоятельными этапами.

Секреты, `.env`, конфигурации рабочих профилей, live базы, память пользователя, auth stores и диагностические payloads в этот public checkpoint не включены. LCM-X и Decider — самостоятельные проекты, не дополнительные release-gates Memory Wiki.
