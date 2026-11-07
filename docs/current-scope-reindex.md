# Caller-visible reindex (opt-in)

Совместимое расширение `memory_wiki_reindex`:

```json
{"current_scope_only": true, "dry_run": true, "limit": 25}
```

Для настоящего read-only preflight используйте уже инициализированный provider и существующий native caller context. Новый путь не открывает/мигрирует store, не создаёт erasure authority и не пишет journal, registry, outbox, meta, access counters или debug log. Native SQLite WAL-reader может обновить только volatile read marks в `-shm`; это не byte-immutable/OS-level чтение. В gate main database, WAL и все остальные файлы сохраняют байты, SQL `total_changes` не растёт. Только ACL-ограниченные metadata SQL, authenticated read существующего erasure ledger и GET проверки semantic/target contract; никаких текстов памяти, embedding POST или создания коллекции. `dry_run` без `current_scope_only` отвергается. Новые boolean значения проверяются по точному типу; scope-only не принимает model-owned caller/SID/trusted-host поля.

После отдельного разрешения владельца выполнить ограниченное обновление можно тем же native инструментом с `dry_run: false`. Все записи выбираются по существующему claim ACL до work limit. Обновление in-place использует только существующий собственный active physical target с совпадающим manifest и доказанными dimensions/distance. Нет immutable target creation, alias switching, scroll/reconciliation, удаления точек, draining исторического DELETE outbox, архива/TTL изменений или исторического переноса. `force: true` в scope-only режиме отвергается до external I/O.

ACL, actor/context, source revision, text hash, manifest/target и erasure перепроверяются до чтения текста, до PUT и до registry commit. Registered vectors не используются: отсутствие права читать claim нельзя заменить чужим вектором. Для допустимой записи применяется существующий embedding guard, vector validator, canonical payload, Qdrant upsert с exact metadata readback и crash-safe `write_pending` registry. Ошибка/неизвестный remote outcome оставляет pending location; операция ничего не удаляет и не сообщает неподтверждённую доставку как успех.

`eligible_count` — metadata snapshot текущего доступного active корпуса, не общая численность shared store и не delivery proof. `limit: 0` обрабатывает весь этот snapshot; положительный limit ограничивает попытки. Возвращаются только счётчики выбранного корпуса, не ID/тексты чужих claims. `scoped_completed` означает завершение выбранного snapshot; `scoped_partial` честно отражает limit/failures, `scoped_noop` — отсутствие eligible записей. Это синхронный вызов, не новая фоновая очередь. Уже существующие full-reindex jobs остаются неизменными.

При `current_scope_only: false` и `dry_run: false` работает прежний immutable full-index режим с ID-based reconciliation и старым recovery contract. Новый scope-only путь не журналируется как full-corpus replay: только safe per-point delivery registry, чтобы recovery не расширял caller authority.

В scoped режиме `auto`/`require` привязка к target доказывается свежим `GET /aliases`: валидная схема ответа и ровно одна запись настроенного alias на собственный manifest-compatible physical target. Недоступный/невалидный ответ, отсутствие или дубликат alias — bounded refusal, не разрешение использовать совместимый base. Legacy negative capability cache не является authority и не мешает свежему положительному ответу. Привязка перепроверяется на scoped fences, включая до PUT и до active commit. Явно настроенный `physical` — отдельный контракт с `target_binding: explicit_physical`; alias-привязка помечена `configured_alias`.

Все scoped prerequisites, native connection access, импорты и public handler/profile ошибки остаются внутри bounded refusal: `ok: false`, `success: false`, `status: refused`, без reconnect/migration или нового provider. Наружу проходят только точные code-owned причины из safelist; `scope_` в начале чужого exception message не даёт права переслать текст. Erasure sequence читается непосредственно из уже привязанного connection. Public scoped dispatcher намеренно обходит full-corpus journal; существующий `_should_journal_tool` не меняется. Это не distributed CAS или универсальная атомарность.

## Проверка и ограничения

`repair01/evidence/native_gate.py` и `native_run.py` образуют bounded native gate на настоящем установленном SDK/MRO/registry и byte-exact typed trust guard. Восемь прежних сценариев сохранены; два ближайших regression-сценария проверяют strict alias/physical binding и prerequisite/error envelope. Сценарии используют свежие tiny synthetic stores и синтетические ответы только на external Qdrant/embedding boundary. Это не remote proof, не proof loaded pivo и не OS sandbox: Python audit запрещает сеть/child calls и записи вне owned fixture/artifact roots. Реальный владелец pivo, исторический перенос и erasure continuity исторических clones этим gate не подтверждаются.

В данной копии установка, публикация, restart и live reindex не выполняются. Перед будущим запуском нужны отдельные source admission и подтверждение загрузки именно этих bytes настоящим owner chat.

