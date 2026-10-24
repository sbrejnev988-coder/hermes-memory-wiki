# Контекст документа с привязкой к ревизии

## Контракт

`memory_wiki_document_unit_context` и `memory_wiki_document_neighbors` принимают
необязательный `expected_revision_id`. Он предназначен для продолжения работы
с уже полученной цитатой, а не для чтения истории документа.

| Запрос | Поведение |
|---|---|
| Поле отсутствует | Намеренная навигация по координатам **текущей** активной ревизии. После обновления тот же `anchor` может обозначать новый текст. |
| Передан точный текущий `revision_id` | Чтение только этой текущей ревизии, при сохранении всех обычных проверок доступа и раскрытия. |
| Передана другая корректная ревизия | Отказ `document revision mismatch` до чтения units/edges. Автоматического перехода на новую ревизию нет. |
| Переданы `null`, число, boolean, контейнер, пустая или некорректная строка | Отказ `invalid expected_revision_id` для доступного источника. Отсутствие поля и явное пустое значение различаются. |
| Источник отсутствует или больше не активен | Прежний отказ `document source not found`; старый текст не восстанавливается. |
| Передан старый `unit_id` вместе с повторно использованным `anchor` | Приоритет остаётся у `unit_id`; при его отсутствии в текущей ревизии — `document unit not found`, без fallback к anchor. |

Ревизии создаются существующим producer в формате `docrev_` и 28 строчных
шестнадцатеричных символов. Новый параметр принимает именно этот формат
(35 символов). Сравнение буквальное: без `strip`, преобразования типа,
`casefold`, изменения регистра или Unicode-нормализации. Повреждённая текущая
ревизия также не даёт успешного ответа: `document revision unavailable`.
Это не миграция данных и не разрешение нормализовать сохранённые идентификаторы.

## Продолжение цитаты

Иллюстрация использования; это не выполненный пример и не полученные от сервиса
идентификаторы:

```python
# hit — ранее допущенный результат document_query с сохранённой идентичностью.
context_args = {
    "source_id": hit["source_id"],
    "unit_id": hit["unit_id"],
    "anchor": hit["anchor"],
    "expected_revision_id": hit["revision_id"],
    "radius": 2,
}
neighbors_args = {
    "source_id": hit["source_id"],
    "anchor": hit["anchor"],
    "expected_revision_id": hit["revision_id"],
    "hops": 1,
}
```

При R1 → R2 старый pin отказывается. Для сознательной навигации по текущему
документу caller может сделать **отдельный** запрос без pin. Нельзя автоматически
убирать `expected_revision_id` после отказа и представлять результат как
разрешение исходной цитаты. Если guards изменили или скрыли идентификатор,
его нельзя восстанавливать из старого raw payload.

Успешный допущенный context содержит `source_id`, `revision_id`,
`target_ordinal`, `units`; каждый unit содержит собственные `source_id` и
`revision_id`. Neighbors содержит `source_id`, `revision_id`, `anchor`, `hops`,
`edges`, `nodes`; каждое ребро также несёт `source_id` и `revision_id`.
Существующие лимиты, порядок представления и возможное повторение ребра при
обходе не переопределены. `nodes` — координаты внутри выбранной ревизии,
а не исторические сущности.

**Идентичность цитаты не доказывает смысловую поддержку вывода.** Совпавшая
ревизия подтверждает адресуемую текущую версию, но не entailment ответа модели,
полноту извлечения или актуальность первоисточника вне индекса.

## Доступ и сохранённые границы раскрытия

1. Сначала выбирается активный source, сохраняется существующий raw read fence,
   выполняются прежние source/profile/repository и connector-owner проверки.
2. Только затем проверяется новый pin. Ошибки не содержат ни запрошенной,
   ни фактической ревизии; неизвестный или чужой source не получает отдельного
   version-сигнала. Формат pin также не проверяется раньше этих проверок доступа.
3. Поиск target unit, окно units и **каждый** шаг обхода edges ограничены
   `source_id`, выбранным `revision_id` и `active=1`. Рёбра не связываются JOIN
   с units: формульные/cell coordinates не обязаны быть самостоятельными units.
4. Сохраняются watch исходного source, возвращаемых units/edges, локальная
   санитизация и `_disclosed_document_output`. Не меняются schema/ACL/guards,
   `DisclosureFence`, `TerminalDelivery`, `_retain_read_fence` и конечная
   сериализация/owner-проверка. Дрейф или veto не разрешают «починить» raw ID.

Новые SQL-предикаты используют уже существующие `revision_id` в
`document_sources`, `document_units`, `document_edges`. DDL, индексы и
`SCHEMA_VERSION` не изменены. Это read-only дополнение: индексирование,
scan/ingest, embeddings и reindex **не запускаются** им и допустимы только по
явной отдельной команде владельца. Продуктовая реализация не содержит
Windows/Linux-specific ветвей или абсолютных путей.

## Регрессии и граница доказательства

`tests/test_document_citation_revision_source.py` использует существующий
шаблон `test_hybrid_budget_observability_source.py`: явный `source_suite`,
`unittest.TestCase` с настоящим fixture/cleanup lifecycle и извлечение точных AST
bodies в один namespace. При обычной collection нет product reads/imports,
исполнения definitions или fixture setup. Первый source read/AST остаётся
после собственного isolated scratch setup и оригинального audit fence
`devtools/source_bootstrap.py`.

Подготовлены:

