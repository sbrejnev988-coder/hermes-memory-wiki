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

Start/wake существующего worker находятся после успешного возврата настоящего owner
из COMMIT/retirement и используют исходный DB path. Dry-run, отказ, no-effect,
rollback и UNKNOWN не будят worker. Worker повторно проверяет canonical state обычным
путём; сам `_outbox_process_scoped` не изменён. Пробуждение не доказывает delivery.

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
| `addressed_committed` | true | true | Retry state committed, worker notification вернулся; не delivery |
| `refused` | false | false | Нет подтверждённого retry effect |
| `unknown` / `outbox_commit_unknown` | false | null | Native outcome не доказан; primary/owner/quarantine сохранены |
| Commit + wake/context error | false | true | Собственный commit известен, notification не подтверждён |

Ошибки возвращаются только фиксированными кодами, в том числе
`outbox_payload_invalid`, `outbox_target_missing_or_invalid`, `outbox_target_mismatch`,
`outbox_claim_changed`, `outbox_job_not_failed`, `outbox_job_leased`,
`outbox_retry_snapshot_changed`, `outbox_retry_no_effect`, `outbox_retry_failed`.
Повтор UNKNOWN не является способом снять quarantine.

## Подготовленные регрессии и граница доказательства

`tests/test_addressed_outbox_repair_source.py` инертен при collection: нет чтения
product sources, product import/exec, SQL/native/SDK, worker, network и ENV setup.
`__test__=False`; suite создаётся только явным вызовом после отдельного допуска.

- `make_policy_suite(policy)` — 10 отдельных SOURCE policy cases: healthy current
  producer shape, literal IDs, malformed payload, bound target/alias, historical
  delete refusal, failed/lease, stale source labels, все поля job race, original
  epoch + counted-own effects, отсутствие raw diagnostic leakage. Эти cases не
  подменяют authority provider/SDK/SQL разрешающим stand-in: authority не исполняется.
- `make_metadata_suite(main_raw, cache_raw, baseline_main_raw, baseline_cache_raw)` —
  6 отдельных AST/JSON controls: schema/cache, реальные caller edges, native/ACL/source
  guard wiring, conditional UPDATE/postcommit wake, неизменённые worker/authority
  owners, различающий локальный control с удалённым forwarding keyword.

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