## Миграция embedding-провайдера в общей базе

`provider` входит в physical manifest hash. Поэтому смена Nous → OpenRouter
меняет контракт, даже если model slug и размерность совпадают. Scope-only не
мигрирует индекс. Legacy full reindex может копировать невидимые ему записи
только из зарегистрированного источника с **тем же** manifest; это ограничение
сохраняется. Новый provider не получает права читать чужой текст.

Для отдельно разрешённой миграции добавлен opt-in:

```json
{"provider_migration": true, "limit": 25}
```

Это **записывающая** операция, не preview. Её нельзя сочетать с
`current_scope_only`, `dry_run` или `force`. Она требует уже инициализированного
native provider с собственным соединением и действующим caller context.
Каждый вызов строит embeddings только для доступных этому владельцу active
claims. Его прежние SID/bot IDs из базы не являются разрешением. Если прав на
остальные записи нет, возвращается `awaiting_authorized_owners`; старый alias
остаётся на месте. Следующие владельцы вызывают тот же инструмент **из своих
действующих контекстов**. Идентификаторы и тексты чужих claims не выдаются.

Хост также может вызвать `provider.migrate_embedding_index(owners=(...))`,
передав уже имеющиеся настоящие авторизованные provider objects для той же
базы и home. Это не model-facing tool: метод не перечисляет владельцев,
не создаёт их по сохранённым идентификаторам и не меняет их scopes. Если
нужного владельца больше нет, миграция ждёт; автоматического обхода нет.

Новый physical staging target и content-free receipts сохраняются в
`embedding_migrations` / `embedding_migration_points`. При здоровом частичном
прогоне повторный вызов использует тот же job/target и подтверждённые receipts,
не встраивая успешно обработанные документы заново. В shared staging нет
plaintext preview. Неподтверждённый point PUT или неоднозначный alias POST
останавливает автоматическое продолжение: `migration_pending_write_outcome_unknown`
или `migration_alias_outcome_unknown`. Это не разрешение повторить платный
запрос либо создать новый job; отдельного автоматического resolver здесь нет.

Перед переключением проверяются полный exact набор ID и payload digests,
включая content hash, revisions и ACL, а также database identity и erasure
ledger. Финальная повторная проверка и единственная atomic alias transaction
выполняются при SQLite `BEGIN IMMEDIATE` и существующем межпроцессном native
operation lock. Это координация штатных writers плагина, не distributed CAS
против стороннего администратора Qdrant. Drift или неполное покрытие до POST
оставляет alias неизменным. Старый physical индекс не удаляется; его retained
registry позволяет согласованный откат и privacy cleanup. Async claim writer
не записывает в него новые несовместимые embeddings во время ожидания.

Незавершённые claim DELETE jobs (`pending` / `processing` / `failed`) дают
`migration_claim_deletes_not_quiescent` до alias POST: уже выданный worker мог
бы изменить staging без новой claim revision. Мигратор не исполняет чужую
очередь вместо её владельца. Сначала нужно штатно завершить/разрешить эти
удаления; повторная проверка под тем же SQLite writer lock обязательна.

Одной пустой очереди недостаточно: stale worker может сохранять локально
уже reclaimed/ACKed row. Claim DELETE дополнительно проверяет исходный lease
в том же SQLite writer slot, который удерживает до завершения реального HTTP
effect. Отдельный content-free `claim_vector_delete_effects` intent коммитится
до возможной отправки. Timeout/исключение оставляет `unknown`/`pending` даже
после успешного ACK преемником; cutover не разрешён, пока такой исход не
разрешён отдельной процедурой. Автоматического сброса UNKNOWN нет. Эта
граница требует согласованно обновлённых writers; старые уже загруженные
процессы без нового effect fence должны быть отдельно quiesced до live run.

Native `on_session_switch` и мигратор разделяют provider lock. Кроме того,
original actor проверяется после отбора, до intent и до raw hydration —
новый fence не может молча принять права другой session. Повторный вход
после `activation_unknown` сохраняет `alias_switched=null`, без нового
embedding или alias POST; `false` не подменяет неразрешённую активацию.

`completed` относится к проверенному миграционному snapshot. Это не установка,
не restart и не доказательство работоспособности live-бота. Для приёмки нужен
непустой настоящий vector/hybrid поиск; FTS или rerank сами по себе недостаточны.
Регрессии в `tests/test_provider_migration.py` требуют явного disposable
Qdrant через `MW_MIGRATION_TEST_QDRANT_URL=http://127.0.0.1:6333`; без него они
помечаются skipped, а не успешно проверенными. Транспорт модели синтетический;
это не проверка доступности, биллинга или качества настоящего OpenRouter.
