# Безопасный адресный retry failed outbox

## Контракт

`memory_wiki_repair` получил необязательное поле `outbox_job_ids`. Это список
от 1 до 100 различных **буквальных** ID штатной outbox: 16 строчных hex-символов.
Пробелы, другой регистр, дубликаты, усечение и преобразование типов не исправляются
автоматически. Поле относится только к `outbox`, включая это действие внутри `all`.
Остальные repair targets не получают новых полномочий.

`dry_run` по-прежнему `true` по умолчанию. Для outbox нужны точные ID даже в dry-run:
без них возвращается `outbox_job_ids_required`, а не глобальный перечень failed jobs.
`target=all` без ID может выполнять прежние **другие** repair actions, но его outbox
поддействие отказывает и не оживляет corpus. Общий результат такого `all` не считается
полностью успешным. Для адресной операции в общем store следует выбирать `outbox`:
этот путь проходит до глобального census, lazy migration и recovery journal/export.

Пример формы вызова (ID ниже вымышленный; эти вызовы при авторстве не выполнялись):

```json
{"target":"outbox","outbox_job_ids":["0123456789abcdef"]}
```

Для применения нужен тот же явный список и `"dry_run":false`. Список ID — адресация,
**не** доказательство caller ownership и не согласие на чужую работу.

## Допуск и изменение строки

Адресный batch обрабатывается целиком либо отказывает. Используются настоящие:

- уже инициализированные provider/native-home/profile scopes и зарегистрированный
  writer connection; чужая или активная транзакция не присваивается;
- `_claim_visibility_sql`, `_claim_metadata_eligibility_sql('scoped_reindex')` и
  `_require_model_mutable_claim`: только активные подходящие `chat/private` claims
  данного caller; shared read-only memory не становится mutable из-за нового поля;
- оригинальный `DisclosureFence`: существующий authenticated erasure ledger,
  owner/config/revision epoch, canonical claim, связанные evidence, document/code
  sources и их исходные образы. Ни erasure replay, ни переинициализация authority
  не используются для получения допуска;
- существующий `_strict_target` из `current_scope_reindex`: положительное текущее
  physical/alias binding, namespace/manifest/endpoint и размерность коллекции;
- существующая `_claim_transaction` с `BEGIN IMMEDIATE`, native COMMIT, retirement,
  rollback/primary/quarantine правилами. Нет второго backend или очереди.

SQL ограничен переданными ID и caller ACL **до** загрузки payload/last_error.
Отсутствующий, чужой, неподходящий и не-claim объект дают один `outbox_jobs_unavailable`.
Ни один ответ не содержит job/object IDs, payload, claim text, target URL/collection,
raw exception или `last_error`; глобальные `failed_seen`/`skipped_count` удалены.
Counts относятся только к успешно допущенному адресному batch.

Payload должен быть JSON object с явной непустой строкой `collection`. Malformed JSON,
scalar/list/null, отсутствующая collection, дубли ключей и не-finite JSON отказывают.
Нет fallback `{}` и нет implicit online target. Нужны совпадающие canonical revision,
updated_at, event_at и owner labels, которые уже пишет штатный `_add_claim` producer.
Если присутствуют endpoint/manifest/target hash или retained text, они тоже должны
совпасть. Legacy job без нужного evidence отказывает, а не получает его выдуманным.
Alias принимается только при подтверждённом текущем binding. Payload не переписывается.

Под writer TX повторно читается **полный** исходный job image: operation, object,
payload/hash, status, attempts, timestamps, worker/lease, retry time и retained error.
Повторно проверяются исходные source/actor/erasure/epoch/target. UPDATE содержит
условия полного image, `status='failed'`, `worker_id=''`, `lease_until=0`; нужен
`rowcount == 1`. Изменяются только status, attempts и retry/update timestamps.
Ни lease/worker чужой работы, ни payload, ни raw stored error не очищаются.
После UPDATE проверяются точные собственные эффекты и неизменность исходного snapshot;
нет принятия нового epoch после ожидания. Допускается только собственное подтверждённое
приращение `total_changes`, а не чужие изменения или дополнительные trigger effects.

