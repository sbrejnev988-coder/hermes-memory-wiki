# Документные parsers: PDF/OCR и bounded XLSX (3.1.7)

## Изменение поведения

- PDF сначала читает native text. Для пустой/повреждённой/слишком короткой текстовой выдачи PyMuPDF пробует установленный pypdf **до OCR**. При исключении/отсутствии/пустой выдаче основного reader существует следующий native reader; пустая выдача больше не является `ok`. Зашифрованный PDF без пустого пароля возвращает `encrypted`, а не запускает внешний обход.
- PyMuPDF выдаёт контейнер страницы, `text_block`, контейнер `table` и `table_row`. В `row.metadata.cells` находятся отдельные cell anchor и locator (`page/table/row/column/bbox`). Контейнеры не дублируют тело страницы/таблицы. Блоки целиком внутри успешно представленной таблицы не дублируют её строки. Секреты в таблице редактируются по контексту колонок, в том числе в перекрывающихся блоках.
- Bbox берётся только из настоящего результата PyMuPDF. `coordinate_system=pymupdf_unrotated_top_left_points`; номер страницы, таблицы/строки/колонки — с 1, номер native block — исходный номер parser (может быть 0). Для дополнения OCR исходные block IDs сохранены в отдельном namespace `ocr-block`. Пропущенная геометрия ячейки не превращается в придуманную merged-cell геометрию.
- `pdf_reading_order=layout` — **геометрическая эвристика `(y1,x0)`**, соответствующая `get_text('blocks',sort=True)` проверенного исходника. Это не обещание правильного многоколоночного/RTL/семантического порядка. `source` сохраняет порядок блоков parser внутри block-группы; таблицы выдаются первыми, затем блоки, с точным label `parser_tables_then_blocks`. У разных API нет общего доказанного source-order.
- pypdf/Tika не получают выдуманные bbox или таблицы. pypdf — page-text-only fallback. Tika используется только по прежнему явному loopback opt-in, после native readers, и помечает `coverage_known=false`, `partial` при непустом теле.

## OCR и частичность

Для каждой осмотренной PDF-страницы сохраняются `page`, `origin`, `native_characters`, `quality`, OCR requested/attempted/status/engine/language, причина отказа и структурная диагностика. Низкокачественный/пустой OCR не заменяет пригодный native text. Если полностраничное распознавание потеряло native text, он сохраняется, а OCR добавляется как дополнение (`mixed`).

`quality` — проверяемая эвристика здоровья текста: число символов/букв и цифр, доля replacement/control characters. Это **не точность распознавания**. PyMuPDF TextPage не отдаёт confidence — сохраняется `null`, не выдуманный процент. Native-страница с достаточным текстом не запускает OCR; это не доказательство распознавания всех картинок/областей страницы.

Сводка `metadata.coverage` различает total/examined/usable/missing/omitted pages, native/OCR pages и truncation. Пустая средняя страница не исчезает из массива диагностики. `ok` означает пригодный текст на всех осмотренных страницах без известных пропусков/лимитов; `partial` сохраняет пригодную часть с явным недопокрытием; `empty` не выдаёт пустой успех; `failed`/`unsupported`/`encrypted` различаются. Сводка помечена как page-text-health, **не исчерпывающее image-region coverage**. При недоступном reader число страниц неизвестно (`coverage_known=false`).

Для изображений настоящий Tesseract запускается с конфигурацией `tsv`. Stdlib-декодер читает реальные поля TSV (page level 1, word level 5), сохраняет по каждой странице engine/language/mean word confidence/качество/partial. Bbox страницы — в пикселях (`image_top_left_pixels`), не PDF points. Confidence — score движка, не калиброванная вероятность; score ниже 20 и пустой/повреждённый текст не принимаются как распознанный контент. Total image pages без отдельного API не считается известным.

## Проверенный API, без установки зависимостей

В facts-selected Python 3.14.7 установлены только pip/README, а PyMuPDF/pypdf/pdfplumber/Tesseract отсутствуют. В текущем PM venv также не найдено этих parser distributions; `tesseract` не найден на PATH. Окружения не изменялись, модели/языковые данные не скачивались.

Проверены **исходники**, а не установленный native runtime:

