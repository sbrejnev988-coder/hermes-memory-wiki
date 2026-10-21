# Ограниченные Excel-формулы для извлечения документов

`spreadsheet_formulas.py` — независимый чистый stdlib helper. Это **не весь Excel**, не средство открытия XLSX и не замена LibreOffice. В extraction identity **3.1.7** настоящий `document_extractors.extract_xlsx` подключает этот helper без изменения его утверждённых bytes. Контракт OOXML → один bounded `evaluate_cells` → санитизированные units описан ниже; outcomes correction находятся в отдельном RESULT, не выводятся из исторического helper PASS.

## API v1

```python
from spreadsheet_formulas import evaluate_cells

result = evaluate_cells(
    {
        "Итог": {"A1": {"value": "999", "formula": "SUM('Данные'!A1:A2)", "type": "n"}},
        "Данные": {
            "A1": {"value": "2", "formula": "", "type": "n"},
            "A2": {"value": "3", "formula": "", "type": "n"},
        },
    },
    max_cells=100000,
    max_range_cells=100000,
    max_operations=250000,
    max_depth=64,
)
# result["Итог"]["A1"]:
# value=5.0, status="computed", value_origin="evaluated", cached_value=999.0
```

Вход — mapping точное имя листа → mapping точная A1-координата → **plain dict** с `value`, `formula`, `type`. Значение — plain `str|int|float|bool|None`; `formula` и `type` — plain строки. Дополнительные поля входной записи не копируются и не исполняются. Поддержаны обычные mapping-контейнеры, в том числе `UserDict`; это API для данных доверенного caller, **не sandbox для Python-объектов с враждебными методами**.

Helper создаёт новые mappings/records, ничего не меняет во входе, не читает и не переписывает original workbook. Имена листов, координаты, `formula` и `type` в выходе сохраняются буквально. Входная строка формулы может начинаться с `=` или не иметь его. Пробелы внутри/после формулы допустимы; `=` после ведущего пробела не переносится в начало автоматически.

### Поля выходной записи

