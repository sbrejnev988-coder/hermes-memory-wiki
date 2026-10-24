# Current hybrid cohort: отдельный test-only compatibility блок

Baseline: `ec87e40a1974cfbc36f777186d05178566e889ce`, tree
`9486355683ed2f9e8ddb379870cdbc66fda7dcdf`. Runtime и принятый
`test_hybrid_budget_observability_source.py` не меняются. Этот блок не повторяет
их SOURCE-приёмку и не возобновляет исчерпанные native/CI этапы.

## QG-1: current pins и historical gold — разные роли

- Actual LF `__init__.py`: `44cdca1b753f13650fcb9c9fb9bdec9192a9f7c11cdffbe91163abe64dd02805`.
- Производный CRLF: `cdf6ccc05ece2d823522203656308581dd9b0db4829f963c7b499d285aacb5dc`,
  строго `sha256(raw.replace(b'\n', b'\r\n'))`, без нормализации исходника.
- G4 test_08 и review-boundary operand используют новый literal. EOL PUBLIC
  меняет только current provider tuple, не gold fixtures и не Git assertions.
- Старые `8007b015...` / `6c1de6f4...` остаются историческими witnesses. Три
  `ORIGINAL_TESTS*` таблицы и selector CPython 3.11/3.12/3.13–3.14 сохранены.
  `historical_method_dumps` проверяет конкретный ClassDef/FunctionDef/Call,
  требует literal нового pin и заменяет только этот operand обратно на `8007...`
  **перед** прежним `ast.dump(include_attributes=False) → sorted →
  json.dumps(ensure_ascii=True, default separators) → encode → sha256`.
  Новые неизвестные parser digests не вычисляются догадкой; неизвестный parser
  или pin/expression явно отказывают. Динамически вычисленный current digest
  не становится ожидаемым gold.
- Инертный CPython 3.14.7 producer даёт current G4 fingerprint
  `4e0eb6a2bd04ecbc43cfc14c3cbcbc3491772f3f97dc8239393f8c3da1f03f42`;
  точный inverse возвращает прежний
  `ea6341d85a25afc3f00fd79039046417bdd2b64ff15d75483474852bcb18f84e`.
  Это AST/hash metadata, не исполнение G4. Новые текущие 3.11/3.12/3.13
  fingerprints не заявлены. Их исторические профили проверяются исходным
  producer после того же typed inverse, без эмуляции parser fields.

## QG-2: census и действительный SOURCE entry

`docs/COLD_LANES.json` теперь описывает **357** test Python файлов и **16**
отдельных source pins: прежние355 + принятый standalone hybrid + новый
compatibility suite. Это полный **логический** census, не полный checkout.
Все unchanged bytes берутся readonly из предыдущих источников и сверяются с
Git blobs; sparse worktree не раздувается. Source/native unions остаются
раздельными, реальные Core/trust origins и closures — null, admission — false.
Старый descriptor rebind сохранён в `closure_scope.previous_rebind`.

`source_suites.run_suites` умеет только запускать direct `__main__` для прежнего
8+2+10 roster. Новый hybrid direct main намеренно отказывает; его `source_suite`
требует provider и semantic loaders. Поэтому добавлен только маленький test-owned
`scripts/ci_owned/hybrid_source.py:make_suite`: SHA-проверка test declarations,
вызов исходной factory и настоящий `unittest.TestSuite`. Он не импортирует
runtime/SDK, не создаёт controller и не меняет audit/qualifier. Старые
`source_suites.py` и `fixture_prerequisites.py` byte-unchanged; новый маршрут не
выдаётся за их native prerequisite PASS. `__test__=False` не доказывает native
совместимость; validator проверяет explicit entry, inputs, factory signature и
SOURCE-only prerequisites даже при ложном absence flag.

## Один подготовленный пакет, без авторского запуска

Точный executable, candidate/tree, bindings и ordered roster находятся в
`repairs/hybrid-current-cohort-20261024/SOURCE_PACKET.json`; entry —
`source_entry.py`, invoker — `source_packet.py` в той же lane. Parent после
freeze/readback и собственного admission может выполнить invoker выбранным
Python с `-I -B -S`. Используется неизменённый `devtools/harness.py.run_source`
и `source_bootstrap.py`, не canonical CLI с его historical aggregate gate.
Scratch/output — только literal paths из REQUEST, не project runtime aliases.

Пакет: прежние ColdPartition41 + current-composition14 + новые compatibility14
+ hybrid19 **через новый maintained entry**. Последние19 требуют отдельного
parent admission именно как интеграция изменённого entry; это не bookkeeping
повтор принятого hybrid и не новый runtime repair. Все88 — ожидаемый roster,
не PASS. Сохраняются исходные unittest setup/teardown/cleanups и CaseResult;
subtests, AST/static controls, expected historical violations и extracted
composition не смешиваются с native coverage. Старый55 report сохраняется
отдельно в новом scratch с SHA/ref, не урезается ради итоговой сводки.

Retained `COLD_TEST_INPUTS.zlib` и `COLD_ENTRY_INPUTS.zlib` используются readonly.
`COLD_OVERLAY.json` задаёт только отдельные bound raw/zlib inputs: новые/изменённые
файлы, semantic/gold/entry pins и retained exact44cd compressed main. Новых полных
bundles/archives нет. Исторические old322/354 + stale16 controls используют
retained bytes **до** overlay; plain unbound direct composition main не получает
их молча. Документы и raw transport mappings не являются исполняемым FULL.

Авторская проверка ограничена AST/raw/hash/JSON/Git. SOURCE packet, G4 runtime,
actual local-Git EOL fixtures, pytest/native SDK, SQLite, HTTP, model, CI,
publication, installation и loaded-runtime: **NOT_RUN**. Actual parent execution,
независимое whole-delta review и adoption/rollout остаются отдельными этапами.