Notification находится после успешного возврата настоящего owner из COMMIT/retirement
и использует исходный DB path. Новый `_notify_registered_outbox_worker(path)` только
читает registry и проверяет точные штатные `Thread`/`Event`, liveness и identity
под **одним** `_OUTBOX_WORKERS_LOCK`, затем вызывает `Event.set`. Нет повторного
path resolver, SQL, `_ensure_outbox`, starter, нового thread или вложенного wake-lock.
Отсутствующий/мёртвый worker даёт `notification="deferred_no_live_worker"`,
`worker_woken=false`, `ok=true`: собственный retry batch уже committed, durable
intent сохранён, а не выполнен. Bootstrap/restart не входит в этот вызов.
Dry-run, отказ, no-effect, rollback и UNKNOWN worker не будят. Штатные
`_start_outbox_worker`, `_ensure_outbox`, `_wake_outbox_worker`, worker loop и
`_outbox_process_scoped` не изменены. Уже живой worker продолжает свой обычный
namespace lifecycle; notification не доказывает delivery или дальнейший write-set.

## Correction01: последний callback и настоящий COMMIT

Исходные `d6fb…`/`a3b8…`, отрицательное SOURCE-review и прежний policy PASS сохраняются.
Два исправляемых findings — **условные подтверждённые по source механизмы**, не
воспроизведённые runtime incidents: `OUTBOX-NATIVE-ADMISSION-001` и
`OUTBOX-STARTER-SCOPE-002`.

Для первого добавлен только plugin-private `_OutboxRetryStage` из
`code_knowledge_graph.py` и необязательный `_claim_transaction(..., _outbox_retry=...)`.
Это не Hermes Core/SDK и не graph/document/event/terminal capability. Stage держит
точные provider/connection/thread, original-admission closure и исходные actor/reference/
policy значения. Он допускается только для отдельного idle shared owner с `BEGIN IMMEDIATE`.
Join/adopt, другая connection/thread, повторное использование и сочетание с document,
graph, event, terminal либо rollback receipt явно запрещены. Чужой ordinary writer
также не может присоединиться к незавершённому narrow outbox stage.

После yield, callback-capable journal/hook/owner/lease tail владелец вызывает именно
**первоначальный** `final_original_admission`. Повторно проверяются target, ACL/actor,
source images, erasure, policy, epoch и полный адресный job afterimage. Возвращаемый
SQL counter равен `original_epoch.total_changes + подтверждённые собственные CAS`,
а не новому snapshot. Новые исходные claims/ledger/epoch не принимаются.
Затем настоящая `_GraphCommitConnection.commit` вооружает точный native flight до
`super().commit`. Pure fence проверяет owner/stage/image/actor/policy/counter на входе
и после native authorizer, не вызывая из SQLite SQL, target reader или authority callback.

Critical user authorizer/trace/progress lifetimes не поддерживаются этим stage.
Они **отказывают**, а не отключаются: pre-existing либо установленный в stage
callback оставляет sticky `callbacks_seen`; его последующее удаление не очищает
признак. Trace/progress отдельно запрещены на native entry. Поздний authorizer
проверяется также после callback перед native effect. Поэтому корректный отказ может
случиться **до** actual `SQLITE_TRANSACTION/COMMIT` callback; такой отказ нельзя
называть исполнением последнего callback. Обычный callback-free lawful upsert имеет
положительный путь; ordinary nonoutbox callback semantics не переопределяются.
Это поддерживаемый in-process контракт, не защита от прямой замены внутреннего
authorizer через raw setter descriptor, private-field monkeypatch, сигналов,
произвольного host profiling или OS-level атак. Raw COMMIT shortcuts, в отличие
от замены самого authorizer, проходят через установленный native fence.

SQL/cursor/script/context shortcuts не завершают тело stage: premature COMMIT/END,
SAVEPOINT и не-владельческий ROLLBACK запрещены native authorizer. Reentrant completion
из authorizer также запрещён. Setter/close/transaction-mode guards защищают новый
lifetime; callbacks не могут снять fence во время native flight. Только сам owner
переводит stage в rollback. Исходный `_rollback_claim_transaction` не изменён.
Retirement разрешён после подтверждённого COMMIT либо rollback и только для своего
точного stage. UNKNOWN сохраняет owner/stage/primary и quarantine без reconnect.
Fatal `BaseException` не превращается в публичный ordinary refusal.

После известного native COMMIT ошибка journal/notification не изображает rollback:
`applied=true` и собственные counts сохраняются, notification остаётся deferred.
При неизвестном native outcome сохраняется `applied=null`; success notification сам
по себе не устанавливает commit. Прежние native graph/document/event fences и private
writer/reader classes не переписаны. Их новые совместные runtime-проверки не выполнены.

