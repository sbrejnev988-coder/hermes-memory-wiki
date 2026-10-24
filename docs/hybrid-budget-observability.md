# Бюджет hybrid prefetch и причины пропуска rerank

## Изменение SOURCE

Primary prefetch получает `max(0, remaining - PREFETCH_FALLBACK_RESERVE_SECONDS)`,
а не `min(remaining / 2, remaining - reserve)`. Уже настроенный резерв остаётся
для последовательного lexical fallback **и** terminal tail. Значения по умолчанию
не меняются: общий deadline 5,5 с (поддержанный clamp 5–6 с), fallback reserve
0,45 с (clamp 0,20–1,0 с). Конфигурация профилей этим изменением не редактируется.

Вложенный primary budget не продлевает исходный абсолютный deadline. После его
выхода восстанавливаются deadline/Event внешнего callback; fallback выполняется
в том же потоке после primary. Истёкший общий бюджет или cancellation по-прежнему
отбрасывают результат, включая запоздавший fallback. Owner/attempt admission,
retained UNKNOWN и terminal/disclosure fences не меняются. Это кооперативный
бюджет, **не** обещание жёсткого realtime для блокирующего native/сетевого кода.
Меньший фиксированный резерв не гарантирует, что вся локальная подготовка
успеет: при исчерпании общего окна остаётся штатный безопасный пустой результат.

## Accounting reranker

`_rerank_status()` дополнен:

- `stats_scope = "process_local_bound_profile"`;
- `skip_reasons` — отделённый снимок конечной гистограммы.

Гистограмма живёт рядом со `stats`, а не внутри числового `_RERANK_STATS`.
Import-owner и каждый bound foreign profile имеют независимые counters/cache.
Счётчики накопительные в данном процессе для данного профиля: смена generation
сохраняет их, но по прежнему правилу сбрасывает cache/circuit; restart обнуляет.
Это не durable-статистика, не fleet-total и не статистика одного user query:
варианты поиска могут принимать отдельные решения. Мутация returned histogram
не изменяет внутреннее состояние.

Конечные ключи: `disabled`, `invalid_profile_settings`, `endpoint_invalid`,
`no_key`, `query_length`, `candidate_threshold`, `secret_query`, `exact_technical`,
`circuit_open`, `safe_candidate_threshold`, `candidate_identity`,
`safe_document_threshold`, `deadline`, `cancelled`, `mode_or_disabled`,
`invalid_rerank_cache`, `document_disclosure_changed`, `other`.
Неизвестная причина сводится к `other`, без user text, URL или exception message.

`_rerank_skip` вызывается один раз на выбранном локальном skip-exit. Убраны
предварительные «skipped» receipts до фактического решения. Добавлены пропущенные
entry/cache deadline, identity/document threshold и search-level bypass.
Corrupt cache сохраняет receipt `failed` и отсутствие нового RPC; теперь его
локальный отказ также включён в `skipped`/гистограмму. Уже существовавший discard
после disclosure withdrawal учитывается прежним смыслом, без изменения fences,
response accounting или identity-guarded cache cleanup. Исключения, которые
исходный disclosure guard распространяет наружу до transport try, не превращены
в новый локальный fallback. Optional accounting/receipt errors не разрешают I/O
и не заменяют выбранный возврат; первичная cancellation не поглощается.
При уже распространяющемся fatal disclosure-исключении отказ optional diagnostics
не заменяет exact original primary. Без pending primary новая cancellation
по-прежнему распространяется, а не превращается в успешный skip.

Порог кандидатов, exact-technical skip, content/ACL guards, cache key, circuit,
rank fusion и последний HTTP admission не ослаблены. Rerank не безусловен:
достаточные безопасные кандидаты и остаток бюджета только допускают существующий
transport path. Чужая visibility/secret/native authority этим тестовым блоком
не квалифицируется.

`requests` сохраняет прежнюю семантику, включая некоторые доответные ошибки:
**не** называйте его числом физических HTTP. Cache hits и skips тоже не HTTP.
Для различения embedding cache reuse, deadline и adapter attempts используется
неизменённый per-attempt `_observed_semantic_http` trace (`http_issued`, terminal,
usage/response validity при наличии). Даже `http_issued` — marker входа в adapter,
а не подтверждение доставки/успешного ответа модели. Новых egress-counters перед
последним admission нет.

## Регрессии и запуск родителем

`tests/test_hybrid_budget_observability_source.py` содержит один standalone
`HybridBudgetObservabilitySource`, полный упорядоченный roster — `CASE_METHODS`.
Collection инертна: только stdlib imports/definitions, без чтения source,
plugin import, SQLite, SDK или model calls. `__test__ = False` отделяет explicit
suite от обычного pytest-контракта; actual pytest collection здесь NOT_RUN.

