# Привязка document lookup к текущей ревизии

Статус этого блока: **CODE + prepared regressions, все исполнения NOT_RUN**.
База — `59fe5bc3d2e620fd87d2096f727f6272466d4026`, дерево
`479b26b16391ea78911c98f10b5e3559a7e943b9`. Механизм перенесён из принятого
локального donor `346778f6e315143a5e0072cf3d0a686980d79c5f` относительно его
origin `028fe5f1471ee06e49261b29af9e31aade42fc80`. Это адресный перенос, не
замена текущих файлов файлами donor и не перенос прежнего SOURCE PASS.

## Контракт

`memory_wiki_document_unit_context` и `memory_wiki_document_neighbors` принимают
необязательный `expected_revision_id`. Формат — ровно `docrev_` и 28 строчных
шестнадцатеричных символов, то есть 35 символов целиком. В публичных декларациях
и packaged cache задан одинаковый строковый параметр с `minLength`, `maxLength`
и `pattern`; параметр не имеет default и не входит в required.

- **Параметр отсутствует:** намеренная навигация по координатам текущей
  индексированной ревизии. Это не запрос исторического текста и не подтверждение
  прежней цитаты по повторно использованному anchor.
- **Передан точный текущий ID:** чтение привязано к этой ревизии.
- **Передан корректный, но другой ID:** `document revision mismatch` до чтения
  units/edges. Автоматического перехода на latest нет.
- **Передано malformed значение:** `invalid expected_revision_id`. Пустая строка,
  null, bool, число, bytes, строковый подкласс, пробелы, перевод строки, иной
  регистр и Unicode-двойники не равны omission. Reader не вызывает `str`, `strip`,
  `lower` или `casefold` для этого параметра.
- **Текущий source содержит некорректный revision_id:** `document revision unavailable`,
  а не восстановление или догадка о версии.

Порядок reader: активный source → прежний disclosure watch → source ACL →
connector owner → проверка буквального pin → чтение содержимого. Ошибки версии
не включают ни supplied, ни current ID. Существующие missing/retired source и
scope/connector отказы предшествуют проверке pin; новая проверка не обходит их.

Target unit по `unit_id` или anchor, окно контекста и каждый hop edges ограничены
одновременно `source_id`, текущим `revision_id` и `active=1`. Если передан старый
`unit_id`, допустимый anchor не служит fallback. Успешное **предложение** содержит
фактический `revision_id` сверху и `source_id`/`revision_id` на строках. Все поля
по-прежнему проходят текущие row projection, очистку, XLSX hydration и disclosure.
При позднем veto ID не восстанавливаются поверх withheld output.

ID — идентичность индексированного состояния, не доказательство freshness файла
на диске, семантической поддержки ответа или отсутствия последующего изменения.
Новых writer, DDL, migration, watch/auto-index/ingest действий нет. Существующая
инициализация схемы в reader, radius/hops/limit, порядок строк и terminal fences
не менялись. Согласованность при конкурентном обновлении и итоговая публичная
выдача требуют отдельной SQL/native qualification.

## Публичная связка

1. `MemoryWikiProvider.get_tool_schemas()` объявляет оба инструмента и их
   argument properties через существующую `P`; изменены только две записи.
2. `mcp-wrapper/tool_schemas.json` содержит те же полные две записи; порядок и
   остальные records сохраняются. Отдельной второй таблицы argument validators
   для этих инструментов в current59fe нет.
3. Native `handle_tool_call` создаёт `a = dict(args or {})` и передаёт `a` в
   `_document_unit_context(self, a)` / `_document_neighbors(self, a)` без новой
   фильтрации аргумента. Прежние lifecycle, reserved-argument, journal, profile
   и terminal владельцы не изменены.
4. Package-relative и standalone fallback imports связывают эти aliases с
   настоящими readers в `document_knowledge_graph.py`.
5. Неизменённый `mcp-wrapper/server.py` переводит `parameters` в `inputSchema`,
   получает актуальные native schemas и проверяет, что `arguments` — объект.
   Он передаёт объект в provider; отдельного исполнения JSON Schema validator
   или стирания malformed pin до reader здесь не заявляется. Авторизация и
   буквальная проверка значения остаются у reader. Дисковый runtime cache не
   обновлялся: packaged declaration не доказывает actual loaded MCP/native schema.

## Prepared регрессии

Новый модуль `tests/test_document_revision_integration_source.py` использует
ReadObserver/proposal-stop и stdlib unittest lifecycle принятого donor. Он не
создаёт runner, SDK stand-in или разрешающий authority/disclosure double.
Обычная collection инертна по конструкции: stdlib imports и declarations;
product reads/import/exec, fixture, вызовы фабрики и cases на уровне модуля
отсутствуют. Actual collection **NOT_RUN**. Класс TestCase создаётся только
явным `build_suite`; mixin не является TestCase.

