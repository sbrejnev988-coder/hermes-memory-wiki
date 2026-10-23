# CI foundation: воспроизводимые prerequisites и границы

## Что поставляется

- `tests/test_memory_diff_polarity.py` берёт собственный `tmp_path_factory`, а не
  `RECOVERY_DIAGNOSTIC_OUT` внешнего recovery controller. CI-C01 удерживает
  настоящий caller-home override (`hermes_constants`) и пустой настоящий
  `agent.secret_scope` этого home от initialize через yield до shutdown. Вложенные
  `finally` возвращают точные tokens даже при initialize/test/shutdown/assertion
  failure; отказ установки secret scope тоже возвращает home token.
  Это fixture-only исправление: runtime SDK/DisclosureFence не изменены, genuine
  lifetime всех21 параметризованных cases здесь **NOT_RUN**.
- Observation finite/repair используют поставляемый autouse setup в
  `tests/conftest.py`: отдельный root каждого item и явные event/background
  параметры. `TMPDIR`, `WIKI_G2_FIXTURE` и предустановленный background flag больше
  не нужны при collection. У обоих файлов сохраняется один настоящий provider,
  native context/secret scope, SQLite, JobStore и старые assertions.
- Prefetch diagnostics сохраняет наблюдения в собственный pytest temp. Отсутствие
  именно модуля `hermes_trust_core` — явный optional SKIP/NOT_RUN, не PASS. Ошибка
  его внутренней зависимости, несовпадение genuine API или
  `MW_REQUIRE_TRUST_CORE=1` не пропускаются. SDK база не подменяется.
- Два G4 файла — **SOURCE**, не optional SDK tests. Они проверяют отсутствие SDK
  и устанавливают process-global audit hooks. Их нельзя безопасно исполнять в том
  же процессе, где уже загружен native provider. Collection теперь не требует
  их ENV и не ставит hooks; standalone setup сам создаёт synthetic root.

## Исполняемое разделение SOURCE / native

`source_suites.py` — минимальный adapter поверх существующего `unittest`, не
новый test framework. Он запускает каждый из двух G4 файлов и additive tooling controls в отдельном
`python -I -B -S`, с allowlisted credential-free environment и immutable логами.
Полные старые методы исполняются без skips. Parent/subtest outcomes сохраняются
раздельно; неуспешный subtest запрещает parent PASS.

```
python -B scripts/ci_owned/source_suites.py --output <NEW_OWNED_OUTPUT>
```

Существующие `packaging/run_native_regressions.py` и hosted
`memory_wiki_ci.py` выполняют этот SOURCE roster **до** native bootstrap/.pth.
Только после полного успешного результата всех трёх SOURCE файлов на тех же
source bytes `native_pytest_args` выдаёт три точных `--ignore=<SOURCE file>` для
native pytest. Оригинальные G4 дают10 cases; tooling controls — отдельные10.
Это разделение разных import/security domains, не blanket skip/deselect и не
снятие старых assertions. Missing/failed/skipped/stale SOURCE packet блокирует
native continuation. Остальное ordinary discovery не фильтруется. `--confcutdir`
предотвращает ненужный ancestor package setup в checkout с дефисом в имени.
Raw `pytest tests` не является поддерживаемым объединённым gate: G4 откажет
при уже загруженном SDK, а не ослабит свои условия.

Исторические SOURCE output/assertions остаются видимыми. CI-O01 разрешена
координатором в отдельном correction candidate: ровно одна expected Constant
`G4Tests.test_08_direct_boundary_preservation_and_network_denial` мигрирует
с `bb6815f0f00f9f208f23727d5fa1c09c969eac87326fad5a29b434ac5b9bbf6f`
на immutable accepted-a4 raw SHA
`0b4fc9bc4bf914318a54237a977819d75533a1c1eaaedcc401e716703fbfc8d2`
(Git blob `c88a7e1ad748078490c161be3c618a21ba8d84ed`; a4 и bdbef byte-equal).
Соответствующий digest8 methods в `ORIGINAL_TESTS` —
`ec7dc331f9500ca9d730366833988db3f57d016be01fe5a3da3fbe564e278c7f`.
Expected не вычисляется из current/HEAD; другие31 прежних методов и оба gold
не меняются. Будущая интеграция другого provider требует отдельного exact rebind.
Старый pin FAIL и его network tail NOT_REACHED остаются историческими.

### CI-C02 и ограниченный correction packet

