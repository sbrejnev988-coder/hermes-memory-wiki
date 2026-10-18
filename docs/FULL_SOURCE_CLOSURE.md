# FULL: текущая file-role / entry closure

Этот документ и `COLD_LANES.json` закрывают **SOURCE-учёт файлов и объявленных
точек входа**, а не запуск FULL. Native/pytest/SDK/hosted/model/network в этом
блоке не допускаются. Parent acceptance и окончательная интеграция отдельны.

## Что исправлено

Старый partition содержал 256 строк при 318 tracked `tests/**/*.py`: отсутствовали
62 файла; часть helpers/conftest/historical inputs ошибочно стояла в списке
исполняемых legacy targets. Provider SHA также относился к прежним bytes.
После настоящих последовательных merge принятых A и B перечислены все
318 исходных baseline-файлов, `tests/test_cold_lane_partition.py` и доставленный
`tests/ci_owned/collection_dispatch_cases.py`: 320 Python source files в прежнем checkpoint.
ADJ-REINDEX-FOREIGN-01 добавляет shipped native regression и отдельный SOURCE entry:
**322 уникальных Python source files** в текущем census. Это не 322 collected,
executed или независимо семантически проверенных tests.

| File role | Файлов | Что означает запись |
|---|---:|---|
| `pytest` | 268 | Есть collectible function/class declarations; реальная collection и outcomes не выполнялись |
| `unittest-explicit` | 21 | Отдельный stdlib entry / suite binding; `make_suite` или `CARRIER` не инициализируются одним pytest discovery |
| `callable` | 2 | Реальные аргументные native packets; не pytest test bodies |
| `source-only` | 10 | Отдельный SOURCE маршрут, исключённый из native preload; конкретные требования различаются |
| `support` | 19 | Helpers, fixture producers, conftest, reporter, cold entry; не независимые test cases |
| `historical` | 2 | `baseline-source_connectors.py` и `primitive_guard_a9d5016e.py`: неизменные oracle inputs, не current runtime/tests |

File-lane membership: legacy 243, strict 25, SOURCE-explicit 31,
native-explicit packets 2, support 19, historical 2. Отдельный recovery entry
повторно ссылается на существующий `recovery_cases.py`; это намеренный другой
cold process, не ещё один уникальный файл. Не складывать этот повтор с file
inventory или cases. У source_explicit_targets теперь полный набор 31 entries,
включая существующий doc/code SOURCE carrier.

Для каждого Python-файла JSON хранит raw SHA-256, role, lane, actual entry kind,
invocation, сигнатуры объявленных explicit functions, причины, prerequisites и
статически названные test peers. `peers` — консервативный индекс literal filename /
`from ... import` зависимостей, **не доказанная полная dynamic import closure**.
Подробные module bodies этим не были независимо рассмотрены или исполнены.

## Точки входа и несовместимые процессы

- Existing native entry — `tests/cold_lane_entry.py`: те же strict / genuine
  trust-absent legacy / legacy-recovery процессы. В native target lists остались
  только pytest roles, не support/historical/explicit suites. SDK, exact origin,
  registry/MRO, package versions, security mode, public trust delivery и
  admitted bootstrap/recorder guards сохранены. Нет универсального FULL режима.
- Existing `tests/ci_owned/doc_code_carrier_cases.py` — SOURCE module entry через
  постоянный проектный `devtools/harness.py`, с его DEVTOOLS_INPUTS, read_bound,
  case_started и own scratch. Его три SOURCE fixture inputs сохранены. Это не
  native provider bootstrap или автоматический unittest module.
- G4 identity/error и G4 repair требуют подлинного отсутствия
  `agent.memory_provider`; имеют разные `G4_FIXTURE` / `G4_REPAIR_FIXTURE` и app/user
  identity. Их нельзя запускать после native SDK preload. Исторический
  `g4_original_boundary_gold.txt`, BEFORE oracle и security expectations не менялись.
