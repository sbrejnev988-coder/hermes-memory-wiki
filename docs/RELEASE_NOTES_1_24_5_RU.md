# Memory Wiki 1.24.5 — опубликованный source, установленный code-stage

**Исходники опубликованы, code-stage установлен; runtime готовность не подтверждена.** Версия выбрана владельцем: **1.24.5**. Основной public PIN E — `42d2e943f887efda00d65ebf143adce28873103e`; secondary metadata-only PIN M — `02eed6da5b5cdba02a4fb114534730067e2d21ea`. Native installation/readback выполнены после явного решения владельца о code-only обновлении. Это не tag/GitHub Release, native feature/full-recovery acceptance или успешный CI/runtime всей композиции. Профильные настройки и owner restart — отдельные этапы.

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
- Исторический первичный static verifier отказал на ложном regex совпадении `state_token` в dynamic cache metadata. Отказ сохранён; triage verifier и его исправление не являются behavioral/runtime PASS, production bytes ради ложного совпадения не меняются.
- Старый packing RED/GREEN относится к прежним source bytes: это история, **не** свежий PASS 1.24.5.
- Focused regressions и current-source test-contract правки вошли в опубликованный/установленный code-stage; свежая tests/SDK/model/native/full приёмка этой композиции **не выполнена**. Статический prefetch/selection/owner-budget review не заменяет её. Ранее отмеченные конфликты security/renderer assertions и R03 fixture identity сохраняются как история подготовки test-contract derivative, не как свежий test result; production guards и исторические gold/receipts не переписываются ради GREEN. Code-only решение владельца не превращает старые receipts в новый PASS.
- Native owner/loaded-source identity, getter versus cached manager cap, model-bound delivery и whole-plugin release acceptance остаются непроверенными. Upstream field clipping сохранён: whole rendered knowledge block не означает весь исходный graph hit.
- Публикация исходников сама не открывает live store; native install уже выполнен в согласованном code-only режиме. `--no-enable` при active replacement не выключает plugin и не доказывает отсутствие последующей загрузки. Владелец явно отказался от нового Wiki data backup для этого этапа; это не full-recovery proof и не рекомендация другим операторам отказаться от backup. Отдельная owner-утилита не имеет принятого compatible whole-store restorer: restore/rollback disabled, `SEMANTIC_REPLACEMENT_UNPROVEN`; она не включена в plugin package. LCM SQLite/externalized payload preservation, снимки кода и scoped snapshots — отдельные договора, не full backup/recovery Wiki. Защитный whole-store recovery refusal, ACL и действующая authority удаления не обходятся.

Текущий порядок: **опубликованный exact source → native installed code/readback → разрешённые YAML/ENV и saved readbacks → ручной restart владельцем → loaded/effective readbacks → отдельно разрешённые runtime/recovery проверки**. Parent readback этого среза подтверждает 15 установленных plugin targets и 355 saved-setting значений во всех пяти согласованных профилях. Это не доказательство loaded значений на другом ПК или в ещё не перезапущенном backend. Новые GUI/MCP/workers, hermes-security-core/subagent-memory и дополнительные LCM extensions не начинаются до отдельного допуска; существующая mandatory protection не откладывается. `code_stage_installed=true`, `release_accepted=false`, `native_proved=false`, `full_recovery_proved=false`.

Текущий [переносимый русский Memory Stack guide](MEMORY_STACK_1_24_5_RU.md) содержит 63 ENV + 8 YAML targets и отделяет общий auto delivery cap 15000 от provider ceiling 48000 и большого ручного packing. Этот doc-only update не меняет runtime, metadata, schemas или tests E/M. Подробности prefetch: [исторический source-only срез](PREFETCH_PACKING_SOURCE_ONLY_RU.md). Исторические notes: [1.24.0](RELEASE_NOTES_1_24_0_RU.md).


## Последующий patch: профильный hybrid recall

Базовые E/M PIN выше описывают первоначальный code-stage; обновлённый routing/hybrid patch публикуется отдельными exact commits той же версии 1.24.5. Схемы и исходные metadata не изменены. Независимые FTS/vector ветви, ACL до выборочных лимитов, native owner contexts/cache и frozen canonical receipts описаны в [HYBRID_SEARCH_DIAGNOSTICS_RU.md](HYBRID_SEARCH_DIAGNOSTICS_RU.md).

Сохранены 58 уникальных native synthetic cases в шести выбранных завершённых receipts (44 + 14), а не единый 58-case прогон. Первый нормальный запуск 53 cases / 7 setup failures и blocked socket receipt сохранены. Source review закрыл F1/F2/F3; новые live gateway/embedding/rerank/reindex и полный release пока не подтверждены. Strict policy, credentials и защитные отказы не ослаблялись.