Collection обоих G4 теперь оставляет только stdlib/test infrastructure и
неисполненные объявления: product globals — `None`. `setUpClass` создаёт own
fixture, устанавливает **исходный** audit hook и лишь затем импортирует
collapse/Drive, проверяет origins и (repair) читает/исполняет public AST closure.
NetworkDenied, SDK-absence, READ_ROOTS, WRITES и unexpected-event проверки
не ослаблены; irreversible hook во время collection не ставится.

`test_foundation_ci_review_boundaries.py` добавляет семь SOURCE controls:
whole-module inert collection с отказом product-import/nested-exec/hook,
порядок setup и exact исходные hooks, genuine imports и структурное покрытие
всех token-reset exits, immutable pin/network tail, отказ native continuation
для subset и compile. AST lifetime/order PASS **не** genuine SDK lifetime proof;
общий native путь этого нового файла не требует отсутствия SDK.

Локальный supplemental adapter переиспользует `h.supervise`, оригинальные
TestCase/setUpClass и `CaseResult`; единственная selector delta исключает
**исполнение**, но не тело/roster, G4 `test_03` с `sqlite3.connect(':memory:')`.
Полный shipped identity entry и SOURCE20 **BLOCKED/NOT_RUN** в этом correction:
новых SQL connections (даже in-memory), SDK/provider/bootstrap/Vault/hosted/paid
allowances — 0. Старый test_03 PASS не переносится через изменённый setup.
Допустимы лишь три непересекающихся children: tooling10 + additive7, G4 nonSQL7
(включая настоящий test_08 NetworkDenied), repair2. Это subset, не whole20,
не новый native continuation; полный shipped roster и его guard сохранены.
Предыдущие6 children/40 main attempts/20 unique и оба outer1 сохраняются,
current outcomes/отказы и точный executed candidate — в correction RESULT.
Без retries; при отказе сохраняется actual outcome и packet останавливается.

## Чистый startup/save/recall target

Без Core edits используется тот же native loader и тот же `CORE_SHA`/dependency
contract из `packaging/run_native_regressions.py`. Новый режим:

```
uv run --with pytest --with PyYAML==6.0.3 --with ruamel.yaml==0.18.16 --with openai==2.24.0 --with httpx==0.28.1 --with pydantic==2.13.4 python -B packaging/run_native_regressions.py --core <PINNED_OFFICIAL_CORE> --gate startup --fixture-root <NEW_OWNED_ROOT> --trust-core <GENUINE_DELIVERY>/hermes_trust_core.py --trust-sha256 <EXACT_LOWERCASE_SHA256>
```

Это runnable **native provider component** target, не разрешение на его запуск.
Требуются свежий native admission, чистый официальный core на существующем pin,
реальные import dependencies, genuine trust delivery с origin/SHA, новый root и
самостоятельный процесс. Никакого installed plugin, live home, .env/auth/DB,
скопированного profile либо stand-in SDK. Root никогда не сбрасывается/не
переиспользуется; environment очищается до provider import. Trust обязательна
для этого режима: policy0 fallback не считается проверкой strict save/recall.

`provider_startup.run` проверяет genuine MRO/registry/trust, initialize на
synthetic home, публичный `memory_wiki_add_claim`, реальную сохранённую строку,
публичный FTS query с тем же claim ID, shutdown, новый экземпляр на том же store
и durable public recall. До genuine native imports установлен audit-запрет
network/process calls (не OS sandbox). Pending review не превращается в stored. Успешное
завершение записывает `provider-startup.json`; исключение/отсутствие receipt не
считается PASS. Model/vector/network и host MemoryManager/bootstrap не выдаются
за выполненные. Новые scanner/install/restart/Core/SDK/PM права не появляются.

## Регрессии и результат

`tests/test_foundation_ci_prerequisites.py` — stdlib SOURCE controls: чистая ENV,
реальный импорт G4 без carriers/hooks, точный split и его отрицательные controls,
учёт failed subtests, transitive-vs-optional import predicate, переносимый setup,
compile и неизменность старых behavioral test-method AST относительно a4.
Статический startup контроль не исполняет native provider.

Фактические local outcomes, exits, hashes, полные stdout/stderr и оставшиеся
блокеры записаны в lane `evidence/RESULT.json`. SOURCE не является native CI,
hosted OS matrix, whole suite, loaded/runtime/fleet или release acceptance.
GitHub CI и старый cold gate в этой работе не запускаются; прежние бюджеты
cold3/3 и native0 сохраняются. Приёмка/интеграция — только родителю.