## Correction02: exception-safe progress registration

Единственный исправляемый остаток `OUTBOX-NATIVE-ADMISSION-001` —
`CORRECTION01_PROGRESS_NATIVE_STATE_DIVERGENCE`. Родитель подтвердил его по source:
после штатного `set_progress_handler(H, 1)` неуспешный
`set_progress_handler(None, 10**100)` мог оставить native H, но заранее записать
Python `None`. Созданный **после** этого stage и native-start проверяли одно ложное
зеркало. Это не новый воспроизведённый runtime incident и не утверждение об actual
late H/COMMIT outcome. Прежнее `correction01-review/REVIEW.json` с `passed=false`
сохранено; автор не принимает исправление самостоятельно.

Изменён только shared plugin setter и его необходимые stdlib import/tests/docs:

- `operator.index(n)` выполняется один раз **до** native effect. Он разрешает
  предусмотренные int/bool/`__index__` значения, не заменяется `int(n)`, truthiness
  или пользовательским `n > 0`. После него `n` — точный int; effective callback
  рассчитывается до native вызова. C-int range, overflow и собственные connection
  проверки остаются настоящему `super().set_progress_handler(callback, n)`.
  Ошибка index-конверсии, включая fatal, не меняет зеркала сама; побочные setter
  эффекты самого `__index__` не откатываются выдуманным старым snapshot.
- Исходный flight guard сохранён и повторён после callback-capable conversion.
  До native вызова зеркало получает отдельный non-None pending/unknown marker,
  **никогда** ещё не доказанную `None`. Только нормальный native return разрешает
  опубликовать effective callback/absence. Native exception оставляет unknown,
  выходит тем же bare re-raise; native outcome не угадывается. Это намеренно
  консервативно и для failed clear без прежнего H.
- При успешном `callback=None` clear либо effective `n <= 0` зеркало становится
  `None`; успешный positive interval сохраняет настоящий callback. Нет лишнего
  native clear, отключения H ради critical operation или произвольного сравнения
  после эффекта. Прежняя ссылка удерживается до публикации; если во время native
  replacement reentrant setter изменил зеркало, результат помечается unknown,
  а не изображается доказанным порядком двух регистраций.
- Все настоящие потребители уже трактуют non-None как неподдержанный critical
  lifetime: initial owner `any(value is not None ...)`, native-start и остальные
  существующие graph/document/event/terminal guards. Поэтому `__init__.py` и
  другие owners не изменены. Unknown нельзя превратить в callback-free допуск.
  Failed native setter внутри stage делает sticky history истинной даже после
  последующего успешного clear. Успешный clear **до нового** stage восстанавливает
  обычный healthy path. Ordinary noncritical transactions продолжают использовать
  фактически установленный native H; marker не вызывает и не отключает его.

Новые prepared controls включены в прежние suites, не в новый runner: failed
clear **до** stage с наблюдаемым сохранённым H и known rollback; успешный clear
с healthy commit; progress install/remove в stage; ordinary native H после
failed clear; bool/index/int-subclass без пользовательского `__gt__`; zero/negative
и index-zero/negative; невалидные типы/index и positive/negative overflow; exact
fatal index identity + known rollback + следующий healthy stage; failed setter
в stage с последующим clear и сохранённой sticky history. Два новых AST controls
проверяют success-bound публикацию/unknown и различают удалённую conversion либо
error reconciliation. Это подготовленный oracle, не выполненные TestCases.

Прежние known rollback/postcommit-fatal controls и все UNKNOWN guards сохранены.
Существующий genuine
`tests/test_document_native_commit_fence.py::test_native_unknown_keeps_original_primary_exact_owner_and_admissions`
остаётся отдельным **document** native control, не proof нового outbox UNKNOWN.
Outbox UNKNOWN/public composition остаётся в `PUBLIC_NATIVE_REQUIREMENTS`,
NOT_RUN/BLOCKED без собственного допуска и совместимого safety teardown:
shipped derived fixture удерживает quarantine, но её `safety_close_unknown`
вызывает guarded `c.close()`, который законно отказывает retained outbox stage.
Здесь не добавлены raw-setter bypass, permitting stand-in, recovery или новый
fixture framework ради зелёного результата.