| Поле | Контракт |
|---|---|
| `value` | Типизированный scalar для `literal`/`computed`; `None` для error/refusal. Настоящая blank также `None`, но отличается `value_type`/`status` |
| `value_type` | `number`, `text`, `boolean`, `blank`, `error`, `unknown` |
| `status` | `literal`, `computed`, `error`, `unsupported`, `external_refused`, `cycle`, `resource_limit` |
| `value_origin` | `input` для literal/input error, `evaluated` для computed/formula error, `none` для refusal |
| `reason` | Пустая строка при успехе либо короткий постоянный code, не исходный текст и не exception message |
| `error` | Excel error code (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NUM!`, `#N/A` и др.) либо `None` |
| `cached_value` | Типизированное входное cached value **только metadata** формульной ячейки; error cache хранит строку error code |
| `cached_value_type` | Тип cache либо `unknown`; не тип вычисленного результата |
| `cache_status` | `not_applicable` без формулы; `absent`, `available`, `invalid` с формулой |
| `formula`, `type` | Буквальные входные строки |

Cached value не считается вычислением и **никогда не используется как fallback**. Наличие даже хорошего cache не превращает неизвестную функцию, external reference, цикл, Excel error или исчерпанный бюджет в success. Плохой cache также не блокирует независимо вычислимую поддержанную формулу. Значения `0`, `False`, empty text и blank различаются, без truthiness-fallback.

Ошибка формы workbook/параметров, невалидный literal cell ID и превышение `max_cells` дают атомарный `ValueError` с постоянным code: частичного молча обрезанного workbook нет. Ошибки формулы и её зависимостей возвращаются в записи, а не маскируются исключением всего документа. Повторная ссылка на отказавшую dependency переносит её тип отказа; `COUNT`/`COUNTA` не превращают unsupported/resource/cycle в число.

## Поддержанное подмножество

- Числа с ASCII digits, точкой и scientific notation, включая `.5`, `2E-3`; строки Excel `"text"`/`"a""b"`; `TRUE`/`FALSE`; перечисленные в модуле Excel error literals.
- `+`, `-`, `*`, `/`, `^`, unary `+/-`, postfix `%`, скобки. Принята Excel-приоритетность: `-2^2 = 4`, `2^3^2 = 64` (power слева направо). `%` можно повторять.
- A1-ссылки с `$`, например `A1`, `$A$1`, `$A1`, `A$1`; forward references и зависимости между формулами.
- Межлистовые ссылки `Data!A1`, `'Raw data'!$A$1`, `'O''Brien'!A1`. Имена листов сопоставляются **точно**, без strip/casefold/Unicode normalization: отсутствующий или иначе написанный лист — `#REF!`. Это сознательно строже обычного Excel.
- Координаты только uppercase ASCII A1 в пределах `A1:XFD1048576`, без leading zero. Lowercase, кириллические двойники, `$` в ключе входного mapping, out-of-grid ID не исправляются. В формулах неподдержанная reference/name syntax получает refusal; невалидные ключи workbook — `ValueError`.
- Прямоугольные диапазоны `A1:B5`, `$A$1:$B$5`, `'Data'!A1:B5`, в том числе обратный порядок границ и одинаковый явный лист у обеих границ. Row-major обход ленивый, без полного списка промежуточных cells. Диапазоны допустимы **только аргументами агрегатов**, не как scalar/dynamic array.
- `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `PRODUCT`, `ABS`. Имена функций case-insensitive, без удаления `_xlfn.`. У `ABS` ровно один аргумент, у агрегатов 0–255.

### Типы и coercion

Поддержаны OOXML `type=""/"n"/"b"/"s"/"str"/"inlineStr"/"e"`. Числовые строки нынешнего `extract_xlsx` (`"42"`) и rendered boolean (`"TRUE"`, `"FALSE"`) принимаются без отдельной библиотеки. Строковые типы сохраняют текст: shared string `"00123"` не становится числом. `None` — blank; `""` без text type — blank, с text type — empty text. Date serial с числовым типом остаётся числом; стили/форматы/эпоха дат не интерпретируются. `type="d"` и неизвестные типы — явный `unsupported`.

Числа считаются finite binary64; nonfinite/overflow/domain error дают `#NUM!`, деление на ноль — `#DIV/0!`. `0^0` → `#NUM!`, отрицательная степень нуля → `#DIV/0!`. Giant integer exponentiation/complex arithmetic нет; используется `math.pow` над doubles. Это не обещание полного Excel rounding/precision compatibility: отображение, форматирование, 15-digit input rules, Excel underflow/суммирование и floating-point нюансы не эмулируются. Underflow Python может дать finite zero.

В арифметике blank → 0, boolean → 1/0, numeric text → число; другой текст → `#VALUE!`. Прямая формула `=A1` для blank/missing cell существующего листа даёт numeric zero; прямой empty text остаётся empty text. `TRUE`/`FALSE`, возвращённые ссылкой, сохраняют boolean type до арифметического coercion.

Агрегаты различают direct argument и reference/range: числовой текст/boolean в **ссылках** игнорируется numeric aggregates, в **прямых аргументах** переводится в числа. `COUNT` игнорирует Excel errors (и referenced, и direct literal/expression) и nonnumeric text. Это не разрешает проглатывать `unsupported/cycle/resource_limit/external_refused`. `COUNTA` считает всё кроме blank, в том числе empty text/Excel errors. Остальные агрегаты передают Excel errors. `SUM/COUNT/COUNTA/MIN/MAX/PRODUCT` без чисел возвращают 0, `AVERAGE` — `#DIV/0!`. Эти правила объявлены явно; не заявляется полная совместимость со всеми историческими версиями Excel.

## Refusal и ограничения

Не поддержаны IF/условные/lookup/date/financial/volatile функции, ROUND, named ranges, таблицы/structured refs, whole-row/whole-column ranges, union/intersection, 3D refs, dynamic/spill/array formulas, implicit intersection `@`, comparison/concatenation, localized names/decimal comma/`;` separator, shared-formula translation, VBA/macros/UDF/XLM/RTD/DDE, indirect evaluation. Неизвестная функция/синтаксис не исполняется и не заменяется кешированным ответом.

External workbook/path/URL/DDE syntax отказывается без открытия target. `[]`, `\\`, `|` вне double-quoted text и `[]:/\\|` в quoted sheet token отказываются консервативно как `external_refused` (включая structured/3D ambiguity). `WEBSERVICE`, `HYPERLINK`, `INDIRECT`, `EXEC`, `CALL`, `RTD` не входят в allowlist. URL/похожая на формулу последовательность внутри double-quoted text — **инертный текст**, не адрес для fetch. Никаких `eval/exec`, macro engine, subprocess, network, filesystem или изменения процесса/окружения внутри evaluator нет. Собственный tokenizer/parser не является защитой от всех атак на остальной extractor.

Незавершённые диапазоны (`A1:`, `SUM(A1:`) отказываются с `unsupported/invalid_formula`: EOF sentinel не потребляется как operand/reference и остаётся доступен lookahead. Не-ASCII digits после точки (`.١`, `.²`) не попадают в ASCII numeric lexer и дают `unsupported/operator_or_syntax_unsupported`, без Unicode normalization. Это отказ отдельной формульной ячейки, не исключение всего workbook; следующая здоровая ячейка продолжает вычисляться в том же общем бюджете. Unicode внутри text/sheet tokens остаётся допустимым инертным содержимым. Cache в обоих случаях — только metadata.

| Ограничение | Default и hard maximum | Учёт |
|---|---:|---|
| `max_cells` | 100000 | Все явно переданные cells всех листов до вычисления; превышение атомарно отклоняется |
| `max_range_cells` | 100000 | Площадь каждого прямоугольника **вместе с отсутствующими cells**, до обхода |
| `max_operations` | 250000 | Один общий бюджет на вызов: cell resolutions (и memo hits), lexer tokens, AST visits, range/aggregate steps; не reset на лист/формулу |
| `max_depth` | 64 | Parser nesting и evaluation expression/reference nesting; expression nodes и cross-cell hops потребляют глубину, не только число ссылок |
| Formula length | 8192 characters | До tokenizer |
| Lexer tokens | 4096 на формулу | До AST evaluation |
| Aggregate args | 255 | До evaluation |
| Text value | 32767 characters | Literal/cache normalization |
| Листы | 10000 | До обхода cells; имя — непустая plain строка ≤1024 characters |

Параметры можно уменьшать, но не повышать hard maxima; только plain positive integer, не bool/string/float. `max_operations` идёт в порядке входных mappings; reorder при малом бюджете может изменить набор вычисленных формул. Уже исчерпанный бюджет не мешает сохранению literal cells. Depth refusal не кешируется как постоянное свойство dependency: суффикс длинной цепочки может независимо вычислиться от короткого root. Цикл и зависящие от него формулы имеют `status="cycle"`; unrelated здоровые формулы продолжают вычисляться в оставшемся бюджете.

Память/CPU ограничены размером workbook, длиной формулы, количеством tokens/operations и depth; это не OS CPU/RSS/deadline sandbox. Исходная `formula` в record сохраняется буквально даже при длине >8192, поэтому **её нельзя напрямую выводить пользователю/модели без штатного sanitizer/renderer bound**. Cache также недоверенный document content. Входной API не знает о shared/array OOXML attributes и о наличии/отсутствии XML `<v>`: parser должен отдельно помечать/не передавать неподдержанную shared/array semantics как обычную формулу. Empty `str` cache нельзя отличить от отсутствующего `<v>`, если caller уже потерял этот факт.

## Проверка и передача

`tests/test_spreadsheet_formulas_bounded.py` содержит positive/inverse/regression unittest cases, в том числе literal fidelity, mixed types, coercion, dependency graph, cross-sheet identity, cached/computed/error distinctions, cycle/resource/external refusal и static no-eval/import controls. Сам тест загружает **весь** hash-bound `spreadsheet_formulas.py`; Python compile/exec используется только trusted SOURCE loader теста, никогда для Excel formula text.

Correction01 добавляет к неизменным прежним cases связанные EOF-range/Unicode-numeric controls, проверку следующей здоровой ячейки и dependent refusals без cached fallback, positives для `.5`/scientific notation, законных ranges и Unicode text/sheet IDs. Единственный новый SOURCE packet и exact candidate bindings сохраняются в `xlsx/correction01/evidence/RESULT.json` с отдельными original outer return и raw captures; прежние два overlapping SOURCE36 packet не изменяются и не складываются в свежий denominator.

Допустимый packet — existing `devtools.harness.run_source`, Python `-I -B -S`, synthetic lane-owned home/temp, stdout CASES_SCHEMA и отдельные raw logs. Тонкий path-only invoker в `xlsx/evidence` нужен, поскольку фиксированные default output/scratch roots контроллера не являются roots этой lane; guard/runner/stdlib-only policy не меняются. Полный roster, exact source hashes, actual child/controller exits, capture/ownership и candidate commit/tree — в `xlsx/evidence/RESULT.json` и указанных там captures.

Исторический SOURCE PASS helper доказывает synthetic in-memory workbook, **не** новый OOXML consumer. Byte-exact helper и его43 standalone tests поставляются с кандидатом; unchanged43 не исполняются вновь для увеличения fresh denominator. Native/loaded/fleet/release и финальная combined-tree проверка остаются отдельными gates родителя.

## OOXML consumer (extraction identity 3.1.8)

- Входные числовые/boolean/shared/inline/error значения читаются без output-redaction/обрезания перед вычислением. Явная blank, число0, FALSE и empty text различаются. Одно вычисление получает **все** допущенные листы и ячейки, включая forward/cross-sheet dependencies; `max_units` ограничивает только выдачу. Прежний `cell.value` остаётся строкой (`"6"`, не `6.0`); `value_type`, `status`, `value_origin`, `reason`/`error` сохраняют тип/происхождение. Literal blank — `value=null,value_type=blank`, empty text — `value="",value_type=text`.
- Cache формулы остаётся исключительно metadata: `cached_value` — строковое представление typed cache, `cached_value_type` — его тип, `cache_status` — `available/absent/invalid`; `cached_raw_value` сохраняет отдельно rendered исходник. `value_present` и `cached_present` фиксируют XML `<v>` независимо от truthiness. Поэтому отсутствующий `<v>`, `<v/>`, cache0/FALSE и empty `str` различимы. Stale/invalid cache не подменяет результат и не блокирует отдельно вычислимую формулу.
- `<f>` учитывается по **наличию**, а не по непустому тексту. `formula_present` и `formula_attributes` сохраняют форму XML. Shared (включая empty follower), array, dataTable, formula region/неизвестные attributes и cell metadata `cm/vm` явно `unsupported`. Empty normal `<f/>` — отказ, не literal. Заданные `ref`-регионы блокируют также отсутствующих followers; виртуальные blockers не выдаются как прочитанные cells. Бounded expansion считает повторное покрытие тоже. Невалидный/слишком большой region лишает workbook допуска к вычислению. Нет shared translation, spill/dynamic array или full Excel promise.
- Исходные sheet names/cell IDs передаются буквально: без strip, casefold, Unicode normalization, исправления lowercase/leading zero. Duplicate names/relationships/rows/cells/ZIP members, invalid/out-of-grid coordinates и row-coordinate mismatch дают явный `ValueError` до молчаливого overwrite. Worksheet-only legacy архив поддержан только при отсутствии **обоих** workbook metadata parts; повреждённый declared workbook не заменяется positional fallback.
- Existing ZIP/source/member/read caps и public max_cells не повышены. Если `max_cells`, unreadable/missing declared worksheet/shared strings, region expansion или helper hard cell/sheet maxima не дают полный workbook, **ни одна формула не вычисляется**, даже constant. `incomplete_workbook`, `value=null,value_origin=none`; cache — `unvalidated`, не fallback. Доступные literals сохраняются с `value_type=unknown,value_origin=input_unvalidated`, не выдаются за typed evaluation. Непрочитанная dependency не становится blank0. Helper не дробится на вызовы с новым operation budget.
- `metadata.coverage` отделяет declared/read sheets, collected/evaluator-input/output cells, complete input, attempted evaluation, output truncation, статусы всех collected cells и причины отказа. `partial/empty` не полный success. Публичные caps strings/metadata/row text/edge output также отражаются как truncation. Формульные `formula_ref` edges сохраняют прежний predicate и exact benign anchors; это только lexical endpoints вычисленных поддержанных выражений, **не полный dependency DAG**. Quoted text не создаёт edges, inherited sheet у правой границы range сохраняется; edge limits/сокращённое evidence отражаются в coverage.
- Formula/cache/computed text, XML attributes, identifiers/edges и metadata — недоверенные document data. Реальные `sanitize_table_cells`, `clean_text` и `sanitize_json` выполняются до возврата объекта, поэтому защищены **и полный `asdict`, и `to_dict`**. Header columns сопоставлены по координатам (включая sparse rows); контекстные literal masks применяются ко всем output views/edges. У helper нет taint API: при наличии защищённого table context consumer консервативно редактирует **все formula values/caches workbook**, не заявляя безопасность преобразованных секретов лишь из equality-mask. Это обозначено `formula_context_redaction=workbook_conservative` и `cell.context_redacted`; вычисленный статус/тип остаётся настоящим, displayed secret — `<REDACTED>`. Это может скрыть независимый безопасный formula result; literal non-secret данные сохраняются. Общая secret policy3.0.0 не изменена.

Исторический connected target `tests/test_document_parser_xlsx_formulas.py` включает original72 через прежние suites/setup/cleanup/reporter и real-ZIP cohort, а не ручные calls/skip или unchanged43. Единственный lowered-operation control вызывает настоящий helper один раз с меньшим бюджетом и проверяет отсутствие reset между листами. SOURCE imports явно связывают exact shipped helper **до** shared extractor consumer; ambient package не используется. Frozen `integration/xlsx-formulas01/evidence/RESULT.json` сохраняет исходный FAIL81 и отрицательное review; он не переписывается исправлением.

### Correction: literal identity, privacy/schema и независимые scalar/cache отказы

`tests/test_document_parser_xlsx_output_privacy.py` переиспользует весь original81 и прежний reporter под инертным module name. Только десять current-version literals пяти прежних файлов переходят3.1.6→3.1.7; все остальные assertions, setup, helpers, IDs и legitimate132/133–137 сохранены. Additive cohort добавляет inverse3.1.6; прежние3.1.4/5 остаются. Helper и его43 теста byte-exact, без нового запуска.

- Буквальные bounded sheet IDs сохраняются в raw `asdict`, direct `Unit.to_dict`, `ExtractedDocument.to_dict`, metadata/locators/titles/anchors/edges. Узкий serializer hook допускает только проверенную structural key/value пару; arbitrary keys не исключены из sanitizer. ID проверяется тем же secret detector, а control/format characters, пустота и превышение1024 скрывают весь ID. Пробелы/Unicode/apostrophe не strip/casefold/normalize; обычные non-XLSX serializers и generic sanitizers прежние.
- В protected workbook context скрываются **все formula sources, attribute keys/values, rendered rows и edge evidence**, а не только value/cache. Поэтому Excel doubled quotes и transformed numeric/string результаты не требуют ложного substring-taint proof. `formula_attributes={}` означает withheld representation при `context_redacted=true`; реальные status/type/provenance и references сохраняют честную семантику. Без context обычные formula/cache/attributes видимы после generic redaction. Context masks применяются лишь к document-owned slots, не к producer keys/finite enums/counters: protected слово `value` не отменяет публичный schema key `value`.
- Наличие XML `<v>` независимо от его валидности. У normal formula тип`s` с отсутствующим cache даёт `absent`, с пустым/невалидным/out-of-range shared index — `invalid`, с корректным — `available`; ни один плохой cache не блокирует независимую формулу и не становится вычислением. Невалидная shared-string **literal** и её dependencies остаются unsupported, не blank0.
- `<f>`/`<v>` допускаются как полное simple content: nested child/mixed content не склеивается и не вычисляется по `.text` prefix. Повреждённый f — отказ с dependent refusal; повреждённый v/его attributes — invalid cache, independent formula сохраняется. Повреждённый literal v отказывается. Harmless indentation за пределами scalar node не является суффиксом формулы; empty/zero/FALSE distinctions прежние.

Единственный разрешённый SOURCE packet, frozen commit/tree, actual counts/child/controller/original-outer returns, raw captures и guards: `parallel/foundation-documents-20261019/corrections/xlsx-output-privacy01/evidence/RESULT.json`. Этот текст не предвосхищает результат. Независимое delta-review, parent acceptance/integration и genuine engines/SDK/SQL/native/FULL/install/restart отдельно; SOURCE audit не OS sandbox.

### Protected-slot admission и настоящие redaction findings (3.1.8)

Защищённость присутствующей ячейки определяется прежней header/adjacent-label политикой **до и независимо от наличия raw/cache/computed value**. Refused, cyclic и incomplete formula без результата всё ещё содержит source/attributes: такие представления и rendered row удерживаются при `workbook_conservative`, а отказ/status/type/provenance не превращаются в computed. Обычный отказ без secret-label context сам по себе не скрывает безопасную формулу.

Контекстные masks получают только значения действительно защищённых slots либо настоящие detector findings. Обычный `clean_text` display trim/truncation без secret finding не является admission секрета: несекретное значение, буквально совпавшее с spaced Unicode sheet ID, больше не меняет structural ID до literal gate. Genuine protected value, совпадающее с ID, по-прежнему маскирует этот ID; generic normalizers/secret policy и typed schema gates не ослаблены.

В прежний finished cohort добавлены только два finite composition cases: sole no-cache refused header/adjacent slots вместе с cycle/incomplete/healthy inverses; display-only trim с literal IDs/anchors/edges и genuine-secret inverse. Все original88 bodies/setup/helpers/reporter сохранены, кроме одиннадцати current-version literals шести файлов3.1.7→3.1.8; новый fingerprint inverse3.1.7 дополняет прежние. Helper43 не перезапускается. Точный frozen candidate и фактический единственный SOURCE результат — `parallel/foundation-documents-20261019/corrections/xlsx-taint-admission01/evidence/RESULT.json`; результаты здесь заранее не утверждаются. Прежние FAIL81, PASS88 и отрицательные reviews неизменны. Квалификация остаётся SOURCE, не native/FULL/installed/runtime acceptance.


## Cumulative parser/XLSX SOURCE на common9f68 — только static

В этой отдельной композиции переносится полный parser/XLSX source subset из
frozen `f31176f2c4233b0f8fa185106351257ded8e1027` на CI/Luna/filesystem common
`9f68d726471b25f1606482add03460887093e289`. Это три runtime модуля, их полная
поставляемая test/helper цепочка, fixture compatibility `test_p2_g3_native.py`
и два документа; не весь upstream491, не document owner/public schema/job/history
композиция. Старые SOURCE receipts и их PASS/FAIL/UNKNOWN остаются историческими,
новых тестовых, import/collection, native/SQL/SDK/engine/model/network запусков0.
Текущие __init__, document_knowledge_graph filesystem guards, Luna и CI15 неизменны;
CI-O02 literal/digest и все gold сохранены. Sparse physical source — не runtime
snapshot. До нового independent cumulative review этот source subset не принят;
source review не даёт native/FULL/installed/loaded/Vision/indexing proof или grant.
Точный candidate/tree/static proof хранятся в этой lane evidence/RESULT.json;
новый parser runtime, PDF/OCR engines и XLSX end-to-end остаются NOT_RUN.

## Parser16 static correction: helper closure ≠ pipeline qualification

Correction lane `parallel/foundation-documents-20261019/corrections/parser16-review-fix01`
от `5047b80bbe97e55fa2a5f6c88c8cf49bd10cad40` готовит связанный OCR lifecycle
и test-loader fix, **не новый evaluator/OOXML feature**. `spreadsheet_formulas.py`
с SHA256 `c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac`
и все его прежние43 tests unchanged и заново не исполнялись. Здоровый content,
`EXTRACTOR_VERSION=3.1.8`, secret policy3.0.0, cache/content versions,
санитизаторы, literal serializer hooks и все XLSX/fingerprint APIs сохранены.

SRC-LOAD-03 исправляется в существующих `test_document_parser_pdf_ocr.py`
и `test_document_parser_components.py`: обязательный exact shipped helper
читается через `DEVTOOLS_INPUTS`/`devtools_read_bound` либо sibling path,
SHA-проверяется и исполняется перед extractor, без ambient `sys.path`.
Для здорового заранее связанного outer XLSX helper сохраняется module identity,
но namespace инициализируется pinned source, не чужими globals. Wrong-helper
SHA/read refusal не преобразуются в optional-engine skip. Component opt-in,
own TMPDIR и настоящие engine prerequisites остаются прежними. Static source
closure не равен cold import, pytest collection или genuine component proof.
Prepared wrong-helper/read-refusal/healthy identity controls находятся в
существующем `ReviewBoundarySourceTests`; они **NOT_RUN**.

SRC-OCR-01/02 исправляются только внутри существующего `_run_ocr_command`:
pre-acquire Python state и owning try с `process=None`; отдельные cleanup
attempts; точный body fatal, иначе первый наблюдённый reader/cleanup fatal
вместо ordinary failed-document; private causal ledger/explicit causes;
retained UNKNOWN/no replacement. Ordinary healthy/read failure политика
сохранена. Подробные приоритеты, private context projection и direct-child
ограничения описаны в `DOCUMENT_PARSERS_RU.md#parser16-correction-на-5047-подготовленный-source-execution0`.
Нет нового supervisor или atomic async/constructor/native/descendant/tree/OS/
peak-bound proof; PDF owner class вне OCR функции не менялась.

### SRC-CALLER-04 — открытый documents-owner contract

Прежние literal-ID утверждения выше относятся к **extractor output views**,
а не автоматически к `document_knowledge_graph.py` persistence/cache/read.
В baseline d93 этот тогда unchanged owner импортирует generic `sanitize_json` как
`_sanitize_extracted_json`. `ingest_document` повторно sanitizes extraction
payload перед cache, `_safe_json` — stored metadata/locators; cache eligibility
`_cached_extraction_payload` проверяет generic sanitized representation;
`_decode_json` делает её снова на `document_source`/`document_unit_context`.
Точный generic путь `clean_text` → `redact_secret_text` использует построчный
`line.rstrip()`, а не `.strip()`: он может убрать literal trailing spaces scalar
benign sheet ID, несмотря на узкий structural hook extractor serializers.
Удаление leading spaces на этом пути не доказано; они нужны как отдельный control.
Следовательно, `"Data"` и `"Data "` могут потерять различимость на этих слоях;
full exact identity units/anchors/locators/edges и fresh-v-cache fidelity здесь
**NOT_QUALIFIED**, не SQL/runtime reproduced loss и не принятый pipeline PASS.

Исправление требует отдельного documents-owner задания: typed bounded benign
structural key/value pairs должны переживать persistence/cache/read вместе с
прежними общими privacy guards. Нужны same-ID positive, whitespace-distinct
inverse (включая trailing space), Unicode/apostrophe и anchor/edge identity,
real round-trip и fresh-v-cache equality. Не разрешается blanket bypass generic
sanitizer либо расширение этой correction на 17-й файл. Cache version bump не
заменяет identity fix; для текущего content-preserving OCR cleanup он не нужен.

Original full SOURCE review `integration/parsers-common01/review/REVIEW.json`
(`passed=false`, SHA256 `cb32609032f85b263269f6fea180c3318a162b8830f128f2cd0d6a87657f60ad`)
и parent HOLD сохранены, прежние PASS/FAIL/UNKNOWN не переписываются. Изменённый
loader/shared seam инвалидирует перенос затронутых исторических PASS на новые
bytes. Выполнены только Git/raw/AST/syntax-compilation checks без exec; новых
SOURCE/test/script/import/collection/native/SQL/SDK/PDF/OCR/engine/model/network/
Vision/index/CI/install/restart calls0. `metadata_preflight()` не вызывался.
Sparse physical6 — не полный runtime snapshot. Exact frozen source/tree,
неизменные491 mode/blob, шесть raw hashes, prepared roster и actual metadata
returns хранятся в `corrections/parser16-review-fix01/evidence/RESULT.json`.
Independent delta-review, parent acceptance/integration и whole-goal
native/FULL/installed/loaded остаются отдельными, здесь не выполнены.

### Literal-owner correction: documentKG, не evaluator

Производная `parser16-literal-owner01` добавляет typed bounded structural channel
в настоящий documentKG cache/persistence/read. Схема extractor
`xlsx_identity_context`/`xlsx_identity_fields` проверяет producer metadata/coverage,
точные уникальные benign sheet names (nonblank, до1024 символов, до10000 листов),
sheet index/title и согласованные row/cell anchor/locator/parent/grid. Parser
label, произвольный `sheet` key или policy marker сами по себе не authority.
Нет strip/casefold/Unicode normalization; generic sanitizer/secret detector и
обычные text/formulas/keys/non-XLSX defaults не изменены. Invalid/control/secret/
overcap/allblank/injection identity не получает literal exemption; withheld
состояние не объявляется exact success. Formula helper/evaluator API и версии
остаются прежними, включая pinned helper и оба предыдущих corrected loaders.

`_document_extraction_payload` связывает typed extraction cache capture с actual
XLSX writes. Source `metadata.sheets`, unit locators/sheet titles и structural
anchors/edges проходят `_safe_json`, typed `_decode_json`, общую hydration в
`_load_candidate`/`document_unit_context` и source read. Unit cell metadata и
evidence/formulas по-прежнему проходят generic redaction, не structural bypass.
Связанный guard channel не снимает privacy table context и existing caps.
Raw leaf возвращается только поверх whitespace-only generic normalization,
никогда поверх secret redaction, включая совпадение в composed anchor framing.

XLSX-only representation policy `xlsx-literal-structure-v1` включена в extraction
fingerprint до revision/early reuse. Cache eligibility проверяет typed current
shape и исходные hash/file/parser условия; после legacy/malformed cache miss
обе same-revision early ветви дополнительно закрыты. Lossy legacy materialization
не сохраняется через scan mtime/size shortcut: XLSX всегда проходит canonical
ingest/cache admission, non-XLSX stat optimization не менялась. Materialization
может быть заменена только обычным разрешённым чтением source, не восстановлением
по похожему label. Legacy reads помечаются `legacy_or_withheld`; policy bump
дополняет реальный identity fix, не заменяет его. Non-XLSX fingerprints прежние.

`bounded_benign_fields_only` относится к представлению до read guards. Настоящие
provider inspection, ACL/owner/connector и disclosure finish остаются обязательны.
`_clean` не strip; `guard.py` сохраняет nonblank benign spaces, allblank/injection
может withhold, private inspector может transform/veto. Ни один raw ID не
восстанавливается поверх этих решений, и exact final fidelity при отказе не
обещается. Дополнительный allblank/unsafe case не разрешает общий sanitizer bypass.

`tests/test_document_xlsx_identity_source.py` — только prepared definitions:
SOURCE positive/inverse/healthy/privacy/legacy controls плюс отдельная future
own-SQLite composition. Ordinary pytest исключён module/class `__test__=False`;
actual nonselection NOT_RUN, product load только в future admitted setup.
SQLite/public/SDK/worker proof не выводится из STATIC assertions или SOURCE
helper equality; standalone SQLite definitions не подделывают read-fence authority.
Execution0: test bodies/import/exec/collection/metadata_preflight/native/SQL/
engine/network/model/CI/install/restart не выполнялись. Code checkpoint и inert
AST/compile/Git checks — не acceptance. RESULT с exact pins/roster/remaining gates:
`corrections/parser16-literal-owner01/evidence/RESULT.json`.