Фабрика, **не вызванная в авторской фазе**:

```python
build_suite(sources, *, declared_inputs, scratch, parent_static=False)
```

- `sources`: точный dict `role -> frozen UTF-8 source string`, не пути и не loaders.
- `declared_inputs`: те же roles, каждое значение — tuple `(raw_sha256, immutable_filename)`.
  Parent передаёт фактические candidate bytes и baseline59fe blobs, без
  нормализации EOL или реконструкции соседнего checkout.
- `scratch`: собственный уже допущенный абсолютный scratch. Фабрика не выдаёт
  execution grant. Setup требует исходный isolated `-I -B -S` режим; flags сами
  по себе не являются audit/OS isolation proof.
- SOURCE roles: `graph`, `baseline_graph`, `extractor`, `guard`, `fence`,
  `baseline_fence`. Поддержка берётся из frozen59fe; `baseline_graph` — исходный
  graph59fe, `graph` — новый candidate. Все input bindings и audit admission
  остаются обязанностью неизменённого `devtools/harness.py`/source bootstrap.
- `parent_static=True` roles: `main`, `baseline_main`, `cache`, `baseline_cache`,
  `wrapper`, `baseline_wrapper`. Native main превышает стандартный лимит одного
  input harness. Наличие локального test cap 2 MB не разрешает его обходить:
  эти cases требуют отдельно допущенной STATIC работы с точными большими strings,
  а не нового сжатого carrier, изменения controller или разрешения native exec.

Фабрика возвращает штатный `unittest.TestSuite` с литеральным roster; она ничего
не запускает. Процесс, reporter, audit, freeze и допуск должны оставаться у
существующего controller. Новый invoker/runner в этом блоке не добавлен.

Матрица подготовленных cases:

| IDs методов | Проверяемое свойство | Уровень |
|---|---|---|
| `test_01`–`test_03` | omission/match, символический R1→R2, stale unit без anchor fallback | SOURCE proposal |
| `test_04`–`test_05` | supplied типы/пустота, буквальный формат, mismatch без ID, corrupt current | SOURCE refusal/proposal |
| `test_06`–`test_08` | scope/connector/missing/retired до сигналов версии и содержимого | SOURCE refusal |
| `test_09`–`test_10` | cross-source/revision/inactive filtering target/window и всех hops | SOURCE proposal |
| `test_11` | прежние row watches и настоящая локальная redaction | SOURCE proposal |
| `test_12` | настоящий local output owner + deny-only fence, без восстановления ID | SOURCE deny-only |
| `test_13`–`test_16` | auth/read order, DDL/guards, disclosure и весь graph вне трёх owners, row loop и argument clamps | STATIC |
| `test_17` | здоровые разные окна, hops и limit, непустой counterpart | SOURCE proposal |
| три `test_PARENT_STATIC_*` | полная native/cache parity, unchanged records/весь main, dispatch/import/MCP argument path и terminal guards | STATIC |

Полные case IDs находятся в литеральных `CASE_METHODS` и
`PARENT_STATIC_CASE_METHODS` нового модуля и в AUTHOR_RESULT. Старые tests,
assertions, gold и historical rosters не редактируются. Для сравнений AST
используются candidate и baseline, разобранные одним parser, а не устаревшие
межверсионные `ast.dump` hashes donor.

ReadObserver — authored finite query/parameter oracle, **не SQL engine**.
Исполняемый после отдельного допуска suffix начинается после connect/schema/fence
creation и заканчивается `ProposalStop` перед разрешением disclosure. Настоящие
локальные source/connector ACL и sanitizers работают на synthetic rows/settings;
это не genuine provider initialization или реальная авторизация профиля.
Deny-only case не подменяет genuine `DisclosureFence` разрешающим mock.
STATIC assertions не исполняют public handler, MCP server или terminal commit.

## Непроверенные границы

В этой фазе допускаются только чтение исходников, inert AST/JSON/bytes и локальная
Git фиксация. Product/test imports, compile/exec owning code, collection,
`build_suite`, SQL, SDK/native/model/network/CI — **NOT_RUN**, allowance 0.
Предыдущие SOURCE/native допуски и отказы не переоткрываются.

Отдельно остаются: независимое sole review родителя; применимый execution packet
после нового допуска и resource admission; настоящий R1→R2 ingest/retirement,
конкурентность, публичная SQL/native выдача, genuine SDK/lifecycle/ACL/terminal
composition, FULL/CI, publication/install/loaded identity и приёмка задачи.
Старые whole-main/cache/census/inverse/inventory oracles требуют отдельного
решения владельца; новый CODE-кандидат не переписывает их под себя. Этот документ
не закрывает parent task, operational health или resource HOLD.