Старые initial SOURCE 26/85 и correction01 SOURCE 33/183 относятся только к своим
точным прежним input tuples; оба допуска 1/1 spent. Они не объявляются PASS
correction02. Автор выполняет только inert AST/JSON/hash/Git metadata; новый
SOURCE, tests/helpers/factories, collection, native/SQL/SPI/SDK и public E2E —
**NOT_RUN**. Native совместимость нового setter, runtime исход исходного сбоя,
независимый changed-contract review и acceptance остаются отдельно родителю.

## Deletes и статусы

Retry delete здесь явно запрещён: `outbox_delete_capability_required`. Текущий delete
worker может расширить hint на несколько ledger targets; в этом caller seam нет
доказанной exact-target ownership/capability для безопасного адресного delete.
Исторический target и весь durable delete intent остаются без изменений, **никогда**
не перепривязываются к online. Удалённый/неактивный/чужой claim не раскрывается даже
ради диагностики такого job. Это ограничение только unsafe delete ветви, не blanket
refusal законного upsert: current owned producer-shaped upsert имеет положительный путь.

Основные исходы:

| Исход | `ok` | `applied` | Смысл |
|---|---|---|---|
| `addressed_preflight` | true | false | Собственный batch допущен к моменту проверки; не изменение |
| `addressed_committed` + `notified` | true | true | Retry committed; Event.set вернулся; не delivery |
| `addressed_committed` + `deferred_no_live_worker` | true | true | Retry committed; worker отсутствует/мёртв; нет bootstrap |
| `refused` | false | false | Нет подтверждённого retry effect |
| `unknown` / `outbox_commit_unknown` | false | null | Native outcome не доказан; primary/owner/quarantine сохранены |
| Commit + journal/notification/context error | false | true | Commit известен; typed deferred notification; не rollback |

Ошибки возвращаются только фиксированными кодами, в том числе
`outbox_payload_invalid`, `outbox_target_missing_or_invalid`, `outbox_target_mismatch`,
`outbox_claim_changed`, `outbox_job_not_failed`, `outbox_job_leased`,
`outbox_retry_snapshot_changed`, `outbox_retry_no_effect`, `outbox_retry_failed`,
`outbox_retry_callback_lifetime_unsupported`, `outbox_postcommit_failed`,
`outbox_worker_notification_failed`. Notification ошибки имеют фиксированные состояния
`deferred_context_changed`, `deferred_postcommit_failed`, `deferred_notification_failed`;
до commit notification равен `not_requested`.
Повтор UNKNOWN не является способом снять quarantine.

## Подготовленные регрессии и граница доказательства

`tests/test_addressed_outbox_repair_source.py` инертен при collection: нет чтения
product sources, product import/exec, SQL/native/SDK, worker, network и ENV setup.
`__test__=False`; suite создаётся только явным вызовом после отдельного допуска.

- `make_policy_suite(policy)` — 12 подготовленных SOURCE policy cases: прежние 10
  сохранены, добавлены typed notification/deferred и запрет выдумывать commit/counts.
  Проверяются healthy current
  producer shape, literal IDs, malformed payload, bound target/alias, historical
  delete refusal, failed/lease, stale source labels, все поля job race, original
  epoch + counted-own effects, отсутствие raw diagnostic leakage. Эти cases не
  подменяют authority provider/SDK/SQL разрешающим stand-in: authority не исполняется.
- `make_metadata_suite(main_raw, cache_raw, baseline_main_raw, baseline_cache_raw,
  native_raw=..., baseline_native_raw=...)` — 15 подготовленных AST/JSON controls:
  schema/cache, реальные caller edges, ACL/source/target guards, CAS/afterimage,
  original admission после journal tail, native flight до actual commit и после
  callback, callback/setter/completion refusals, known/UNKNOWN retirement,
  locked registry-only notification. Есть различающие AST controls с удалёнными
  forwarding keyword и native fence. Прежнее требование полного равенства тела
  `_claim_transaction` заменено проверкой явно согласованного extension: старые
  mode/defaults сохранены, unchanged authority/worker/native peers сверяются отдельно.