## CI-O02: cumulative SOURCE на current common63a (только static)

Этот кандидат переносит весь cumulative CI delta a4 → bdbef → C465 (15 файлов)
на common `63a45fc10a90fcc4f63d5cd0667e0722949982c9`, tree
`1a931b4ab7e91fb36d6f4984ea900e0f021bf371`. Предыдущие разделы CI-O01 и
«ограниченный correction packet» описывают **исторический C465**, не новый запуск.
Исходные26 main PASS на C465 =17 tooling +9 product SOURCE;41 subtests отдельно.
Они не переносятся как PASS этого кандидата. Вся cumulative chain пока не принята;
полное независимое review и любое принятие/интеграция остаются родителю.

Единственный новый oracle rebind CI-O02 заменяет literal expected в test_08
с historical accepted-a4 `0b4fc9bc4bf914318a54237a977819d75533a1c1eaaedcc401e716703fbfc8d2`
на заранее разрешённый raw SHA current `__init__.py`
`f7c896a12a43dff50de99d45b02c496ccf1eabe00c9afc834a8b6d2f59182985`
(mode `100644`, Git blob `68fc7b56cb497e695cb53437d76317a5253cb1d6`).
Тот же literal меняется в `test_foundation_ci_review_boundaries.py`; digest8
в `ORIGINAL_TESTS`, пересчитанный исходным AST/JSON producer, теперь
`8017b80c0d73939d4ad390d5ff77b65863b9feae04b39b83a46c416dad172d92`. Expected остаётся literal, не SHA(current/HEAD)
во время теста. Historical CI-O01/digest8 выше, оба gold, первичные receipts,
31 другой behavioral method, hooks, NetworkDenied tail, SQL test_03 и полный
SOURCE20/native-continuation guard не меняются. CI-C01 own caller/secret context
через cleanup и CI-C02 inert collection/setup-before-product сохранены.

Новых SOURCE/native/SQL/SDK/model/network/pytest-import/collection запусков — **0**.
Выполнены только raw/Git/AST и compile-without-exec проверки; новые test/product
modules, тела и scripts не исполнялись. Исторические initial CI6 и correction CI3
(remaining0), M4 SOURCE1, Luna SOURCE3, Windows SOURCE1/native2 остаются spent;
это не новый grant. Whole SOURCE20/identity entry, genuine CI-C01 lifetime21,
SDK/startup/hosted/native/FULL/installed/loaded/live/release остаются unqualified.
Точный frozen candidate и static proof — только в этой lane `evidence/RESULT.json`;
исторические outcomes/отказы остаются по прежним ссылкам, не переписываются.

## CI-SCHEMA-01: cache и диагностика release-contract на d390

В исходнике d390 общий `document_options` уже расширен, а packaged
`mcp-wrapper/tool_schemas.json` остался прежним. SOURCE-сверка полных словарей
показывает дельту только у `memory_wiki_document_ingest` (20 добавленных свойств)
и `memory_wiki_document_scan` (21, включая `ocr_language`). Имена/порядок всех121
инструментов, прежние свойства, required и остальные119 словарей не меняются.
Cache теперь содержит те же PDF/OCR опции, defaults, enum, bounds и описания
понижаемых owner ceilings, что и объявленный метод. Это ремонт публичного cache,
не изменение parser/SDK/provider lifecycle.

Нативный `packaging/generate_tool_schemas.py --check` остаётся обязательным:
реальный provider import и `MemoryWikiProvider().get_tool_schemas()` не заменены
SOURCE-режимом. Exit2 + `MCP_SCHEMA_CACHE_STALE` означает завершённый export и
validation с несовпадением cache. Ошибки export/validation/read/write дают exit1,
`MCP_SCHEMA_GENERATION_FAILED stage=...` и исходный traceback. `verify_release.py`
сохраняет exit и оба потока неуспешного schema child вместо безусловного
утверждения «cache differs». Успех SOURCE не отменяет этот native release gate.

`tests/test_tool_schema_source_parity.py` — инертный при collection stdlib
regression. Он исполняет только exact self-independent owning schema method,
сверяет полные словари/порядок/UTF-8 LF render с cache и manifest, проверяет pinned
MCP major compatibility, nested drift и различение диагностик. Native export и
subprocess records в diagnostic controls явно injected; это не SDK/процессный
native proof. Локальный packet использует unchanged `devtools/harness.py`
`run_source` и минимальный exact method carrier меньше binder cap1MB; полный
origin raw SHA/Git blob/mode связан отдельно. Guard/caps не расширяются.

