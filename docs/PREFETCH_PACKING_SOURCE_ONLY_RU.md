# Prefetch: целые units, raw delta и профильный предел

**Статус: source-only. Новый кандидат не установлен и не опубликован; `release_accepted=false`, native/model acceptance отсутствует. Свежие тесты по решению владельца отложены до публикации/обновления.**

## Что исправлено в исходнике

- Подготовленный public source353 сохранён целиком. Старый installed `__init__.py` использован только как общий baseline настоящего three-way переноса packing patch, не как замена публичного кода. Сохранены новые literal-data renderers, guards, CI, ACL и остальные публичные слои.
- Guard-safe claim вместе с metadata/why/evidence, delta, shared fragment, episode, trusted block и opaque knowledge block пакуются целиком. При overflow исключается полный unit вместе с принадлежащими ему заголовками. Cache/wrapper пересобираются из оставшихся units; если обязательная оболочка и доказательная память не помещаются, возврат пустой. Social, lexical fallback и withheld ветки тоже не режут строки.
- `_select_recall_rows` сохраняет **raw** delta до main/delta dedupe. Ack требует доставки каждой raw пары `(id, memory_revision)` через финальные main/delta units. Shared excerpt, пропуск по бюджету/guard/deadline, другая revision того же ID и отсутствие raw-контракта не являются coverage. При любом пробеле старый watermark консервативно удерживается; cancellation guard сохранён.
- Existing rendered/delta/episode counts, claim-char counts и shortfalls пересчитываются после удаления. Локальный `episode_rendered_chars` уменьшается на длину исключённого encoded episode; отдельного поля с этим именем в прежней diagnostic whitelist нет, новая schema не добавлена. Optional diagnostic line формируется из финальных counts и исключается целиком, если не помещается.
- В публичном `prefetch` ДО внутреннего bare thread вызывается штатный `get_spill_config` под context-local owner home через публичные API Hermes. При enabled spill предел равен `min(MAX_PREFETCH_CHARS, owner max_chars)`, при disabled — исходному provider ceiling. Значение явно передаётся worker и обоим fallback путям. Owner/native callback недоступен — fail-closed пустой prefetch. Process ENV и cached MemoryManager spill config не изменяются.

## Что сохранено

Guard admission, candidate/ranking limits, field caps, deadlines, ACL, владельцы, durable partition/state/index revision contract, cache version/fields, tool schemas и manifests не менялись. Private direct `_prefetch_impl`/lexical callers без нового аргумента сохраняют прежний provider ceiling; native callback всегда передаёт owner snapshot явно. Upstream knowledge renderer/guard field clipping остаётся прежним: гарантируется whole **guarded rendered block**, не полный исходный graph hit.

## Проверки и оставшиеся границы

Разрешены только raw hashes/inventory, three-way/diff replay, AST и syntax compilation без imports/исполнения продукта. Старый saved packing GREEN относится к прежним bytes и не принимается за проверку этого кандидата. Старые tests, gold, failures и receipts не изменены.

Будущие focused regressions находятся в `tests/test_prefetch_delivery_packing_regression.py`: точная граница 15000 Python characters, whole-unit overflow, raw delta/main dedupe, identity/revision mismatch, пропуски guard/budget/deadline/shared, cancellation, final counters/diagnostic line, пустая оболочка, ancillary paths и interleaved owner caps пяти синтетических профилей. Они написаны, но **не запускались**.

До native acceptance остаётся проверить реально зарегистрированный owner и совпадение свежего profile getter с cached host spill snapshot. Config-cache invalidation не обновляет уже созданный MemoryManager; кандидат его не патчит. Также не доказаны loaded-profile bytes, фактическая model-bound доставка, host timeout/delivery acknowledgement и whole-plugin release gates. Независимое review кумулятивной дельты и дальнейшие публикация/установка/тесты принадлежат parent lane.