- `make_native_owner_suite(fixture_factory)` — 17 подготовленных **настоящих native
  owner component** cases, не SOURCE: прежние 8 — callback-free commit, поздний journal actor
  drift, реальный authorizer/refusal, sticky trace install/remove, native shortcuts,
  fatal rollback, fatal после known commit и отсутствие whole-store maintenance
  при absent/dead worker. Последний из прежних cases не запускает thread и сравнивает весь
  собственный SQL store, включая unaddressed legacy completed payload. Девять новых
  correction02 controls перечислены выше; они используют тот же реальный fixture.
  Передаётся прежний shipped
  `tests/ci_owned/derived_claim_materialization_fixture.py:Fixture` при активном
  штатном `derived_case`, с genuine SPI/connection и отдельным native/SQL допуском.
  Маленькая собственная SQL table и тестовый original-admission callback проверяют
  только stage owner; они **не** подменяют настоящие public ACL/DisclosureFence/target
  и не доказывают lawful public repair. Source imports при collection отсутствуют.
- `PUBLIC_NATIVE_REQUIREMENTS` оставляет 7 явных NOT_RUN требований для actual public
  semantic/erasure fixture, включая whole-store readback чужого legacy completed
  payload при absent/dead worker, настоящий healthy producer upsert, late source/
  target drift, UNKNOWN и notification failure. Готового разрешающего stand-in для
  этих недостающих ролей нет. UNKNOWN safety teardown прежней document fixture не
  переносится автоматически: close guard намеренно удерживает новый stage, поэтому
  нужен separately admitted base-descriptor safety close **после** snapshot, без
  очистки quarantine/owner/stage. Он не реализован как production recovery.

Для будущего малого SOURCE packet родитель использует существующий `devtools/harness.py`
и его source bootstrap/loader с **полными точными малыми** `outbox_repair_policy.py` и
этим test module; затем штатный `unittest.TestSuite`/runner и полный case roster.
Нет нового loader/framework. `__init__.py` больше per-file binder 1 MB: он допускается
здесь только как raw input для отдельной AST/JSON metadata проверки. Его нельзя
передавать в behavioral binder через explicit bindings, compression или extracted
full-main и называть это исполнением public repair. Широкие parity/FULL/census/pins
не меняются и не запускаются.

При авторстве выполнены только AST/JSON/raw hashing/Git metadata проверки; **все
подготовленные test bodies, SOURCE execution, SQL/native/SDK/worker и public E2E —
NOT_RUN**. Свежий applicable SOURCE admission, независимое review и приёмка остаются
родителю. Подтверждён прежний source mechanism, не исторический runtime incident;
исходная версия и raw diagnostics/receipts не переписываются новым кандидатом.

## Перенос полного CODE на current 4b/ac8 (2026-10-30)

Предшествующие разделы и receipts — история donor d6fb→cc40, не новое исполнение.
Текущий CODE переносит всю кумулятивную feature, включая обе corrections, на
`4b32def39cb9272fae54f15859e82563eb78c95f` / tree
`10d98c9efe032aafe45d04f10f4107e3b47d02d6` (production ac8 + test-only corrections).
Только шесть feature paths изменены. Whole donor tree/старый initializer не принят.

Current `_commit_receipt` сохранён в сигнатуре перед добавленным `_outbox_retry`,
включая standalone-mode validation и публикацию после настоящего COMMIT до journal.
Outbox stage явно несовместим также с этим passive receipt; обычные maintenance
owners/dispatch и non-retryable postcommit diagnostics не меняются. Поздние rerank
local-failure/usage, health UNKNOWN, document revision/observation, profile/privacy/
ACL/erasure и fatal-primary механизмы остаются current, а не donor fallback.

Все 44 donor test bodies/setup/helpers сохранены. Metadata factory получила
строгий raw-SHA rebind baseline inputs на current 4b; её прежняя suite construction
сохранена. Дополнительно готовы 3 AST controls (unchanged current guards/maintenance,
disjoint commit receipt, public schema/module wiring) и 2 native-owner controls
(mixed-mode refusal с последующим healthy retry, ordinary passive receipt с durable
readback). Итого 49 prepared methods: policy 12, metadata 18, native owner 19.
Семь public native obligations и UNKNOWN safety-teardown hold не сокращены/не
исправлены. Ни один test body, factory, helper, SDK, SQL, model или product import/exec
не запущен. Авторские проверки ниже — собственные inert AST/raw/Git, не test PASS.

`tests/test_cold_lane_current_composition.py` и `tests/test_cold_lane_partition.py`
не мигрируются: их исторические descriptor/transport/old41 evidence и behavioral
assertions не являются новой module/schema fingerprint. Frozen COLD descriptor уже
на исходном 4b не совпадает с current provider SHA и не включает 12 текущих test
files (357 declared против 369 Git paths); новый test даёт 370 Git paths. Это не
исправляется удалением старых checks или переделкой immutable census. Будущий полный
current-source/physical rebind требует отдельного применимого scope.