- `test_connector_stage_admission.py` требует genuine `agent` и trust absence и
  настоящую standalone fallback class; `test_connector_stage_home_compat.py` и
  `test_connector_legacy_schema_owner.py` **реально экспортируют `stage=peer.stage`**
  и используют эту fixture в cases. Все три имеют отдельный SOURCE-only pytest
  маршрут. Для двух consumers задан явный `fixture_binding`, проверяемый по actual
  top-level peer loader/alias/fixture argument; producer сохраняет genuine absence
  и standalone guards. `requires_sdk_absent=false` не разрешает native metadata.
  Это узкий actual-binding контракт, не новый import resolver и не распространение
  absence по любому `peers` edge: AST/input reading само по себе не fixture import.
  **In-tree native autouse conftest несовместим с этим маршрутом.** Для будущего
  настоящего pytest требуется byte-exact полный peer layout в own non-package
  tree без native ancestor conftest; здесь такого процесса/копии/допуска нет.
  Это объявленный prerequisite, не bypass conftest, fake SDK или removal cases.
- Stdlib SOURCE unittest не всегда требует отсутствия SDK: у файлов собственные
  условия. Удалено неверное глобальное утверждение «все SOURCE требуют SDK absent».
  Чистые observer/reporter/AST packets просто исключены из native preload; это не
  переопределение их assertions. Factory suites имеют exact `make_suite` signatures
  и отдельный setup/scratch. Для non-main modules указан stdlib loader API, не
  инертное `python file.py` как якобы выполненный набор.
- `tests/ci_owned/test_current_sdk_bootstrap.py` требует явного `CARRIER` для его
  UNIT-only API; вызов worker/component не разрешён этим binding.
- `tests/ci_owned/entry_cases.py` и `exit_cases.py` до первого case импортируют
  `binding_cases`. Bare `python -I -B -S <file>` не добавляет script directory и
  здесь не поддержан. Их exact structured bootstrap/argv и invocation используют
  **stdlib `-c` + `runpy`**, добавляя только собственный `tests/ci_owned` до этого
  import. Из complete source root (пример для entry; exit заменяет только operand):

  ```text
  python -I -B -S -c "import runpy,sys; from pathlib import Path; entry=Path(sys.argv.pop(1)).absolute(); sys.path.insert(0,str(entry.parent)); runpy.run_path(str(entry),run_name='__main__')" tests/ci_owned/entry_cases.py
  ```

  Operand потребляется через `pop(1)` до `runpy`: target получает обычный
  `sys.argv=[absolute_entry, *remaining_args]`, а не имя script как test selector.
  Остальные literal unittest selectors/options сохраняются без преобразования.
  SOURCE-контроли проверяют exact argv и настоящий `unittest.main()` на инертных
  собственных модулях: оба entry, default suite, `-q` и явный test selector.
  Historical CI suites/peer от этого не считаются исполненными.

  Prerequisites: проверенный полный source layout, byte-exact peer
  `tests/ci_owned/binding_cases.py`, существующий пустой own scratch через
  `MW_CI_UNIT_FIXTURES`, credential-free home/temp. Сам peer штатно добавляет только
  `scripts/ci_owned` для lazy `load(name)`; `ci_process.py`, `ci_bootstrap.py` и
  `memory_wiki_ci.py` явно SHA-bound. Ни SDK path, ни site/PYTHONPATH, ни новый
  runner не добавлены; `-I/-B/-S` сохранены, historical bodies не изменены.
- `test_runtime_lifecycle_handoff.py`: `run_lifecycle_packet(provider, root)`.
  `test_fts_transaction_handoff.py`: `run_fts_packet(provider, manager, root,
  checkpoint)`, `run_negative_packet(...)`, `run_retained_fts_unknown(home,
  session_id, checkpoint)`. Нужны настоящий SDK/initialized provider/manager,
  own store, original authority и retained UNKNOWN. Сам факт файла в collection
  этих функций не вызывает. Прежняя историческая lifecycle evidence сохранена,
  не объявлена новым результатом.
- Некоторые native files содержат несколько security modes, optional trust paths,
  protected-setting fixtures или subprocess/worker controls. Их requirements
  явно сохраняют отдельную per-case mode/effect qualification; file-role closure
  не разрешает скрыть такие случаи skip/deselect/xfail и не объявляет их применимыми
  в текущем no-config/native-child envelope. Приведённые lane lists — source plan,
  не семантическая гарантия всей будущей collection/bootstrap комбинации.