Исторический автоматический run39902744179 завершился failure во всех8 jobs
до suites на `verify_release.py`. Его generic сообщение без child stdout/stderr
**не доказывает**, что actual child отказал именно из-за stale cache; историческая
причина остаётся INCONCLUSIVE. Подтверждённая здесь SOURCE-дельта — отдельный факт.
Результат единственного разрешённого packet, actual exits/captures, frozen
commit/tree и границы находятся в
`repairs/ci-schema-contract-20261023/RESULT.json` проекта, не в этом narrative.

Native generator/SDK/bootstrap/SQL, Linux runtime, hosted CI/matrix, FULL,
install/loaded/fleet/release acceptance здесь **NOT_RUN**. В исходном пятифайловом
этапе старый exact cache pin в `test_audit_package_contracts_20261003.py` оставался
вне writable scope. Его последующий отдельно разрешённый SOURCE-only rebind
описан ниже; это не native acceptance. Настоящие профили не менялись;
независимое review и приёмка candidate остаются родителю.

## CI-SCHEMA-02: fixture qualification и current-cache input rebind

Первичный `5265` RESULT остаётся `BLOCKED/fixture`: child0/outer1 и три audit
refusal не переписаны в PASS. Последующий finite diagnostic с passive audit
observer, установленным до byte-exact stock bootstrap guard, наблюдал три
`open("<unknown>")` из CPython3.14 traceback caret formatting через `ast.parse`.
Это attribution нового diagnostic, не восстановленный caller старого packet
или исторического GitHub CI. Guards, provider и assertions не ослаблялись.

Отдельный final SOURCE packet использует штатный selected interpreter с
`-I -B -S -X no_debug_ranges` и свежим собственным `-X pycache_prefix=...`.
Отключены лишь необязательные column/caret debug ranges; обычный исходный
traceback, stage и exception checks остаются. `-B` и пустой owned cache prefix
исключают прежние compiled stdlib debug ranges без записи в глобальный cache.
Существующие public supervisor/interpret и stock bootstrap переиспользованы,
нового guard или SDK stand-in нет; observers в final child отсутствуют.

Выполнен весь прежний roster: **20 shipped regressions +1 expected baseline
violation**, child/outer0/0, audit refusals0, supervisor `errors=[]` и
`primary_error=null`, complete stdin/captures/reap/ownership. Own pycache prefix
после запуска пуст. Точный runtime/input/capture binding и scope находятся в
`repairs/ci-schema-contract-20261023/source-qualification03/RESULT.json` проекта.
Это SOURCE qualification выбранных функций/синтетических diagnostic seams,
не genuine provider/SDK/native export, ordinary pytest collection или CI PASS.

Отдельный source-only input rebind добавляет
`CURRENT_CACHE_SHA256_SOURCE_20261023` для принятой additive cache-дельты и
переводит только три current native-test consumer references на этот exact SHA.
Исторические `CACHE_SHA256`, `CURRENT_CACHE_SHA256_SOURCE_20261009`, metadata gold
и все dictionary/manifest/SDK/readonly assertions сохранены. Native tests этого
rebind **NOT_RUN**: совпавший digest не доказывает native export или lifecycle.
Independent delta review и parent disposition обязательны до adoption.

Published/installed common остаётся d390; candidate не установлен и не загружен.
Native/SDK/SQL/Linux/hosted matrix/FULL/release и owner-run activation остаются
отдельными незакрытыми gates. Диагностический SOURCE setup не добавляется в
обычный release generator и не заменяет его обязательный real-provider export.


## CI-O03: CURRENT G4 oracle на frozen25431 (metadata-only)

На baseline `25431e0a801dd5f9c1114a90c94249f5eaaad978` устарел только CURRENT
whole-file oracle G4, а не продукт. В test_08 и его ReviewBoundary control literal
`f7c896a12a43dff50de99d45b02c496ccf1eabe00c9afc834a8b6d2f59182985`
заменён на заранее фиксированный raw SHA текущего `__init__.py`
`8007b015f204a0b673e7cf41410fe609f60b8151bd39d9042a53336de7fdaf09`
(1524144B, Git blob `5d02a2c816ffecb5ab8f7227bdbd6dc75901827d`). Expected
остаётся литералом, не вычисляется из actual/HEAD во время теста.