- [PyMuPDF 1.24.14 utils.py](https://raw.githubusercontent.com/pymupdf/PyMuPDF/1.24.14/src/utils.py): `get_text('blocks',...,textpage=...,sort=...)`, tuple `(x0,y0,x1,y1,text,block_no,block_type)`, сортировка `(y1,x0)`, `get_textpage_ocr(language,dpi,full,tessdata)`.
- [PyMuPDF 1.24.14 table.py](https://raw.githubusercontent.com/pymupdf/PyMuPDF/1.24.14/src/table.py): `page.find_tables(strategy=...)`, `finder.tables`, `table.bbox`, `table.rows`, `row.bbox`, `row.cells`, `table.extract()`. `None` в cell geometry допустим. В этой версии table extraction использует общие CHARS/EDGES: результат копируется до следующего `find_tables`.
- [PyMuPDF 1.24.14 __init__.py](https://raw.githubusercontent.com/pymupdf/PyMuPDF/1.24.14/src/__init__.py): native block types/tuple, Document close. У TextPage не выдумывается публичный `close()`.
- [pypdf 5.1.0 _page.py](https://raw.githubusercontent.com/py-pdf/pypdf/5.1.0/pypdf/_page.py) и [_reader.py](https://raw.githubusercontent.com/py-pdf/pypdf/5.1.0/pypdf/_reader.py): `PdfReader(stream)`, `pages[index].extract_text()`, decrypt/close. Layout/visitor не объявляются точными bbox/table API.
- [Tesseract CLI/TSV](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html): `tesseract input stdout -l LANG --psm N tsv`, TSV page/word fields.

Source receipts и SHA конкретных полученных текстов сохраняются в lane RESULT. Эти версии — проверенный source contract, не заявление о последней версии или успешно загруженной библиотеке. Отсутствующие методы в реально установленной версии диагностируются как unavailable/fallback.

## Эффективные опции и forwarding родителю

`effective_extraction_options` нормализует значения; `extraction_options_fingerprint` учитывает именно нормализованные content-affecting оси. Версия extractor **3.1.8** инвалидирует прежний extraction cache, включая3.1.7/6, после разделения XLSX protected-slot admission, реальных redaction findings и обычного display formatting; прежние inverse3.1.4/5/6 сохраняются. Это не plugin release/schema bump. Общий secret detector/sanitizer не изменён, secret policy осталась 3.0.0. Уже существующие parser caches не считаются проверкой нового кода. Fingerprint и `parser_version` используют эту же версию; миграция пользовательских данных или очистка cache этим изменением не выполняется.

В SOURCE-кандидате `document-public-options01` реализован ранее объявленный owner forwarding: `memory_wiki_document_ingest` и `memory_wiki_document_scan` используют одну локальную content-схему в `MemoryWikiProvider.get_tool_schemas`. `_worker_options` сохраняет прежний ENV-based dict, добавляет только **явно переданные** whitelisted content-ключи и один раз вызывает `effective_extraction_options`. Отсутствующие новые аргументы не меняют старые defaults. Это законченная исходная реализация с подготовленными регрессиями, **PREPARED_STATIC_NOT_EXECUTED**: её отдельный SOURCE packet, независимое review и parent acceptance ещё не выполнены; parser/native/installed/full-product приёмка не заявлена.

| Ключ | Default / допустимые значения |
|---|---|
| `pdf_parser` | `auto`; `pymupdf`, `pypdf` |
| `pdf_mode` | `blocks`; `pages` |
| `pdf_reading_order` | `layout`; `source` |
| `pdf_tables` | `true` |
| `pdf_native_fallback` | `true` |
| `pdf_table_strategy` | `lines`; `lines_strict`, `text` |
| `pdf_max_blocks_per_page` | 2000; 1..20000 |
| `pdf_max_tables_per_page` | 32; 1..1000 |
| `ocr_min_chars` | 8; 1..10000 |
| `ocr_dpi` | 200; 72..400 |
| `ocr_max_pixels` | 20000000; 1000000..100000000 |
| `ocr_max_pages` | 100; 1..10000 |
| `ocr_max_tsv_rows` | 100000; 1..1000000 |
| `ocr_min_native_chars` | 40; 0..10000; при отсутствии — прежний owner ENV |
| `ocr_psm` | строка `3`; строки `0`..`13`; при отсутствии — прежний `MEMORY_WIKI_OCR_PSM` |
| `max_units` | 100000; 1..1000000; только ужесточение owner ceiling |
| `max_cells` | 500000; 1..5000000; только ужесточение owner ceiling |
| `max_pages` | 10000; 1..100000; только ужесточение owner ceiling |
| `max_chars` | 100000000; 1000..500000000; только ужесточение owner ceiling |
| `external_timeout` | 90 s; 1..900; только ужесточение owner ceiling |

Прежние `ocr` (default `false`) и `ocr_language` (default `eng+rus`) доступны в обеих public schemas; отсутствие сохраняет прежние ENV defaults и legacy coercion, включая fallback пустого языка к owner setting. `ocr_language` сохраняет порядок языков, поддерживает `script/Latin` и `eng+rus`; произвольный путь/переводы строк/более 256 символов отвергаются каноническим normalizer. Новые boolean-поля принимают только настоящий `bool`; новые integer-поля — только настоящий `int`, не `bool`, строку или float. Enum/PSM принимают строки из таблицы. Числовые bounds по-прежнему нормализуются каноническим extractor (clamp), а не вторым parser implementation в owner.

Для `max_units`, `max_cells`, `max_pages`, `max_chars`, `external_timeout` сначала применяется `min(request, прежний owner ENV ceiling)`, затем canonical bounds. Это не позволяет поднять `MEMORY_WIKI_DOCUMENT_MAX_UNITS/MAX_CELLS/MAX_PAGES/MAX_CHARS/EXTERNAL_TIMEOUT`; при отсутствии запроса сохраняются прежние ENV readers, ranges и defaults. Публичные значения defaults описывают неконфигурированного owner, а не отменяют его более строгую настройку. Новые ENV aliases не вводятся. Outer file/snapshot/supervisor limits и SQL/ACL/owner admission не меняются.

`tesseract_bin` остаётся trusted-ENV-only через `MEMORY_WIKI_TESSERACT_BIN` с прежним fallback `tesseract`, `tika_url` — через прежний owner-local `MEMORY_WIKI_TIKA_URL`. `max_bytes`, ZIP policies, worker/process/security/SDK/billing/model controls не добавлены в public схемы и не пробрасываются из request в extraction options. Это не новый executable/network selector и не новый допуск на OCR, rendering или внешний endpoint.

Один и тот же effective dict из canonical ingest идёт в `extraction_options_fingerprint(path, options)` и в `_extract(..., {**args, "_effective_extraction_options": options})`; `_extract` передаёт именно его worker. Сохраняется каноническая идемпотентность normalizer внутри downstream consumers. Для изображений fingerprint включает PSM/executable/TSV rows, для PDF — backend/structure/table/bounds. `ocr_min_native_chars` входит в PDF fingerprint **также при `ocr=false`**, поскольку управляет native-reader fallback; прочие OCR-оси учитываются только при `ocr=true`. Deadline/chunking/embedding route в extraction fingerprint не входят: изменение timeout меняет effective dict, но не content fingerprint. Обновление auto-discovered внешней библиотеки требует отдельной cache/version политики; actual library version записывается в PDF metadata, native dependency upgrade этим SOURCE packet не квалифицирован.

Scan при наличии **любого** явного content-ключа из таблицы либо `ocr`/`ocr_language` отказывается от `stat_fast_path`, даже для `false`, `0` или значения по умолчанию. Равные mtime/size не доказывают равенство extraction settings: кандидат проходит прежний canonical ingest с теми же scope/path/owner guards; его cache уже проверяет content fingerprint. Прежний отдельный XLSX fast-path veto сохранён. При отсутствии content-аргументов прежний opt-in/ENV stat fast-path остаётся; SQL и scanner lifecycle не переписаны. Prepared регрессия проверяет scan/caller wiring **STATIC**, не выполняет SQL или public provider dispatch.

Будущий один SOURCE packet — `tests/test_document_public_options_source.py`: инертная collection, class `__test__ = False`, существующие bound peer loader и harness/bootstrap, только собственный scratch. Pure-schema callable берётся из exact owning-method carrier с полным originating Git blob/span/AST mapping: весь `__init__.py` больше 1 MB binder и не импортируется как native provider/SDK. Наличие подготовленных тестов и inert compile не является их PASS.

`partial` может содержать реальные units. В baseline docgraph `content_indexed` равно true только при `extractor_status=='ok'`, а cache принимает только `ok`. Родителю нужно сохранить это различие и явную partial диагностику; не превращать `partial` в полный успех. Показ локальных пригодных units и решение об embedding частичного документа — отдельный контракт pipeline, а не разрешение этой parser lane.

В3.1.7 `extract_xlsx` использует byte-exact approved `spreadsheet_formulas.evaluate_cells`: полный допущенный workbook → один shared bounded budget → безопасные row units. `max_units` не отсекает dependencies; неполный input удерживает все вычисления, cache никогда не fallback. Исправлены literal IDs после обоих serializers, защита encoded/transformed formula copies и attributes/evidence, отделение document masks от owned schema, независимость invalid/absent shared cache и полное scalar admission f/v без prefix computation. Подробности и compact controls — `SPREADSHEET_FORMULAS_RU.md` и `tests/test_document_parser_xlsx_output_privacy.py`. Generic sanitation, весь PDF owner/privacy/fatal AST и non-version original81 assertions/setup/helpers неизменны; новый inverse3.1.6 дополняет старые. Frozen predecessor FAIL81/reviewfalse сохраняются. Fresh SOURCE outcomes/exits и actual AST roster — в `corrections/xlsx-output-privacy01/evidence/RESULT.json`; helper43 не запускаются заново. Это не genuine Excel/LibreOffice/native/full-base acceptance.

В3.1.8 protected slot определяется header/adjacent-label политикой независимо от успешного value/cache/evaluation; refused/cycle/incomplete formula source и attributes защищены и при отсутствующем результате. Реальные detector/context findings отделены от обычного display trim: несекретные значения не превращаются в masks буквальных sheet IDs. Общие sanitizers/schema/PDF тела не изменены. Два additive composition controls и новый inverse3.1.7 дополняют original88 с одиннадцатью current-version literals3.1.7→3.1.8. Frozen actual SOURCE outcome/capture — `corrections/xlsx-taint-admission01/evidence/RESULT.json`; этот текст не выдаёт planned packet или старый PASS88 за новое исполнение/приёмку.

## Ограничения ресурсов и cleanup

- Общие max_units/max_chars/max_pages/max_cells, пределы blocks/tables, OCR pages/pixels/DPI. Ограничиваются и text, и дублируемые cell metadata; штатный 200k unit cap явно помечает truncation. Большой output не выдаётся как полный.
- `ExitStack` владеет каждым PyMuPDF document и открытым pypdf stream, в том числе при исключениях. Pypdf reader close зарегистрирован при наличии API. Исходный файл не перезаписывается.
- Полностраничное OCR перед rasterization проверяет estimated pixels. Partial-image API не используется: оно может декодировать гигантскую исходную картинку при маленькой площади страницы. Native вызовы всё равно требуют worker OS memory/CPU/wall containment; Python pixel preflight не OS sandbox и не жёсткий per-page timeout.
- Tesseract pipes ограничены (stdout до 16 MB; stderr 16 KiB), дедлайн установлен до Popen; timeout/overflow приводят к kill/wait/join/close. UNKNOWN ownership удерживается и блокирует следующую попытку. Это только direct child; tree containment остаётся обязанностью существующего document worker supervisor. Сырой stderr в документ не публикуется.
- Worker input/output ENV limits теперь используют общий bounded reader; malformed ENV больше не ломает финальную сериализацию вне error envelope. OS limits и существующие parent admission/identity guards не ослабляются.

## Проверки

`tests/test_document_parser_pdf_ocr.py` — законченный stdlib SOURCE target: record→units/locators/redaction, native-first/cleanup static ordering, TSV→per-page quality, bounds/fingerprints, настоящие stdlib CSV/OOXML и worker protocol. Никаких parser mocks, SDK stand-ins или импорта third-party engine под закрытым SOURCE guard. Один case явно STATIC; остальные исполняют реальные функции/stdlib на авторских данных, но не библиотечный PDF/OCR API.

`tests/test_document_parser_components.py` — отдельные runnable genuine PyMuPDF/pypdf controls с синтетическими PDF, включая grid/cell и пустую среднюю страницу. **NOT_RUN**, пока нет установленного engine и отдельного finite parser admission. `MEMORY_WIKI_PARSER_COMPONENT_OPT_IN=1` — только opt-in теста, не authority grant. TMPDIR должен быть собственным абсолютным каталогом. Ни реальный OCR engine, ни эти PDF component cases, ни native SDK/FULL/CI/E2E этим SOURCE результатом не закрываются.

Primary result: `parallel/foundation-documents-20261019/parsers/evidence/RESULT.json`; raw stdout/stderr находятся рядом. Parent acceptance и combined integration gate остаются родителю.

### Фактически выполненный SOURCE packet

- Initial (`49ff500`): 16 cases, 15 PASS + 1 ERROR, child/controller exit 1, complete capture/ownership, audit refusals 0. ERROR обнаружил настоящий дефект нового TSV decoder: стандартный CSV reader отклонял поле длиной 200001 символ при разрешённом большем OCR cap. Первичные captures и исходный commit сохранены; это не ошибка PDF fixture и не native OCR observation.
- Причинная правка (`2ba0997`): bounded TSV rows разбираются без CSV quoting и **без изменения process-global `csv.field_size_limit`**. Все прежние assertions сохранены; добавлен контроль неизменности глобального CSV limit.
- Correction: свежие **16/16 PASS**, child/controller exit 0, complete capture/ownership, пустой supervisor error ledger и audit refusals 0. Из них **15 исполняемых SOURCE controls + 1 STATIC control**, а не 16 native parser tests. Facts-selected Python использован с `-I -B -S`; controller дополнительно запущен с `-W error`, а SOURCE child сохраняет штатный argv `harness.run_source` без добавленного warning flag. Оба SOURCE запуска — через неизменённый `devtools/source_bootstrap.py` и постоянный `harness.run_source`.
- Native PDF component cases, настоящий Tesseract/PyMuPDF OCR и SDK/FULL/CI не запускались. Нет установленных parser engines и отдельного finite admission. Из SOURCE PASS не выводится правильность native API/runtime cleanup или качество распознавания.

## Correction01: review boundaries S1/L1/L2/L3/C1 и N1

Independent `review/parsers01/REVIEW.json` сохранил `passed=false`. Это условные SOURCE findings, не установленные native incidents. Новый отдельный correction-кандидат не принят и не интегрирован; supplemental outcome и exact commit/tree: `parallel/foundation-documents-20261019/corrections/parsers01/evidence/RESULT.json`.

- **S1:** если table extraction отказал, исчерпан cell/table budget или передан неполный структурный префикс, в режиме `blocks` с включёнными таблицами содержимое **этой страницы не публикуется** (`withheld_incomplete_table_context`, partial/truncated). Не только raw blocks, но и page-text fallback и cell metadata остаются закрытыми. Защитный отказ не пытается дочитать исключённые ячейки сверх caps. Здоровые страницы/таблицы продолжают извлекаться; partial сам по себе не privacy fence. Для намеренных `pages`/`pdf_tables=false`, отсутствующего table API и pypdf-only режима новая гарантия table-context не заявлена.
- **L2:** при провале blocks API уже полученный native text не заменяется одними таблицами. Если таблицы доступны, выбирается единственный page-text fallback, замаскированный теми же table-context значениями; отдельные table units при этом не выдаются, поэтому тела таблиц не дублируются. Bbox не выдумывается, `table_structure_omitted=true`, `blocks_status` и partial сохраняют недоказанное структурное покрытие. При одновременном structural refusal действует S1, а не небезопасный обход ради сохранения текста.
- **L1:** effective native threshold участвует в PDF hash независимо от OCR. Worker менять не потребовалось: он передаёт options в настоящий extractor, который применяет тот же normalizer. Нормализованно равные значения сохраняют hash; chunking/deadline/embedding не становятся extraction axes.
- **L3:** successful capture допускается только после cleanup/joins и повторного чтения final overflow/read-error ledger. Original primary продолжает unwinding без подмены; cleanup/live-reader UNKNOWN остаётся retained и запрещает следующий Popen. Это не новый process-tree containment или доказательство native cleanup.
- **C1:** исправлен только вложенный `pdf_boundary` прежнего native-теста: keyword-only `options` обязателен, проверяется effective dict и соответствие шести positional values. Остальные старые assertions/body не изменены. Это fixture compatibility repair, не наблюдённая native regression; сама native suite не запускалась.
- **N1:** исправлен только label реального table-first source emission. Semantic reading order по-прежнему не обещан.

`tests/test_document_parser_review_boundaries.py` включает прежние SOURCE controls без правок и новые positive/inverse/compound regressions. Исполняемые роли разделены: реальные whole-module record consumers/redactors/fingerprint/worker; точный AST суффикс `_extract_pdf_pymupdf` после НЕисполнявшихся optional imports с авторскими document/page/table records; настоящее тело `_run_ocr_command` в собственном namespace с авторским terminal-turn transport; точный вложенный C1 boundary с настоящими dispatch/worker bodies. Ни SDK/authority validators, ни SQL не заменены разрешающими stand-ins. Deterministic drain interleaving не является настоящей Tesseract/thread/OS race reproduction. Один прежний source-order case остаётся STATIC. Standalone stdlib target требует собственного абсолютного `TMPDIR`; основной запуск — существующим неизменённым SOURCE harness.

Старые initial 15 PASS + 1 ERROR и correction 16 PASS сохранены по прежнему RESULT, не превращаются в fresh total. Historical outer carriers совпадают с сохранёнными наблюдениями, но полное transcript-origin corroboration ограничено. Новый original outer tool return сохраняется отдельно: child exit0 сам по себе не доказывает outer exit0. Native/PDF/OCR/SDK/SQLite/Vault/FULL/E2E/CI/hosted/paid остаются NOT_RUN, allowances0; parent acceptance и отдельный substantive-delta review остаются родителю.

## Correction02: terminal S1-AUTO-FALLBACK

Независимый `review/parsers02/REVIEW.json` сохранил `passed=false`: отказ одной страницы ещё не защищал весь dispatcher. Когда все выбранные страницы удержаны, `_pdf_finish` честно возвращает `empty`, но прежний `extract_pdf(auto)` считал это обычным отсутствием текста и переходил к raw pypdf/явно включённому Tika. Это условный SOURCE-механизм, не наблюдённая native утечка.

Теперь существующий typed page diagnostic `table_context=withheld_structural_refusal` агрегируется в `metadata.pdf_fallback_veto=incomplete_table_context`. Настоящий `extract_pdf` возвращает этот же результат до следующего reader/Tika, даже при `status=empty`; это отдельное состояние privacy, а не проверка `partial`, `truncated` или `content_indexed`. В смешанном документе безопасные units сохраняются со статусом `partial`. При обычном empty/unavailable без такого отказа fallback остаётся разрешённым, в том числе прежний явный Tika opt-in. Намеренные `pages`, `pdf_tables=false`, `pypdf`-only и здоровая block/table extraction не получают blanket veto. Новые caps, ENV, release/schema и dispatcher framework не вводятся.

`tests/test_document_parser_terminal_veto.py` замыкает настоящий `extract_pdf` с точным SOURCE-суффиксом PyMuPDF reader и whole-function pypdf reader, затем проверяет итоговые units, metadata, raw canary и фактический dispatch. Document/page/table records, pypdf-open и Tika transport — явно авторские; optional PDF imports и genuine engines не исполняются. Новый пакет включает все прежние32 controls (включая5 authored capture-transport и1 STATIC), без изменения их assertions/gold; прежний PASS через изменённый caller не переносится. Проверки дополнительно различают cell/table caps, table failure, Tika suppression, ordinary empty/unavailable и explicit modes, mixed partial и version-bound cache identity.

Exact candidate, фактические outcomes/exits и raw captures одного разрешённого SOURCE child: `parallel/foundation-documents-20261019/corrections/parsers01/correction02/evidence/RESULT.json`. Этот документ описывает контракт и target, не объявляет независимую приёмку или native PASS. Прежние3 SOURCE children и cold3/3/native0 сохранены; повтор/autoretry, engines/SDK/SQL/network/model/FULL/CI, integration и parent acceptance не разрешены этим пакетом.

## Correction03: S1-TERMINAL-CLEANUP-EXCEPTION

Независимый `review/parsers03/REVIEW.json` остаётся `passed=false`. Условный SOURCE-механизм: return из `_pdf_finish` внутри `ExitStack` ещё не означает фактического возврата reader. Исключение из `doc.close`/другого callback отменяло результат с veto, а generic handler dispatcher разрешал raw alternate. Genuine engine occurrence и частота **NOT_PROVEN**; прежний SOURCE41 с успешным authored close не проверял этот fault-state.

Теперь реальный emitter устанавливает защёлку `fallback_veto` на собственном `_PdfOutput` до передачи page diagnostic. `_pdf_finish` учитывает и эту защёлку. Небольшой `_PdfReaderOwner`, подкласс настоящего `ExitStack`, выполняет прежние callbacks и переносит установленный veto через весь выход owning context. Поздняя ошибка чтения/передачи emit/формирования finish после такого отказа также доходит до owning exit, а не становится ordinary empty. Raw metadata, неизвестное состояние, partial/truncated и простое отсутствие текста защёлку не устанавливают.

При обычном Exception после установленного veto reader поднимает `_PdfPrivacyVetoError`; специальный handler `extract_pdf` перед generic Exception повторно выбрасывает **тот же объект**, без pypdf/Tika и без healthy-success документа. Даже уже собранная безопасная часть mixed-документа не возвращается как успешный extraction при cleanup failure. Без fault прежний mixed partial по-прежнему сохраняет безопасные units. До veto обычные empty/unavailable/nonprivacy и close-fault сохраняют fallback; explicit pages/no-tables/pypdf-only и здоровая contextual redaction не меняются.

Carrier удерживает exact `primary_error` и `cleanup_error` приватно; исходная exception chain сохраняется. В args/`diagnostics` только фиксированные безопасные значения, без `str`/`repr` исключений и без raw document metadata/units. Cleanup Exception означает `cleanup=unknown`, `ownership=unknown`, а не доказанное закрытие. При ошибке body и успешно завершившемся `ExitStack` диагностируется complete именно owning exit. Это не отдельное доказательство native закрытия. Fatal/cancellation `BaseException` не превращается в обычный carrier/результат; исходная cancellation identity сохраняется и при вторичном cleanup Exception. Штатный worker в обычном (не debug) режиме сериализует только `ok=false,error=_PdfPrivacyVetoError`, exit2; private цепь не является публичным payload. Debug traceback, genuine worker/native lifecycle и host delivery отдельно не квалифицированы.

`tests/test_document_parser_veto_cleanup.py` использует прежние actual suffix/clone/reporter seams: прежние41 controls исполняются заново, включая5 authored capture-transport и1 STATIC, плюс additive cleanup/finish/read/handoff/primary/fatal/serialization/inverse controls. Подменяются только authored document/page/open/transport и инъекция ошибок, не SDK/authority/quality/owner validators. Реальный `ExitStack` и новый subclass исполняются; это **SOURCE**, не genuine engine/native cleanup. В старом terminal test изменены только две current-version expectation literals 3.1.2→3.1.3; прежний 3.1.1 inverse и assertions сохранены. Новый inverse дополнительно различает 3.1.2.

Один SOURCE packet и exact candidate/raw exits: `parallel/foundation-documents-20261019/corrections/parsers01/correction03/evidence/RESULT.json`. Само наличие этой ссылки не объявляет PASS: actual результат — в receipt. Исторические4 parser SOURCE children, cold3spent/0left, false46938/a5bf, malformed carrier и metadata refusals сохраняются. Native PDF/OCR/SDK/provider/SQL/Vault/network/model/host/FULL/CI/paid0; integration, независимое delta-review и parent acceptance остаются родителю.

## PDF-COMP01: inner alternate и промежуточный fatal cleanup

Review `parsers04/REVIEW.json` и parent disposition остаются отрицательными историческими свидетельствами. Два условных SOURCE-пробела correction03: успешный **внутренний** pypdf на следующей короткой странице обходил установленный table veto; настоящий `ExitStack` мог оставить fatal раннего LIFO callback только в context chain, выбросив более поздний ordinary Exception. Это не утверждение о genuine engine/runtime incident.

У собственного `_PdfOutput` теперь один invariant `context_alternates_allowed`: после настоящего structural refusal запрещены открытие **и использование уже открытого** внутреннего pypdf, а также новый OCR. Постраничные diagnostics явно показывают `withheld_incomplete_table_context`, `attempted=false` для запрещённого OCR и неполное покрытие. Тот же invariant проверяет emitter перед публикацией context-dropping origin (`pypdf`, `ocr`, `mixed`). Безопасный native text по-прежнему проходит с настоящими native tables и contextual masks, даже после отказа другой страницы. До veto обычные pypdf/OCR selection, explicit pages/no-tables/pypdf-only и outer fallback сохраняются; новая blanket-гарантия для отсутствующего table API не заявлена.

Существующий `_PdfReaderOwner` локально наблюдает common registration seam настоящего `ExitStack`: `callback(doc.close)`, `enter_context(stream)`, `callback(reader.close)`. Body cancellation имеет приоритет; иначе выбран **первый fatal в фактическом LIFO-порядке**, даже если более поздние callbacks бросили ordinary Exception. Частные `cleanup_errors` удерживают исходные ошибки в порядке наблюдения. Целевой контракт ba7 требовал также полного outward context chain, но фактический packet67 подтвердил лишь exact fatal/ledger/drain/UNKNOWN до отказа assertion341: три candidate cases потеряли часть наблюдённых объектов. Поздние iterations/assertions этих cases не были достигнуты; какой именно объект потерялся, первичный capture не записал. Baseline436 оказался отдельной ошибочной auxiliary premise. Поэтому whole ba7 отвергнут; прежние FAIL/UNKNOWN и отрицательное review не переименовываются в успех. Любой callback refusal оставляет private cleanup/ownership `unknown`, не доказанное native закрытие.

`tests/test_document_parser_veto_composition.py` переиспользует весь прежний54 roster/setup/cleanup и additive record seams. Только четыре current-version expectation literals в двух прежних файлах мигрируют `3.1.3→3.1.4`; старые inverse `3.1.1`/`3.1.2` неизменны. `EXTRACTOR_VERSION=3.1.4` исключает прежний extraction cache, включая3.1.3; secret policy literal, plugin version, schema, defaults/models/config и structural caps не меняются. Exact b464 baseline встроен в новый test как lossless SHA-bound Git-blob fixture: два expected-defect witnesses выполняются **в том же child**, не являются healthy baseline PASS и не требуют внешнего fixture файла.

Один применимый SOURCE RESULT, original outer return и raw captures: `parallel/foundation-documents-20261019/corrections/pdf-veto-composition01/evidence/RESULT.json`. До чтения receipt это только описание контракта, не заявление PASS. Штатные controller/bootstrap/deadline/stdio/input guards не изменены. Исторические5 parser children и cold3spent/0left сохранены. Genuine PDF/OCR/SDK/provider/SQL-owner/SQL/Vault/network/models/Vision/FULL/CI/install/restart **NOT_RUN**; отдельные review/parent acceptance/integration остаются родителю.

## PDF-CHAIN01: projection фактически наблюдённых causal objects

`ExitStack._fix_exception_context` может законно закончить работу на `None`; splice уже существующих direct links не восстанавливает отсутствующие связи. Новый локальный `_raise_fatal` после полного штатного drain строит projection из точных объектов owning body и `cleanup_errors`, не из предположений о сохранённой topology. Наружный head — тот же body fatal, иначе первый наблюдённый cleanup fatal. Далее идут остальные distinct cleanup objects в reverse-LIFO порядке (при повторах — последнее наблюдение), затем исходный body, если его identity ещё не встретилась. Private occurrence ledger сохраняет порядок и повторы. Обработан и final cleanup, совпадающий с selected fatal; bare re-raise с неполной chain больше не является отдельным выходом.

Projection меняет только `__context__` наблюдённых объектов через штатный `BaseException` descriptor; явные `__cause__` и их identity не меняются. Equality/hash/`str`/`repr` чужих исключений не вызываются. Это не общий graph repair: произвольные unobserved foreign context graphs не обходятся и их сохранность не обещана. Вторичный отказ metadata не заменяет selected fatal; private ledger и `cleanup/ownership=unknown` остаются, но полнота projection в таком отказном состоянии не квалифицирована. Ordinary-only primary/carrier, здоровый inverse, suppression/drain и отсутствие alternate после veto сохраняют прежнюю политику. Core/SDK/global monkeypatch не добавлены.

`tests/test_document_parser_causal_chain.py` включает original whole67 через прежний `packet_suite` и штатные setup/cleanup, без ручного вызова test methods/skip/наследованного rediscovery. Законный candidate341 и весь его helper/assert AST сохранены. Дополнительные controls проверяют final-selected fatal, точный reverse-LIFO/body tail, explicit causes, повторный observed object без cycle при сохранённом occurrence ledger, suppression и здоровые/ordinary veto/nonveto inverses. Новый cache inverse различает3.1.4; только шесть demonstrably-current expectations в terminal/cleanup/composition мигрируют3.1.4→3.1.5. Исторические3.1.1/2/3 и весь lossless embedded b464 неизменны.

Отдельная **test-only oracle correction**, не product fix: в derivative baseline witness заменён только unsupported auxiliary membership436 на exact ordinary-carrier type/identity и explicit final cleanup cause. Assertions431–435/437+ сохраняют оба обещанных differing effects: b464 публикует inner alternate после veto и заменяет промежуточный fatal ordinary carrier. PASS expected-defect witness не означает исправный baseline; original436/ba7 FAIL остаются frozen.

Exact frozen candidate и один применимый SOURCE packet: `parallel/foundation-documents-20261019/corrections/pdf-causal-chain01/evidence/RESULT.json`. Ссылка не предвосхищает outcome: фактические counts/exits/captures находятся в receipt. Исторические6 parser SOURCE children и cold3spent/0left неизменны; новый конечный допуск — один materially changed child, без automatic second correction. Deadline60s, cleanup3s, stdin64000/stdout48000/stderr16000 и source-input caps не увеличены. SOURCE audit не OS sandbox. Genuine PDF/OCR/engines/SDK/provider/SQL-owner/SQL/network/models/Vision/FULL/CI/install/restart **NOT_RUN**; независимый delta-review, parent acceptance и integration отдельно.


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

## Parser16 correction на 5047: подготовленный SOURCE, execution=0

Полный исходный review `integration/parsers-common01/review/REVIEW.json`
(`passed=false`, SHA256 `cb32609032f85b263269f6fea180c3318a162b8830f128f2cd0d6a87657f60ad`)
и parent HOLD не переписаны. SRC-OCR-01/02 и SRC-LOAD-03 установлены как
**условные SOURCE-механизмы**, не как воспроизведённые runtime incidents.
Отдельная ветка `fix/parser16-review-source01` от
`5047b80bbe97e55fa2a5f6c88c8cf49bd10cad40` меняет только шесть файлов из
`corrections/parser16-review-fix01/REQUEST.json`. Старый parser target и
current common9f68 остаются frozen; это не integration или acceptance.

### SRC-OCR-01: exact fatal вместо ordinary failed-document

В существующем `_run_ocr_command` ошибки pipe-reader и cleanup теперь
удерживаются как **исходные объекты**, с частным stage/occurrence ledger.
Приоритет после полного доступного drain: исходный body fatal; иначе первый
фактически наблюдённый reader/cleanup fatal; иначе исходный ordinary body;
при отсутствии body и только ordinary cleanup refusal — прежний фиксированный
`ocr_cleanup_ownership_unknown`. Ordinary read/capture refusal остаётся
`ocr_capture_limit_or_read_failure`, не превращается в принятый текст.
`SystemExit`, `KeyboardInterrupt` и другой `BaseException`, не являющийся
`Exception`, не упаковываются в ordinary `RuntimeError`.

Выбрасывается exact selected object. Приватные `_ocr_primary_error`,
`_ocr_reader_errors`, `_ocr_cleanup_errors`, `_ocr_observed_errors` сохраняют
causal objects, `_ocr_diagnostics` содержит только фиксированные
cleanup/ownership `complete|unknown`. `str`/`repr` чужих исключений не вызываются.
Projection `__context__` включает distinct наблюдённые объекты в обратном
порядке occurrence и исходный body последним, если его ещё нет; head — selected.
Явные `__cause__` не меняются. Это не обход/сохранение произвольного foreign
exception graph. Вторичный отказ private metadata/projection не маскирует
selected error, но полнота диагностик при таком отказе не обещана.

По неизменённому SOURCE caller contract fatal проходит мимо ordinary handlers
`extract_image_ocr`/`extract_document`; unchanged worker имеет `BaseException`
handler и должен выдать `ok=false`, exit2, а не ordinary failed-document под
`ok=true`, exit0. **Этот путь worker не исполнялся.** Private attributes не
публикуются обычным worker JSON; его прежний debug traceback отдельно не
квалифицирован и не расширяет privacy-гарантии.

### SRC-OCR-02: owning lifetime и независимые cleanup attempts

Buffers, Event, ledgers, callbacks и initial state подготовлены до acquire.
Owning `try/finally` начинается с `Popen` при `process=None`; успешный return
из acquire и весь последующий Thread constructor/start/body охвачены им.
После возвращённого child clock/poll/kill/wait/join/is_alive/close имеют
отдельные защищённые attempts: отказ одного не отменяет остальные.
Неудачный poll не считается завершением: kill и wait всё равно пробуются.
Clock refusal не отменяет wait/join: при недоступном остатке используются
минимальные timeouts (wait0.01s, join0s), а refusal остаётся в private ledger.
Это не новое доказательство сохранения общего deadline при отказавших clocks.

Join/state проверяются для каждого reader. При live/unknown reader pipes не
закрываются под ним; другие join/state attempts всё равно выполняются.
Любой cleanup refusal либо live/unknown reader консервативно сохраняет
`(process, threads)` в `_OCR_RETAINED`; следующий вызов отказывает до `Popen`
с `ocr_previous_ownership_unknown`. Обычный healthy результат возвращается
только после cleanup и финальной проверки capture ledger. Автоматическое
освобождение retained UNKNOWN или replacement worker не добавлены.

Это только **direct-child Python ownership contract** после возвращённого
acquire. Нет atomic async handoff/constructor-after-native-effect гарантии,
нового supervisor, native/Job/process-tree/descendant/OS containment либо
peak-memory/общего wall-time proof. Существующий `_PdfReaderOwner` и его
private-veto политика вне этой функции неизменны. Здоровый extraction content
не менялся: `EXTRACTOR_VERSION=3.1.8`, secret policy, cache/content version,
PDF/XLSX APIs, caps и fingerprint axes не повышались и не менялись.

### SRC-LOAD-03 и prepared regressions

Оба существующих test-owned entry paths (standalone PDF/OCR loader и optional
component setup) явно читают и SHA-проверяют shipped `spreadsheet_formulas.py`
**до** исполнения extractor. Pin:
`c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac`.
Используются `DEVTOOLS_INPUTS`/`devtools_read_bound` при их наличии, иначе
точный sibling file. У здорового outer XLSX packet сохраняется module identity:
namespace этого module заново инициализируется только из pinned source.
Ambient `sys.path` не дополняется, SDK/engine stand-ins не вводятся.
Wrong SHA даёт `spreadsheet_helper_source_mismatch`; read refusal сохраняется,
не становится missing-engine skip. Component opt-in, собственный absolute
TMPDIR и genuine-engine checks/старые assertions сохранены.

`test_document_parser_review_boundaries.py` расширяет прежний `capture_seam`
и `ReviewBoundarySourceTests` двенадцатью **подготовленными, НЕ запущенными**
methods: exact cleanup fatal без body в wait/join/close; body-priority/causes;
pipe fatal и ordinary inverse через image caller; pre-acquire Event/clock;
early Thread constructor/start; независимые cleanup clock/poll/kill attempts;
reader-state UNKNOWN/no replacement; два STATIC source-order/loader-closure
контроля; wrong-helper/read refusal и same-process healthy prebound identity.
Все прежние test methods/assertions/golds/reporters сохранены; изменённые
loader/setup/seam означают новый исполняемый контракт, не перенос старого PASS.
SOURCE loader closure, future same-process control, настоящий cold import,
pytest collection и genuine engines — **разные оси доказательства**.

Сейчас выполнены только Git/raw-byte/AST/syntax-compilation metadata checks
**без exec/import/collection/test bodies**. Sparse physical6 не является
полным runtime snapshot; для будущего admitted packet нужны exact shipped
peers/helper и соответствующие bound inputs. `metadata_preflight()` не вызывался:
он сам загружает продукт/fixture. Новые SOURCE/native/SQL/SDK/PDF/OCR/engine/
model/network/Vision/index/CI/install/restart executions0; runtime остаётся
`NOT_RUN`, qualification не получена. Exact frozen commit/tree, hashes/delta,
prepared roster, actual metadata returns и ограничения —
`parallel/foundation-documents-20261019/corrections/parser16-review-fix01/evidence/RESULT.json`.
Независимый meaningful delta-review и решения acceptance/integration — родителю.

### SRC-CALLER-04: отдельный owner handoff, pipeline/cache NOT_QUALIFIED

В baseline d93 shipped extractor сохраняет benign literal sheet IDs, но тогда неизменённый
`document_knowledge_graph.py` повторно применяет **generic** `sanitize_json`
как `_sanitize_extracted_json`: `ingest_document` при extraction-payload/cache
capture и `_safe_json` для metadata/locators; `_cached_extraction_payload`
проверяет результат той же generic sanitation; `_decode_json` повторяет её
на read paths `document_source`/`document_unit_context`. Точный механизм —
`clean_text` → `redact_secret_text` с построчным `line.rstrip()`:
trailing spaces bounded benign scalar sheet ID могут исчезнуть после extractor,
а typed structural identity hook `Unit.to_dict`/`ExtractedDocument.to_dict`
через эти слои не переносится. Fresh extraction, сохранённый cache и readback
поэтому не имеют доказанной literal-ID эквивалентности.

Это подтверждённый SOURCE composition gap, не выполненный SQL/cache loss test.
Он **не исправляется 17-м файлом** этой lane и не разрешает ослаблять общий
sanitizer. Documents owner должен отдельно согласовать typed structural
key/value contract через persistence/cache/read и подготовить real round-trip
с same-ID positive, whitespace-distinct inverse, fresh-v-cache equality,
Unicode/apostrophe/anchor/edge identity и прежними general privacy guards.
До такого исправления и собственного допуска SQL/cache/pipeline exact-ID
остаются **NOT_QUALIFIED**. Новый cache version сам по себе этот gap не лечит;
его менять для той OCR correction не потребовалось. Удаление leading spaces
на этом literal path не доказано; они остаются обязательным regression control.

### SRC-CALLER04: отдельный literal-owner code + prepared regressions

В этой производной lane реализован connected documentKG representation path.
`xlsx_identity_context`/`xlsx_identity_fields` в extractor — узкая схема
key + value + shape: producer metadata/coverage, уникальные nonblank benign
имена до1024 символов и до10000 листов, согласованные sheet index/title,
row/cell locator/anchor/parent и допустимые A1 coordinates. Один parser label,
ключ `sheet` либо policy marker не разрешает исключение. Имена не strip/casefold/
Unicode-normalize; апострофы и различимые Unicode sequences не реконструируются.
Generic sanitizer/secret detector, formulas/text/keys и обычный non-XLSX API
сохраняются; malformed/overcap/redacted/allblank/injection identity не получает
literal admission. Неизвестная/withheld fidelity явно отмечается, не exact success.

`_document_extraction_payload` готовит одну redacted typed representation для
cache capture **и** XLSX materialization. Узкий канал проходит source
`metadata.sheets`, `_safe_json`/`_decode_json`, unit locator и sheet title,
unit metadata (по прежнему generic), row/cell anchors и `formula_ref` endpoints.
Полные benign sheet titles до1024 не режутся прежним1000-character display cap;
остальной title API не расширен. `_hydrate_document_unit` используется и
`_load_candidate`, и `document_unit_context`; `document_source` декодирует
свою metadata по той же схеме, до реальных terminal guards. Keys и arbitrary
metadata не получают exemption; существующие depth/item/string caps не обходятся.
Literal channel отменяет только установленную whitespace-only normalization;
он не перезаписывает результат full-field secret detector, в том числе когда
secret-like совпадение возникает лишь в composed structural anchor.

`xlsx-literal-structure-v1` — representation policy, **не** новая версия parser/
evaluator или secret detector. XLSX extraction fingerprint включает её до
revision-ID и обеих early-return ветвей. Cache admission требует актуальный
typed payload, policy/state и прежние file/parser/hash/equality checks.
`_xlsx_unchanged_eligible` дополнительно запрещает `unchanged`/`scope_updated`
после cache miss или legacy source metadata, даже при equal revision.
`scan_documents` не применяет stat-only shortcut к XLSX: даже trusted mtime/size
equality проходит canonical ingest/cache policy; non-XLSX fast path сохранён.
Перечитывается настоящий разрешённый source; миграции пользовательских строк и
догадок о потерянных IDs нет. Legacy reads — `legacy_or_withheld`, не recovery.

`bounded_benign_fields_only` — состояние representation **до** read guards,
не аттестация exact final output. `_clean` сам не делает strip. Настоящий
`guard.py` сохраняет benign nonblank spaces, но может отфильтровать injection/
allblank; provider inspector вправе отказать или преобразовать значение.
`_guard_document_output`, disclosure finish, ACL/owner/connector/FS/worker guards
не изменены; raw ID не восстанавливается поверх их transformation/veto.

Новый `tests/test_document_xlsx_identity_source.py` содержит explicit stdlib
SOURCE suite и отдельный будущий own-SQLite suite. Module/class `__test__=False`,
collection не читает/не импортирует продукт; actual pytest nonselection
**NOT_RUN**. SOURCE definitions используют настоящий OOXML/evaluator/redactors,
serializer/cache/hydration owners; SQLite definitions — настоящую собственную
SQLite и shipped standalone Provider, заменяя только worker transport настоящим
inline extractor. Никакой fake public/disclosure/SQL authority не добавлен.
Public wrapper + genuine provider/read-fence/SDK/worker composition остаются
отдельными gates, не заменёнными static caller assertions.

Выполнены только authoring, inert AST/syntax compilation без exec и Git
metadata/checkpoint. **Ни одно тело теста, product import, collection,
metadata_preflight, SQL/native/engine/model/network/Vision/index/CI не выполнено.**
Нет RED→GREEN, independent approval, приёмки, integration/install/restart.
Полные source pins, static delta/preservation и prepared roster со статусами
NOT_RUN — `corrections/parser16-literal-owner01/evidence/RESULT.json`.