Родитель после freeze использует неизменённый `devtools/harness.py run_source`
и `source_bootstrap.py`, загружает bound test module как **non-main**, затем:

```python
suite = module_namespace["source_suite"](
    source_loader, expected_sha256=raw_main_sha256,
    filename=str(scratch / "candidate_main_from_bound_bytes.py"),
    semantic_loader=semantic_loader, semantic_sha256=raw_semantic_sha256,
    semantic_filename=bound_semantic_path,
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
# testsRun == len(module_namespace["CASE_METHODS"]), no failures/errors/skips;
# source-bootstrap/audit/supervisor outcomes проверяются отдельно.
```

`source_loader()` и `semantic_loader()` явно возвращают полные **bytes** точного
main и неизменённого `semantic_io.py` из pinned baseline. Его обычный binding
нужен для exact `SemanticIOError`, `_cap`, `request_bytes` и `REQUEST_MAX_BYTES`:
ни imports всего модуля, ни подставного exception class. Первые чтения только в
`setUpClass`, за исходным audit fence. `source_suite` создаёт настоящие
`TestCase(method_name)`/`TestSuite`; нельзя вызывать `test_*` непосредственно.
`setUp`, `tearDownClass` и unittest subtests остаются штатными. `__main__` данного
файла намеренно отказывает без binding, а не запускает неявный импорт продукта.

Main больше 1 MB: не повышать binder guard и не передавать oversized binding.
Допустим metadata-only zlib carrier с exact raw size/SHA, проверенным roundtrip
и capped decompression, либо byte-exact parts. Для zlib использовать
`decompressobj().decompress(carrier, raw_size + 1)` и потребовать точный размер,
`eof`, пустые `unused_data`/`unconsumed_tail`; SHA дополнительно проверяется в
`setUpClass`. Carrier/test/entry входят в обычные source bindings. Имя compiled
source выбирается под own scratch (файл создавать не требуется), чтобы formatter
не пытался перечитать unbound physical main при ошибке. Реальный raw source path,
Git PIN и SHA фиксируются metadata родителя. Новый bootstrap/framework не нужен.

Уровни проверок:

- 01–07: exact extracted `prefetch`/budget bodies, synthetic clock/receiver;
  различающий primary `>half` и `<outer`, configured/tiny reserve, serial fallback,
  late primary/fallback discard, cancellation, explicit/nested deadline/Event unwind.
- 08–13: exact `_rerank_rows` и helpers с явно synthetic settings/content decisions;
  early reasons, filtering slots, identity, document threshold, entry/network/cache
  deadline, cache hit/corruption и отсутствие двойного skip event.
- 14: исполнение точного условного **среза** `_search`, не полного SQL search;
  bypass/mode/deadline/cancel и healthy handoff в `_rerank_rows`.
- 15–16: настоящий extracted state/status/skip helper; synthetic profile mapper,
  detached histogram, profile/generation isolation и optional recorder refusal.
- 17: healthy synthetic candidates доходят через exact `request_bytes` и
  `_observed_semantic_http` до adapter denial. Route/content decisions synthetic;
  adapter бросает собственный `BaseException` **без HTTP/response**. Это не mock
  успешного провайдера и не native/physical-transport proof.
- 18: **STATIC** fingerprints неизменённых owner/cancel/budget/terminal/disclosure/
  transport/config/fusion bodies и constants относительно pinned baseline.
  Настоящая disclosure-withdrawal runtime composition остаётся NOT_RUN.
- 19: исполнение exact outer exception-handler с owned synthetic primary и
  отказом optional diagnostic (`Exception`/`BaseException`), сохранение identity
  primary и уже полученного response accounting; отдельно новая cancellation без
  pending primary. Это не исполнение настоящего privacy guard или native I/O.

Первый parent SOURCE packet сохранил 17/18 PASS и fixture-only FAIL в 14: на
синтетическом clock `100.2 - 100.0 > 0.20`. Отрицательный control исправлен на
точно представимое `0.125`, добавлен отдельный healthy `0.25`; product comparison
не менялся. Оригинальный FAIL сохраняется, новый полный roster содержит 19 mains.

Автор не запускал import/main/test/collection/py_compile. Подготовлены code/tests/
docs и локальный candidate; выполнены только AST/raw-byte/Git metadata проверки.
SOURCE packet, независимое review, adoption, SDK/native/live и release acceptance
остаются отдельными этапами родителя.