Ровно зависимый digest восьми identity-errors методов в `ORIGINAL_TESTS`
мигрирует с `8017b80c0d73939d4ad390d5ff77b65863b9feae04b39b83a46c416dad172d92`
на `ea6341d85a25afc3f00fd79039046417bdd2b64ff15d75483474852bcb18f84e`.
Рецепт прежний: `ast.walk`, test `FunctionDef`, `ast.dump(include_attributes=False)`,
sorted methods, `json.dumps(ensure_ascii=True).encode()`, SHA256. Это явная
metadata migration одной pin Constant, **не** неизменный original-a4 AST;
CI-O01/O02 выше описывают исторические pins/digests, не текущую квалификацию.
Остальные пять ORIGINAL_TESTS digest, включая repair01 `e5354523...`, неизменны.

Raw/AST inverse возвращает три test-файла к baseline после обратной замены двух
current literals и одного digest; поясняющий comment учитывается отдельно.
Оба historical gold, исходные hooks/setup, transport/SQL assertions, NetworkDenied
tail, roster8+2+10 и ReviewBoundary7 сохранены. Все506 non-target mode/blob rows,
включая весь продукт, runners/workflows/guards, byte-exact прежние. Historical
`SCHEMA_PINS['baseline']` public-options не является CURRENT oracle и не меняется.

Здесь только инертная raw/AST/digest/Git qualification: tests/collection/product
import/exec/SOURCE/SQL/SDK/bootstrap/native/FULL/CrossPlatform/CI — **NOT_RUN**.
Исторические PASS не переносятся. Исправление stale oracle не доказывает, что это
единственная причина CI failure: конкретный child case/outcome остаётся UNKNOWN.
CI/native не объявляются GREEN; независимое review и приёмка остаются родителю.

## CI-AST/DIAG: actual-parser compatibility и SOURCE failure visibility

На public0c (`0c2f2b6402cbfe1dec243897e4bb2394a3fe426a`) шесть test-method
fingerprints совпадали с literal `ORIGINAL_TESTS` на CPython3.13.2/3.14.7, но ни
один не совпадал на actual3.11.9/3.12.10. Это инертное parser/hash наблюдение,
не исполнение тестов или SDK: у3.11 нет `FunctionDef.type_params`, а у3.12 иначе
отображаются пустые AST fields. `feature_version` нового parser это не исправляет.

Теперь `original_tests_for_runtime` выбирает явные literal таблицы3.11/3.12 и
прежнюю, неизменную `ORIGINAL_TESTS` для3.13/3.14. Иная implementation, неизвестная
версия или malformed tuple дают отказ, не skip/fallback. Producer **не изменён**:
все `ast.walk` `FunctionDef` с `name.startswith('test')`,
`ast.dump(include_attributes=False)`, sorted strings,
`json.dumps(ensure_ascii=True).encode()`, SHA256. Никакой AST normalization,
self-derived expected, обновления gold из HEAD или удаления meaningful fields.

Независимые actual-parser profiles:
`diagnosis/ci-0c2-39962629120-20261023/ast311.stdout.json`
(2427B, SHA256 `127419a52e00f970ba368aaac01827935dfd15f3df33efd150946b58aa231cf7`),
`ast312.stdout.json` (2411B,
`ff3e5e8d256c4dcba4622835f551daf9b2951c9b6c7d7cc88ab3efd91c0a83fb`).
Их шесть exact raw source bindings (в прежнем порядке `ORIGINAL_TESTS`):

| public tests input | B | raw SHA256 |
|---|---:|---|
| `test_memory_diff_polarity.py` | 5847 | `9720bfe64b04183c2b378b0f901245c951df567dd9672a2d6d516fcecdfe2420` |
| `test_observation_finite_work.py` | 18456 | `8bb326e6e42084d37e10a0ed784807e96b67c56612e5bc0fac26b693ec0888fa` |
| `test_observation_repair01.py` | 12947 | `b773c354227036fc8322fb8d61649a42bc6359def70df10e056059e52affd96a` |
| `test_p2_g4_identity_errors.py` | 19883 | `ec293d2136a19afef4b3c60d8bf0f2888ab32972c82a9072e11511f127056d24` |
| `test_p2_g4_repair01.py` | 13944 | `be3299b328933adab7c67b6a6de1d8df6b9a43dff78da43444e2155dfeb387df` |
| `test_prefetch_current_diagnostics.py` | 13729 | `877bce96128a1efdbaac201d36dde7dc890fe42c07dd5eec206bdd94bb96dfa0` |

