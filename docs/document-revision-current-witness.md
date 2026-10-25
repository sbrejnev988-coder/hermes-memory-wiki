# Current witness document346: отдельный test-only контракт

## Что теперь считается текущим

`docs/COLD_LANES.json` остаётся неизменной исторической partition authority:
357 test `.py`, прежний main и прежние transport pins. Его SOURCE checkpoint
не переносится на document346 или изменённые тесты.

`docs/DOCUMENT_REVISION_CURRENT_WITNESS.json` — отдельная версия **подготовленных**
метаданных. Она содержит полный `current_plan`, а не новый runner:

- immutable product commit `346778f6e315143a5e0072cf3d0a686980d79c5f`, tree
  `437d9cd274e24038e5d86d007263e0c41da61e62`;
- 358 baseline test `.py` + один новый current-witness test = 359;
- все исходные rows/roles/entries/peers, дополненные отдельными SOURCE/STATIC
  контрактами citation suite и metadata witness; новый schema regression
  добавлен к существующему полному roster, а не вместо него;
- независимые raw Git identities всех rows и 50 source pins, включая полный
  35-file runtime inventory и неизменный MCP cache;
- `NOT_RUN` для новых TestCase bodies, current-partition execution,
  genuine export/SDK/SQL/CI. Унаследованные evidence-поля — только история
  на их исходных pins, не квалификация текущего дерева.

При отдельном допущенном использовании существующий
`ColdPartitionTests.setUpClass` выбирает новую версию **только** при явном bound
input `DOCUMENT_REVISION_CURRENT_WITNESS.json`. `document_current_plan` требует
точный raw исторический descriptor, version/product PIN и закрытые native flags.
Без этого bound input исторический descriptor не мигрирует автоматически.
Отдельная direct/full-checkout metadata ветвь явно выбирает именованный новый
descriptor по точному пути и той же проверке historical raw SHA; sparse author
tree не является пригодным для неё полным checkout. Все прежние 41 тела тестов
и validator `tests/cold_lane_entry.py` сохранены.

Новый descriptor — JSON envelope; в существующий cold validator передаётся
именно его `current_plan`, не envelope. Никакие admission/origin поля этим
не заполняются. `ColdCurrentCompositionTests` и `HybridCurrentCohortTests`
описывают новую census359, но их выполнение на этих bytes ещё не проводилось.
Исторические old322/354, stale16 и retained355 controls остаются исходными.

## Main, inverse и parser matrix

Current LF main:
`16f06dbffaeccfcce7d34c7180c9929e14d7046fa3d3a1dbf276f35b6007a469`.
Exact LF→CRLF projection:
`4cd2aeb3d83f996bfc465ca9761ee1e014e37b303f9cf3c5cf056046b5926245`.

Только current operands G4/EOL/prerequisite/review и `CURRENT_*` hybrid
перепривязаны к этим independently frozen bytes. G4 сохраняет audit/network
refusal tail. Его один typed assertion operand инвертируется до ORIGINAL8007
перед прежним producer: `ast.dump(include_attributes=False)`, sort,
`json.dumps(ensure_ascii=True)` с исходными default separators, UTF-8, SHA256.
`ORIGINAL_TESTS`, `_311`, `_312`, hybrid `OLD_PIN/OLD_CRLF` и fixture gold
не изменены. Полные исходные bytes доступны в immutable baseline346 Git.
Hybrid review inverse дополнительно удаляет только отдельно raw-hash-bound
finite-hook overlay и возвращает исходный loop operand, прежде чем требовать
полного равенства retained review bytes. Новый helper не маскируется literal-only
заменой и не выдаётся за исторический test body.

`ast.dump` не wire format между версиями. Для уже неизменных двух audit hooks
сохранены исходные G4 gold CPython3.13/3.14, добавлены independently parsed
literal3.11/3.12 variants и явный отказ неизвестной версии. Значимые поля AST
не удаляются. Целевая workflow matrix остаётся Linux/Windows × Python3.11–3.14;
локальный parse/hash на Windows не является выполнением этой CI matrix.

`docs/HYBRID_CURRENT_COHORT_RU.md` вне author allowlist сохранён как историческое
описание прежнего checkpoint. Для current document346 ролей действует этот
документ; старые receipts не перепривязаны.

## Cache и runtime inventory

Исторические `CACHE_SHA256`, `CURRENT_CACHE_SHA256_SOURCE_20261009` и
`_20261023` остаются literal. Новый `_20261025` используется только как
current-source oracle:
`674d9e94ca1e7c0bc86561b0d217edb2a7a5d6844f296b69c05a87b43707cd14`.

Native package test по-прежнему обязан сравнить полные native dictionaries,
121 unique tools, manifest order и MCP translation без cache writes. Добавлен
регрессионный контракт точного optional `expected_revision_id` у двух lookup
инструментов. Остальные 119 cache records сохранены полностью. Genuine exporter,
release wrapper, diagnostics и обязательные CI gates не заменены AST-проверкой;
их запуск здесь **NOT_RUN**. Nonzero exporter не переименовывается в cache drift.

`SOURCE_FILES` egress fixture сохраняет все 35 имён и исходные guards. Новый
current inventory вычислен по полным independently bound Git blobs тем же
`json.dumps(sort_keys=True, separators=(',', ':'))`/SHA256 producer. Прежний
inventory literal сохранён отдельно. Это identity repair, не выполненный
provider/SQL/egress packet и не доказательство полноты native import closure.

## Intended delta вне row loop

Прежнее требование «весь graph, кроме row loop, неизменен» не подходит к
намеренно добавленным helper, revision SELECT/predicates/parameters и output.
`document_revision_inverse` выполняет **только metadata** inverse:

1. требует точный document346 graph;
2. проверяет raw spans `_document_lookup_revision`, `document_unit_context`,
   `document_neighbors` против independently bound current digests;
3. удаляет только новый helper с точной newline boundary, восстанавливает два
   literal original owner spans из pre-revision028;
4. требует byte-exact SHA полного исходного graph.

После inverse исходный outside-loop AST/raw prefix/suffix oracle сохранён.
Сами loop assertions и terminal/source/connector/watch guards проверяются на
**неинвертированном** current owner; дополнительно проверен порядок revision
после authorization и до XLSX/read effects. Произвольное изменение внутри
исключённых owners нельзя спрятать проекцией: полные current spans pinned.

Новый `DocumentCurrentWitnessTests` каталогизирует 12 инертных metadata
регрессий: census/membership, history/gold, LF/CRLF/inverse, transitive recipe,
full cache delta, full35 inventory, graph inverse/typed preservation, intended
SELECT/parameter/output/fence AST, drift controls, no-authority flags и untouched
old41/schema bodies. Factory требует отдельные current/historical inputs и
исходные cold/partition/order test modules. Это не автоматический test entry.

## Граница допуска и приёмки

Полный main больше runtime per-file allowance. Metadata ceiling2MB **не**
разрешает его SOURCE binding: ни explicit bindings, ни compression, ни guard
changes не применены. Новый transport/SOURCE entry/framework не создавался.

Author выполняет только AST/JSON/raw hash/local Git metadata и локальный
checkpoint commit. Ни collection, ни TestCase/helper/product bodies, SOURCE,
SDK, SQL, exporter, native/model/network/CI, install/restart не запускались.
FND925 не включён; исходный standalone CARRIER gap baseline346 не исправлялся.
Исчерпанные document/FND SOURCE1/1 и остальные holds не пополнялись. Приёмка,
independent review, qualification и интеграция принадлежат родителю.
