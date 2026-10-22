# Embedding при повторном document ingest

## Что исправляет этот блок

Раньше `ingest_document` выполнял embedding handoff в конце обычного пути
материализации, но возвращал `unchanged` и `scope_updated` раньше этой точки.
Поэтому явный `embed: true` терялся при повторном добавлении неизменного файла
и при изменении только его scope. У scan stat-fast path собственный handoff
уже был; он здесь не меняется.

Теперь три успешных выхода используют один `_embed_ingest_result`:

1. Завершается исходный `_ingest_transaction`, включая его прежние
   authority/hook/replay проверки. Если выход транзакции бросил исключение,
   до нового handoff исполнение не доходит.
2. При фактическом embedding intent вызывается прежний `embed_pending_documents`.
3. Результат проходит прежний `_guard_document_output(..., provider=provider)`.

Это не перенос embedding внутрь ingest writer и не новая транзакционная
возможность. Выход owning stage сам по себе не обещает COMMIT внешней
транзакции: существующий joined/pending-commit контракт остаётся прежним.

## Аргументы и значения по умолчанию

Пример аргументов **явной команды индексирования**, а не разрешение её выполнить:

```json
{"path":"C:/Documents/report.pdf","embed":true,"embed_limit":200}
```

Сохраняется исходная политика:

```python
bool(args.get("embed", _env_bool("MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST", False)))
```

- Для обычного вызова без `embed` и без включённого доверенного default embedding
  выключен. Явный `false` подавляет включённый default; явный `true` запрашивает
  handoff независимо от default.
- `_env_bool` и `_document_env` не заменены. В strict profile scope собственное
  значение settings имеет приоритет; отсутствие этого ключа не наследует
  одноимённое ambient ENV. Этот ключ не входит в allowlist глобальных defaults.
  Файлы профиля или `.env` новый helper сам не читает.
- Это прежний `bool(value)`, без новой валидации/парсинга строк: передавайте JSON
  boolean, не строку `"false"`, которая в Python непустая и потому truthy.
- Payload остаётся ровно `{"source_id": source_id, "limit": int(args.get("embed_limit") or 200)}`.
  ID берётся из уже установленной ingest identity, не из request `source_id`;
  whitespace/Unicode helper не нормализует. Не добавляются scope/repository,
  route/model/permission аргументы. Значение limit по умолчанию — **200**;
  дальнейшие eligibility/limit/ACL проверки принадлежат прежнему embedding API.

Без embedding intent callback не вызывается и поле `embedding` не добавляется.
При intent предусмотрен один handoff для данного выхода ingest, но не обещание
одного model/HTTP вызова: работа внутри прежнего callback здесь не менялась.

## Как читать результат

Верхний `status` описывает ingest: `unchanged`, `scope_updated` либо исходный
результат материализации (`indexed` при `extractor_status == "ok"`). Helper
не переписывает этот статус, revision/hash, structural counts или другие поля;
обычный путь материализации, включая его прежние non-ok результаты, сохранён.
Существующий output guard по-прежнему формирует публичную безопасную выдачу.

При handoff появляется отдельное `embedding` с исходным значением callback.
`pending`, `pending_commit`, `blocked`, `retry` и ошибки не превращаются в
`completed`. Исключение callback не поглощается и не заменяется успехом.
После такого исключения ingest stage мог уже завершиться; это не обещание
отката прежних committed effects. Исходные счётчики, например
`embedding_pending` у `scope_updated`/`indexed`, остаются снимком **до** handoff;
актуальный embedding outcome следует читать отдельно, а не вычитать из них
выдуманный успех.

Даже `embedding.status == "completed"` у существующего API означает локальную
связь chunks с claims, **не подтверждённую доставку векторов в remote index**.
Этот блок не доказывает extraction quality, supported answer с точной цитатой,
remote delivery или полный цикл update/erasure.

## Граница проверки и SOURCE handoff

Файл `tests/test_document_embedding_handoff_source.py` содержит ровно восемь
explicit `unittest` mains в объявленном порядке:

- шесть SOURCE callable controls: off/default-off; один handoff и сохранение
  identity/полей трёх результатов; настоящий ENV/profile reader и приоритеты;
  точные payload/default/limit; typed callback outcomes без fake success;
  сохранение исходного raised primary, включая cancellation;
- два **STATIC** controls: три call sites после исходных transaction blocks и
  перед output guard; обратная AST-дельта к frozen baseline и сохранность
  остального graph, включая SQL/owner/ACL/privacy/cache/fingerprint/admission.

Callable controls клонируют настоящий helper CodeType из **полного** загруженного
source и заменяют только ссылку `embed_pending_documents` на dispatch observer.
Он наблюдает аргументы и возвращает/бросает явно authored значения; это не
подмена writer, SDK, SQL, permission, output guard или ACL. Реальный embedding
callback ни разу не должен выполняться. Callers и транзакции не исполняются.

Peer `tests/test_document_parser_pdf_ocr.py` предоставляет неизменённые
`read_source`/`load_source` и исходный `PacketResult`. Старые peer tests не
выбираются. Import/collection инертны; у модуля и класса `__test__ = False`.
Фактический pytest discovery не проверен. Main дополнительно требует исходный
`devtools/source_bootstrap.py`, `-I -B -S`, bound reader и собственную sterile
scratch/home среду **до** чтения peer/product. Используется штатный
`unittest.TestSuite`, не прямые вызовы test methods.

На этапе подготовки разрешены только AST, inert compile и Git metadata.
**Тесты, collection, продуктовые импорты, SQL/SDK/native/model/network и старые
пакеты NOT_RUN.** Родитель отдельно допускает единственный будущий SOURCE packet
через существующий публичный `devtools.harness.run_source`; точные входы, hashes,
closure, roster и caps находятся в lane `PREPARE.json`, итог автора — в
`RESULT.json`. Это отдельный локальный source checkpoint, не integration,
publish/install/loaded/native/E2E/FULL приёмка.

Чтение, вложение или Vision-анализ документа сами по себе не разрешают ingest,
scan, inbox или embedding. Настоящее индексирование и remote/model эффекты
требуют отдельной явной команды владельца и исходных security/resource gates.
