# Memory Wiki 1.24.5 — source-only кандидат

**Это не опубликованный релиз и не подтверждение runtime готовности.** Версия выбрана владельцем явно: **1.24.5**, не 1.24.1/1.24.2. Эта lane подготовила исходники; GitHub push, установка и конфигурация пяти профилей выполняются отдельно родителем.

## Изменения

- Полный подготовленный public source353 сохранён как база. Старый installed baseline использован для exact three-way переноса уже подготовленного packing patch, а не для замены более новых публичных guards, rendering, extraction, ACL и CI слоёв.
- Prefetch пакует whole guard-safe rendered units: claim + metadata/why/evidence, delta, shared fragment, episode, trusted и opaque knowledge blocks. Финальная cache/wrapper оболочка учитывается целиком; overflow удаляет unit, не обрывает его строку. Пустая/header-only оболочка не становится доказательной памятью. Social, lexical fallback и withheld пути также ограничены целиком.
- Raw delta obligations сохраняются до main/delta dedupe. Seen watermark не проходит через недоставленный raw `(id, revision)`, включая ID, переданный main-пулу и затем пропущенный. Same-ID другая revision, shared excerpt, guard/budget/deadline gap и неизвестный raw contract не дают ack. Cancellation guard сохранён.
- Existing rendered/delta/episode diagnostics, claim-char counts и shortfalls пересчитываются после исключения units. Encoded episode-char accumulator корректируется; новая diagnostic schema не вводится. Optional diagnostic line описывает финальные units и не режется для вместимости.
- Owner-bound callback захватывает `min(provider ceiling, enabled host spill cap)` штатным public getter до bare worker thread. Budget явно передаётся worker/fallback. Process ENV, live config и cached MemoryManager spill settings не патчатся; чужой/неизвестный owner не подставляется.

## Версия и сохранение истории

`plugin.yaml`, PEP621 `pyproject.toml`, runtime `PLUGIN_VERSION`, SDK `__version__` и self-package в `uv.lock` согласованы на 1.24.5. SDK/MCP protocol, tool schemas, DB/cache/state schema versions не повышаются. Setup, MCP handshake и packaging generators используют эти metadata readers; их SDK/build исполнение сейчас не выполняется. Schema cache/compatibility JSON не содержат release version и сохраняются byte-exact.

Уже инвентаризированный предверсионный кандидат сохранён отдельно; 1.24.5 создана новой полной derivative. Исторические gold/evidence/receipts, `RELEASE_NOTES_1_24_0_RU.md` и прежние audit notes не переписаны. Текущий metadata test получает отдельные exact hashes 1.24.5, сохраняя старый frozen gold map и прежние поведенческие assertions.

## Фактические проверки и pending gates

- Выполнялись только raw-byte readbacks, hashes/inventory, static AST/syntax checks без product imports и чтение исторических receipts. Exact diff replay, version equality и окончательные regenerated hashes фиксируются в handoff evidence этой derivative; не выводить acceptance из названия артефакта.
- Первичный static verifier отказал на ложном regex совпадении `state_token` в dynamic cache metadata. Отказ и verifier сохранены; чинится только triage verifier, production bytes ради него не меняются.
- Старый packing RED/GREEN относится к прежним source bytes: это история, **не** свежий PASS 1.24.5.
- Новые focused regressions написаны, но tests/SDK/model/native/full jobs сейчас **не запускались**. Независимый статический review подтвердил только prefetch/selection/owner-budget delta; review всей композиции выявил конфликты текущих security/renderer assertions и R03 fixture identity. Для них готовится отдельная test-contract derivative: production guard и исторические gold/receipts не меняются ради GREEN. Окончательная source-приёмка этой derivative ещё не получена.
- Native owner/loaded-source identity, getter versus cached manager cap, model-bound delivery и whole-plugin release acceptance остаются непроверенными. Upstream field clipping сохранён: whole rendered knowledge block не означает весь исходный graph hit.
- Публикация исходников не открывает live store. Замена уже включённого plugin через `--no-enable` не выключает его и сама по себе не доказывает отсутствие последующей загрузки. Перед live load требуется отдельный data-preservation gate: существующая owner-run Wiki backup-утилита не имеет проверенного совместимого owner-restorer (`restore_supported=false`); LCM snapshot и externalized payloads сохраняются отдельно. Снимки кода и scoped backups не являются полным backup/recovery памяти. Защитный отказ whole-store recovery не обходится.

Порядок владельца: **Wiki-релиз и YAML/.env пяти профилей → позднее отдельные hermes-security-core/subagent-memory компоненты → широкие тесты в самом конце**. Эта lane не начинает поздние компоненты и не ослабляет current mandatory security. `source_only=true`, `release_accepted=false`, `native_proved=false`.

Подробности prefetch: [PREFETCH_PACKING_SOURCE_ONLY_RU.md](PREFETCH_PACKING_SOURCE_ONLY_RU.md). Исторические notes: [1.24.0](RELEASE_NOTES_1_24_0_RU.md).