- **12 SOURCE-controls:** healthy pinned/unbound; символический R1 → R2;
  stale unit без fallback; malformed/type/empty и literal pins; настоящий
  source/connector-check body на synthetic labels до version-сигнала;
  missing/retired source; чужие, неактивные и cross-revision units/edges;
  все hops; watch dependencies; реальные local redaction и deny-only fence.
- **3 STATIC-controls** в том же малом SOURCE-пакете: порядок проверок и
  параметры чтения, неизменные DDL/guards, исходные disclosure owners.
- **3 дополнительных PARENT_STATIC-controls:** полные словари двух native
  declarations против cache, неизменные остальные cache records и main AST,
  неизменные terminal dispatch/retention bodies. Они сохранены в suite, но
  **не входят** в подготовленный малый SOURCE entry.

`ReadObserver` — явно authored finite relational control, не SQLite и не SDK.
Исполняемый суффикс начинается после создания connection/schema/fence и всегда
останавливается на **proposal**, не выдавая успешный public response и не
имитируя разрешающий disclosure/authority validator. Используются настоящие
source/connector-check и local sanitizer bodies, но synthetic policy/rows не
являются genuine profile authorization. R1 → R2 не исполняет ingest/update.
Отдельный отрицательный control вызывает реальный `_disclosed_document_output`
только с deny-only fence. Полная public/SQL/native owner-композиция остаётся
`NOT_RUN`.

Автор не запускал suite, collection, product import/exec, SDK/SQL/model/CI.
Разрешённая авторская проверка — только AST/JSON/Git metadata. Поэтому
перечисленные test cases — **подготовленные**, а не passed. Результаты
будущего родительского SOURCE-пакета должны отдельно считать 12 SOURCE и
3 STATIC mains, не выдавая их за native acceptance.

### Большой main и неизменный harness

`harness.bindings()` отказывает для отдельного input больше 1 000 000 B.
Исходный main уже превышает этот размер. Проверенная цепочка прежней приёмки
`repairs/hybrid-current-cohort-20261024/PARENT_ACCEPTANCE.json` → `SOURCE_RESULT`
→ `SOURCE_PACKET.json` → `source_packet.py` использовала `h.bindings()` и
компрессированный `candidate_main_fix01.zlib`, а не raw-main исключение из cap.
Сам по себе параметр `run_source(source_bindings=...)` не разрешает обход.

Новый инертный `SOURCE_ENTRY.py` читает только малые hash-bound inputs:
новый test, graph, extractor, guard, disclosure fence и существующий
`scripts/ci_owned/source_suites.py` для исходных `CaseResult`/`case_report`.
Нового loader/controller/reporter framework, SDK stand-in, увеличения cap и
raw-main binding нет. Main/cache parity и native terminal checks относятся
к отдельной честной родительской **STATIC** сверке; исходный код этих трёх
регрессий сохранён. Подготовка нового compressed-main carrier не входит в
этот author scope и не является обязательной для малого SOURCE-пакета.

Родитель самостоятельно связывает финальные bytes, current selected Python,
ресурсы и единственный ещё не израсходованный SOURCE-допуск. Авторский
candidate commit не является приёмкой, integration или установкой.

## Зависимые текущие pins: что ещё требует qualification

Разрешённая дельта ограничена пятью файлами. Следующие существующие consumers
не переписывались и не прогонялись:

| Группа | Следствие изменения |
|---|---|
| `docs/COLD_LANES.json`, `tests/test_cold_lane_current_composition.py` | Census/source pins остаются на прежнем main; новый test ещё не включён в текущую partition/factory closure. Требуется отдельное адресное обновление текущей проекции, не замена исторического плана. |
| `tests/test_ci_checkout_eol.py`, `tests/test_p2_g4_identity_errors.py`, `tests/test_foundation_ci_prerequisites.py`, `tests/test_foundation_ci_review_boundaries.py`, `tests/test_hybrid_current_cohort.py` | Текущие raw-main LF/CRLF pins и их literal inverse/review expectations требуют нового связанного witness. Старые `OLD_*`, original gold и исторические результаты сохраняются буквально. |
| `tests/test_audit_package_contracts_20261003.py` | `CURRENT_CACHE_SHA256_SOURCE_20261023` больше не соответствует дополненному cache; старые cache/metadata gold не меняются. Нужен отдельный current-pin rebind с полной schema parity, не фиктивный native export. |
| `tests/ci_owned/document_egress_fixture.py` и source/cold inventories | Полные runtime-source inventory hashes зависят от main/graph; прежние receipts не квалифицируют новый candidate. |
| `tests/test_document_unit_context_order_source.py` | Старый STATIC oracle «всё вне row-loop неизменно» не описывает новую намеренную revision-дельту вокруг loop. Его исторический результат остаётся прежним; current qualification требует адресного согласования oracle. |
| `tests/test_tool_schema_source_parity.py`, `tests/test_mcp_compatibility_contract.py`, packaging/release native generator | Двух-record AST/JSON parity независимо проверяема без provider import; настоящие exporter/SDK/release gates этим не заменены и здесь `NOT_RUN`. |

Исторические docs/qualification/release receipts — свидетельства своих exact
inputs, не автоматические текущие oracles. Их нельзя blanket-replace новым SHA.
Сам факт несовпадения старого raw pin — qualification gap, не доказательство
runtime regression. Дополнительный parser/whole-suite/native/CI/installed/loaded
PASS, Windows/Linux public lifecycle и независимое ревью данного candidate
этим документом не заявлены.
