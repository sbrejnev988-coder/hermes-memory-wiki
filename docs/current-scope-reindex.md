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