## Три разных native target identity

| Контракт | Existing entry | Declared official revision | Actual origin / resolved closure |
|---|---|---|---|
| ordinary CLI | `packaging/run_native_regressions.py` | `5307e93252ac655cd13fadbd561c0995142138c6` | `null` / `null`, BLOCKED |
| hosted FULL | `scripts/ci_owned/memory_wiki_ci.py` | `d526f14714ce8a95cafd7f3a95d1eab5b6e0b910` | `null` / `null`, hosted-only/BLOCKED |
| managed SDK | `scripts/ci_owned/current_sdk_bootstrap.py` | `null`: требуется current descriptor | `null` / `null`, BLOCKED |

Declared CORE_SHA проверяется по literal AST actual entry, а raw hash связывает
bytes. Это не выбор установленного Core, не signature/trust attestation и не
complete dependency closure. Управляемое readonly окружение не получает hosted
`.pth`/runtime patch. Для каждого cold lane selected_revision/origin/
resolved_closure остаются `null`; strict public trust origin/SHA тоже `null`.
Legacy требует genuine trust absence, не скрытие установленного модуля.

## Минимальная проверка existing cold entry

`validate_partition(plan, source_inputs=None)` — чистая stdlib-функция, без I/O,
импорта tests/product/SDK и без native flags. Она проверяет typed schema/roles,
unique file paths, literal safe paths/hashes, file count/digest, prerequisites,
peers, exact source/native target lists, допустимую recovery overlap и explicit
packet membership. SOURCE-only/SDK-absence targets не допускаются в native lanes;
noncases не становятся исполняемыми targets. Native permission из JSON не выдаётся.
Actual stage consumers проверяются независимо от заявленного boolean: подмена lane,
пропуск/перенаправление fixture binding и отсутствие prerequisites отвергаются.
Два CI entry требуют exact supported bootstrap argv/invocation, own peer path,
fixture ENV и SHA-bound source-input closure; descriptive promise не заменяет их.

Если передан independently enumerated `{repo_path: raw_bytes}`, проверяются exact
membership всего current test Python census плюс named source pins, все raw SHA,
фактические explicit function signatures, наличие collectible declarations и
отсутствие hidden case declarations у support/historical roles. CORE_SHA targets
сверяются с actual source literals. Metadata-only success явно возвращает
`source_inputs_verified=false` и не доказывает filesystem.

`cold_plan` вызывает typed validator, затем сохраняет прежние fail-closed guards.
После их успешного admission existing `main` до любых новых native imports делает
самостоятельный physical no-follow census `tests/**/*.py`, проверяет named pins и
передаёт raw bytes тому же pure validator. Неисполняемый/пустой SOURCE packet не
выдаётся за такой native путь; он проверяет отдельно pure validator и реальные
ранние BLOCKED branches `cold_plan`, не ставя фальшивый recorder или SDK.

Дайджест `input_inventory_sha256`: SHA-256 UTF-8 JSON сортированного списка
`[path, sha256]` всех partition rows, `ensure_ascii=True`, separators `(',', ':')`,
без newline. Это test-file digest, не полный Git tree digest. `source_pins`
связывает provider / existing entry / workflows / historical G4 gold отдельно;
самоссылающийся manifest туда не входит. Полный candidate commit/tree фиксируется
в RESULT, а не вычисляется как self-referential pin этого JSON.

## Focused regression и граница доказательства

`tests/test_cold_lane_partition.py` исполняется настоящим stdlib unittest через
existing `devtools/harness.py.run_source` под `-I -B -S`, clean own home/temp и
неизменённым SOURCE audit envelope. Контроли: current full file closure, missing /
extra / duplicate / stale inputs, typed values, path/hash refusals, native/SOURCE
intersections, target loss/duplication, support hidden cases, exact callable
signature, factory/CARRIER setup declarations, peer/prerequisite loss, provider /
entry pin drift, pending hash/rebind, distinct native revisions и actual ранние
cold-plan refusals. Native/pytest assertions и исторические tests не менялись.
Correction A-SOURCE-01/02 добавляет negative controls ложной native metadata даже
с `requires_sdk_absent=false`, alias/guard drift после rehash, сохранённый
non-inheriting input edge, bare/изменённый bootstrap и потерю peer/prerequisites.
В том же packet actual declared `runpy` bootstrap исполняется на инертных own
targets и через stdlib `PathFinder` разрешает byte-exact `binding_cases.py` до
первого import. Historical CI suites и сам peer не исполняются: SOURCE envelope
по-прежнему запрещает non-stdlib imports; это bootstrap/source-binding control,
не новый запуск тех suite или native/pytest proof. Старый SOURCE27 сохранён как
исторический; весь affected validator cohort проверяется заново, без переноса PASS.