Все прежние assertions, исторические gold, hooks/setup, transport/SQL/NetworkDenied
и product raw8007 остаются прежними. Shipped SOURCE roster по-прежнему8+2+10,
ReviewBoundary7 не меняется. Additive `CompatibilityDiagnosticControls`
(`__test__ = False`) — отдельный явный tooling UNIT/SOURCE roster, не выполнение
старых G4 или полный Prerequisite10 и не дополнительные native ignores.

### Ошибка qualifier остаётся первичной

`run_suites` по-прежнему сохраняет исходные `suite-N/stdout.log`, `stderr.log` и
`source-results.json`; новые children для диагностики не запускаются.
`qualified_native_args` вызывает **тот же неизменный** strict `native_pytest_args`.
При отказе packaging caller и standalone SOURCE main выводят одну bounded
`SOURCE_FAILURE_DIAGNOSTIC` JSON line в stderr, после чего bare `raise` повторно
поднимает exact original exception. Ни formatter/read/write failure, ни вторичная
`BaseException`/cancellation не заменяют primary и не разрешают native continuation.
Если даже fallback stderr недоступен, ошибка qualifier всё равно сохраняется.

Console projection содержит только fixed suite names, source-bound main case IDs,
finite outcomes/builtin error-type labels либо явный `UNKNOWN`, относительные
имена существующих captures и public-input byte layout. Raw messages,
foreign exception class metadata, subtest payload/`id()`, ENV/auth/user files,
stdout/stderr содержимое и произвольный `str`/`repr` туда не попадают. Предел строки
16000 ASCII bytes. Missing/malformed case report не превращается в passed по
одним aggregate counts; сырые captures не переписываются.

Reader допускает только `__init__.py`, `tests/fixtures/g4_original_boundary_gold.txt`
и `tests/fixtures/g4_metadata_scope.txt`: no-links ancestors, regular file,
не более2000000B на input и bounded read(cap+1). Console отдаёт только raw SHA256,
B и отдельные CRLF/LF-only/CR-only counts либо `UNKNOWN`, не bytes. Это сигнал для
следующего actualCI, **не доказательство** Windows CRLF incident. Ограничение
SOURCE binder1MB не повышается: исполнение полного oversized reader на init
в локальном tooling packet **NOT_RUN**; его wiring проверяется статически.

Изменение формата явное и additive: core `memory-stack.source-suites/v1`
(`total/passed/failed/errors/skipped/cases{id,outcome}/subtests`) сохранён;
`case_report` добавляет только namespaced
`diagnostics{schema:memory-stack.source-case-errors/v1,case_error_types}`.
`run_suites` дополнительно сохраняет `cases` и `diagnostics` в per-suite row.
Diagnostic console имеет собственный `memory-stack.source-failure-diagnostic/v1`.
Проверены consumers по source: оба G4 распаковывают прежний `case_report`,
Prerequisite subtest control читает прежние поля, packaging и standalone main
пользуются новым wrapper, `memory_wiki_ci.py` и `ci_child.py` читают прежние
qualification fields через неизменный `native_pytest_args`. Они не используют
новые поля как authority; их отдельные callers не изменены. Summary не является
native receipt и не меняет SOURCE/native split или workflow/checkout/EOL policy.

Actual новый tooling outcome, admission/capture/roster, candidate и ограничения —
только `repairs/ci-ast-compat-diagnostics-20261023/RESULT.json`, не утверждение PASS
в этом документе. Подготовлены pure selector/formatter/primary-preservation
controls с реальным strict metadata-validator на authored typed metadata.
Это не SDK stand-in и не actual3.11 native execution. FullG4/Prerequisite10/SQL,
provider/init execution/SDK/native, hosted CI/Windows matrix, FULL/build/install/
loaded/release здесь **NOT_RUN**. Исторический run39962629120 остаётся последним
разрешённым snapshot:6 regression failures,2 Ubuntu3.13/3.14 in_progress;
конкретные failed child cases и единственная причина historicalCI — **UNKNOWN**.
Independent review frozen четырёхфайловой дельты и приёмка остаются родителю.