Carrier — bare CODE artifact без физического source checkout. Все новые source
bytes находятся в commit tree; полный base→candidate diff восстанавливается из
Git без второго большого patch-файла. Layout не обходит physical consumer,
native fixture, installer/scanner или qualification gates. Актуальное поведение,
SOURCE/native/SQL/SDK/FULL/Linux/CI и installed/loaded остаются **NOT_RUN**.
Независимое CODE-review, parent acceptance и fleet update выполняет родитель в
своей lane; этот candidate ничего не устанавливает и не публикует.


## Current correction01: три HOLD findings одним блоком

Этот source-only блок исправляет `OUTBOX-NESTED-CALLER-001`,
`CURRENT-CACHE-ORACLE-002` и `CURRENT-MODULE-INVENTORY-003` после review 45d3.
Исторический 45d3/c9, его HOLD, donor receipts и прежние отказы не переписываются.

Оба nested alias (`repair`, `memory_wiki_repair`) в `_transaction` передают
`args.get('outbox_job_ids')` буквально в suggest и apply: без trim/coercion/copy
списка IDs. Только для repair классифицируются явные `ok is False`, непустой
`error`, а также такие же поля непосредственных action records. Это не
рекурсивный отказ по произвольным вложенным данным и не blanket denial обычных
repair результатов без `ok`. Refusal остаётся в `results[].result`, но operation
получает стабильный `error=repair_returned_failure` до success post-count и
`_record_mutation`. Существующие `errors`, audit partial, public success=false и
journal error boundary теперь видят его. Предварительный apply count не является
успехом и сохранён. Suggest остаётся best-effort даже при stop_on_error=true;
apply сохраняет прежнюю stop policy. Multi-apply с repair по-прежнему отвергается
перед эффектом atomic-vocabulary guard: тест не обходит его ради continuation.
Fatal/UNKNOWN, privacy/revision/observation owners и callee admission не меняются.

Адресный test-owner handoff добавляет отдельный current cache pin для addressed
outbox; все прежние cache constants и полное сравнение dictionaries сохранены.
Обычный document egress fixture теперь имеет полный runtime38 roster с
`outbox_repair_policy.py`. Его current fingerprint заморожен после final initializer
тем же SHA256(sorted JSON name->raw-SHA, separators=(',', ':')) рецептом. Старый
complete37 observation gold сохранён именованной historical константой. Expected
не вычисляется из текущих inputs при исполнении. Setup/cleanup/guards не меняются.

Из исходных 49 test methods изменён только разрешённый metadata exemption:
`test_current_baseline_retained_guards_are_unchanged` включает `_transaction` в
исчерпывающий список намеренно изменённых owners. Остальные 48 methods и все
прежние helpers/factories/setup сохранены по AST. Добавлены 2 metadata methods и
9 native composition methods: итого 60 prepared methods (12 policy, 20 metadata,
19 native owner, 9 nested caller). Literal rosters проверяются отдельно от запуска.

Новая suite использует тот же genuine derived_case/Fixture, настоящие provider,
`_transaction` loop, `_repair`, public dispatcher и journal failure classifier.
Только retry/FTS/claim outcomes и audit/mutation/journal IO имеют явно authored
seams; `_connect` recorder делегирует настоящему connection. Нет fake owning
class, разрешающего ACL/target guard или нового loader. Controls покрывают оба
режима/alias, healthy literal IDs, typed/action/top-level refusal до success tail,
public success и before/error против before/after, ordinary repair без IDs,
nonrepair suggest best-effort, прежний atomic multi-apply отказ/claim batch и
identity fatal primary. Это не durable journal IO или реальный retry admission.

Все 60 test bodies/factories, 7 public/native obligations, SQL/SDK/native, Linux,
SOURCE behavior, FULL/E2E, CI/models/network/build/install/loaded/restart остаются
**NOT_RUN**. UNKNOWN safety-teardown hold прежний. Инертные AST/JSON/raw/Git checks
не означают TestCase PASS. Immutable correction commit, exact path/diff bindings,
metadata exits и ресурсы находятся в correction01/PARENT_RESULT2.json. Независимый delta
review и приёмка принадлежат родителю; блок ничего не публикует и не устанавливает.