Для этого bounded packet полный независимый byte census упакован в два
lossless UTF-8 JSON+zlib inputs (tests и entry pins): у permanent harness не более
40 inputs и 1,000,000 B на обычный bound input, а полные raw tests/provider больше.
Это только test fixture transport, не runner/framework/SDK decoder. Внутри
пакета decompressed bytes только хешируются и AST-парсятся; исполняются полный
actual cold entry module со stdlib imports и новый focused test, не product/Core.
Обычный direct test работает из полного checkout и строит тот же no-follow census
без внешнего carrier. Actual exits/capture/audit/ownership и main unittest case
counts находятся в lane RESULT и primary logs; FILE counts не testcase coverage.

## Доставленный peer и окончательная SOURCE-композиция

Принятые inputs A `39abfd5bb468d16deb88902fd062f45caae74789` и B
`e14456fde89b3052857810a8eb2fa41126b71007` действительно merged в собственный
combined worktree от `a208e12a03ab1d290372ce059a7a7ab8d711bfd3`, без conflicts.
Доставленный `tests/ci_owned/collection_dispatch_cases.py` получил фактический
SHA и SOURCE-explicit unittest role, direct stdlib invocation и actual
`run_fixture(kind, *, source, root)` callable signature. Его shipped helper
`tests/helpers/collection_evidence.py` указан как layout peer. Перепривязаны
current test census и все source pins, включая изменённый workflow; отдельно
добавлены реальные `ci_child.py` и `ci_output_admission.py` — всего 11 named pins.
B tooling не добавлен в native pytest targets и не исполняется этим SOURCE packet.

`pending_peer_inputs=[]` и `needs_final_rebind=false` означают только эту
фактическую SOURCE-композицию, не native admission или закрытый FULL. Core,
trust и resolved dependency origins всё ещё `null/BLOCKED`. Новый positive
проверяет current B role/hash/callable/helper/pins и отсутствие native grant.
Прежние три pending-negative controls теперь явно создают собственную metadata
fixture будущего недоставленного peer; исходные refusal assertions сохранены.
Это in-memory clone, не ложный pending статус уже доставленного B. Появление
будущего файла в raw input по-прежнему отвергается как unpartitioned membership,
даже если имя есть в pending metadata. Все affected SOURCE controls проверяются
свежим отдельным packet; прежние A40 и B14 outcomes не выдаются за его результаты.

`docs/TEST_CONTRACT.md` принадлежит другому контракту и здесь не редактируется;
его прежние checkpoint counts остаются историческими. State/acceptance/merge,
stock pytest dispatch, native FULL/security/recovery/compatibility и release
остаются отдельными parent gates. No guards weakened, no native grant, no новые
Core/SDK/PM/forks/runtime/settings/data/model/network/install/restart изменения.

## Узкая foreign-copy дельта

`tests/test_foreign_reindex_admission.py` использует прежний genuine-SPI peer
`tests/ci_owned/claim_embedding_fixture.py` и остаётся native-strict / NOT_RUN
в SOURCE scope. `tests/ci_owned/foreign_reindex_cases.py` — отдельный SOURCE
controller entry: static old/current forwarding, реальные generic SQLite
metadata/epoch/intent prediction units, authenticated-format ledger consumer и
actual missing-owner refusal; не здоровый native fence или actual PUT proof.
Подробный контракт и limit применимой phrase erasure —
`docs/FOREIGN_REINDEX_ADMISSION.md`. Перепривязаны только два новых membership,
current provider pin и зависящие count/digest/target lists. Старые SOURCE41,
native/FULL/runtime outcomes и отсутствующие Core/trust origins не переобъявлены.
