# Минимальный контракт безопасности R03 / F05 — 2026-10-03

## Статус и область

**R03 открыт. `passed=false`. Это независимый baseline/proposed-plan review, не acceptance объединённого candidate, релиза, строгого режима или поведения LLM.** Production code и `_INJECTION_PATTERNS` не изменялись; commit/push не выполнялись. Отвергнутый f9 lifecycle cycle остаётся замороженным.

Проверяемая полная локальная база: commit `07d54ea0831267d775a0cfb2a5b42427764f392a`, coordinated fingerprint `48cfe752f8e4fb7a6328adc7e094584f3f18d715f1926562b2ac65ae085ae71a`. Все 299 declared source-файлов проверяются по SHA в `evidence/security-review/verify-review-inputs.py`; это не восстановление неизвестного upstream SHA ZIP. ZIP SHA: `0d7d350e4f216641b3783d0598eb3ba20a937731f7806cc2b30fe6358bebbf49`.

Ссылки ниже — **на реальные baseline-файлы**, не на номера из браузерных excerpts ZIP. В частности, спорный matcher теперь находится в `guard.py:18`, а F05 type branch — `recall_orchestrator.py:401–402`.

## Воспроизведено, а не предположено

- Corpus: `tests/fixtures/audit_guard_security_corpus_20261003.json`, 29 синтетических reviewer-authored случаев. Это не human gold, не репрезентативная частота ошибок и не процент защиты от атак.
- Проверяемый тест: `tests/test_audit_guard_security_diagnostics_20261003.py`. Финальный receipt — `evidence/security-review/diag07/`: **40 passed, 12 strict xfailed, 0 failures/errors; всего 52 test cases**. Xfail разрешён только для `OpenBaselineRequirement`; ошибка setup или иного типа остаётся красной. Старые неуспешные receipts сохранены и помечены superseded.
- 4 benign controls сохраняются. 4 benign false positives, включая исходное обсуждение защит от `prompt injection`, отсекаются. 12 direct-instruction и 4 case/whitespace-obfuscation controls блокируются локальным guard, настоящим provider, unified guard, model-row guard, document guard и shared-claim guard. Их нельзя «чинить» сменой ожидаемого результата на safe.
- 5 adversarial gaps в **local fallback**: zero-width split, fullwidth spelling, confusable Cyrillic character, русская прямая инструкция и role/context terminator. Они получают `status=safe`; это отсутствие срабатывания конкретного detector, не доказательство исполнения инструкции моделью.
- Настоящий `_prefetch_impl()` на реальной migrated SQLite fixture сохраняет benign control и отсекает direct/case-obfuscation controls, но emits сырой claim terminator: **два `</memory-context>` вместо одного и сырой `<|im_start|>system`**. И SQLite Connection, и настоящий subclass дают тот же результат. LLM/tokenizer/system-role exploitation не проверялся.
- Настоящий `handle_tool_call("memory_wiki_code_line_context", ...)` возвращает строку A01 с direct instruction в `line_text`, хотя `_inspect_recall_text()` её отвергает. Эта поверхность редактирует secrets, но не применяет injection classifier. Это parity gap для дальнейшего плана, а не утверждение, что чтение исходного кода само по себе запускает команду.
- F05: обычный `sqlite3.Connection` и его настоящий subclass исполняют полный authoritative suffix для event, episode, observation, entity и relation. Проверены positives, stale/missing fingerprints, foreign owner, TTL, content-hash mismatch, append-only UPDATE denial, закрытое соединение и SQL error после уже найденных positives. Обычно helper не закрывает provider connection и не commit-ит caller transaction.
- Дополнительный supported-path контрпример: **native SQLite authorizer** запрещает `RELEASE`. Реальная функция возвращает все пять validated identities и оставляет transaction открытой; `recall_orchestrator.py:796–805` swallowing cleanup failures не исправляется ZIP F05. Это отдельное открытое требование, не повод расширять f9 lifecycle работу.

## Просмотренная downstream-цепочка всей реальной базы

| Граница | Реальные ссылки | Что делает / чего не доказывает |
|---|---|---|
| Local detector | `guard.py:11–23,32–54` | Patterns проверяют весь переданный текст до display truncation; термин сам по себе совпадает. Batch guard выбрасывает filtered items. |
| Import/runtime fail-closed | `__init__.py:451–463,5115–5121` | Missing local guard и local runtime error дают quarantine, не identity/no-op. |
| Provider decision | `__init__.py:7542–7612` | Shared decision, если доступен, затем local guard. Shared quarantine не переопределяется benign local результатом. В этом запуске shared trust core не исполнялся. |
| Model rows | `__init__.py:7631–7663` | Каждая строковая колонка inspect-ится, rejected поле исключает всю строку; reader ACL отдельно. Corpus реально прошёл этот seam. |
| Ordinary/delta claims + provenance/evidence | `__init__.py:7016–7075,7082–7095` | Guard есть; accepted content вставляется в строки без единого XML/role escaping. |
| Final dynamic wrapper | `__init__.py:7395–7407` | Attributes XML-escaped; общий inner body вставляется сырой. Воспроизведён G05. |
| Auxiliary code/document/metadata | `__init__.py:7097–7135` | Дополнительный provider guard перед prefetch. Secret redaction — не substitute этому guard. Полный code-prefetch flow в corpus не исполнялся. |
| Episodes | `episodic_memory.py:787–835`; `__init__.py:7289–7314` | Backend guard работает по balanced excerpt. В episode renderer отдельно есть flatten + XML escaping; этот контроль нельзя переносить на claims без теста. |
| Events | `memory_events.py:1005–1023,1107–1187` | Owner/TTL/hash, secret scan, balanced excerpt, guard и provenance guard. Для oversized legacy row guard видит excerpt, не гарантированно весь первоначальный источник. |
| Observations/support | `memory_observations.py:533–593,1382–1454` | Hash, source event guard, current immutable version, evidence validation и повторный guard. Реально созданы capture → consolidation → query. |
| Shared blocks | `shared_blocks.py:140–161,175–186,198–215,376–390`; `__init__.py:6836–6862` | Title/claim guards, explicit grants/source digest, повторный guard собранной строки. Нет оснований считать source label trust elevation. |
| Unified recall | `recall_orchestrator.py:196–215,903–929,950–967,995–1026,1053–1090,1126–1177,1187–1202` | Перепроверяет textual content всех kinds, затем authoritative IDs/fingerprints; content остаётся данными, JSON-encoding не делает его «trusted». |
| Code tools | `code_knowledge_graph.py:157–171,488–520,2279–2283,2326–2343`; `__init__.py:8855–8857,12362–12369` | Secret/provenance redaction и scope isolation, но public output не вызывает injection classifier. Native code-line tool реально исполнен. |
| Documents | `document_knowledge_graph.py:212–250,2832–2839,2910–2911,2992–2995,3313–3334` | Recursive guard keys/values, bounded nesting, provider-before-display bound, затем local guard. Prefetch собирает предупреждение и текст, auxiliary guard выше остаётся необходимым. |
| MCP transport | `mcp-wrapper/server.py:269–295` | Сериализует provider result в text content; это не новый content guard. Error redaction не защищает successful text. Сервер/gateway не запускались. |
| Markdown dashboards | `__init__.py:18268–18295,18759–18784` | Используют model-safe claim rows; их наличие не доказательство структурной защиты финального prompt. |

Это coverage map прочитанных security/rendering seams, не заявление о полном suite или проверке каждой функции 299 файлов. Source hashes и exact AST spans записываются в boundary receipt.

## Минимальный безопасный контракт дальнейшей работы R03

### 1. Сначала неизменяемый baseline и запрещённые shortcuts

Сохранить байты `_INJECTION_PATTERNS`, существующих sanitizer signatures и quarantine semantics. **Не удалять/ослаблять regex, не добавлять `if docs/quoted/benign then safe`, не фильтровать matched spans перед classifier ради зелёного теста.** Не изменять `HERMES_SECURITY_STRICT` живого профиля, security Windows, SDK или native provider.

На текущем API невозможно получить raw `R03-01` как safe при неизменном безусловном `sanitize_context_text()`. Поэтому этот review не выдаёт такой результат за готовое исправление: R03 остаётся xfail. Любая будущая смена трактовки сигналов требует отдельного согласованного scope и нового независимого review всей цепочки, а не hidden bypass старого guard.

### 2. Ближайший минимальный шаг — renderer, не разрешение терминов

Отдельный небольшой candidate должен обеспечить **один доверенный dynamic wrapper**, а каждое data-поле внутри него — bounded serialization с escaping на последней границе. Применить одинаковую политику к claim, delta, auxiliary metadata, title, provenance, evidence, graph/document/code text; не только к episodes.

Запрещены source-controlled context delimiters и raw role/control tokens в итоговом prompt. Для корпуса G05 требуются ровно один настоящий `</memory-context>`, отсутствие raw `<|im_start|>system` и сохранённая data/citation связь. XML escaping — структурная защита, **не достаточное доказательство отсутствия семантической injection**; A/O rejection после изменения остаётся обязательной.

Не стирать исходную запись, fingerprint или quote ради rendering. Если display representation преобразован, явно отличать его от exact source quote; не изобретать literal evidence spans.

### 3. Явный результат, а не словарный allowlist

Для будущего отдельно одобренного R03-классификатора определить decision contract до реализации:

- `admitted_data`: проверенный bounded informational span; всегда untrusted data, никогда system/developer instruction;
- `quarantined`: actionable directive, role spoof, matcher/shared rejection или иное нарушение;
- `unknown`: unavailable guard, malformed response, exhausted budget, чрезмерная глубина или неразрешимая неоднозначность; **в public content не публиковать**.

Host-issued provenance/source binding, matched rule IDs, policy version и original-content SHA должны сопровождать решение внутренне. Model-controlled `source="documentation"`, filename, quoted label и confidence не дают admission capability. Shared quarantine/runtime failure нельзя снять новой benign эвристикой. Unknown нельзя конвертировать в safe через truthy object или default value.

Термины, defensive discussion и benign quotes измеряются отдельно. **Цитата прямой команды R03-04 остаётся quarantined**, пока отдельно не доказан безопасный способ её bounded inert representation; для закрытия term-only R03 достаточно отдельно согласованных R03-01..03 positives, а не blanket разрешения всех quoted instructions. Диагностический xfail R03-04 фиксирует utility tension, не навязывает unsafe acceptance.

### 4. Проверка полного admitted поля до сокращения и encoding

Проверять raw input и отдельную bounded detector projection до display truncation, balancing, splitting или JSON/XML encoding. Projection для case/Unicode normalization должна быть детерминированной и версионированной; исходный текст/quote не переписывать. Если raw **или** projection дают directive/suspicious decision, не публиковать original как safe.

Не обещать универсальную защиту NFKC/удалением zero-width: эти операции сами по себе не покрывают confusables, русские инструкции, encoded payloads и semantic attacks. Новый detector обязан явно доказать G01–G04 и не регрессировать B02/B03 (`Dan`/`Jordan`) и все A/O controls. Превышение scan budget — unknown/withhold, не «проверим только безопасный префикс».

### 5. Композиция всех model-facing paths

Сначала host principal/ACL/TTL/current-source validation; затем content decision; затем inert rendering. Content classifier не заменяет authoritative visibility, secret redaction не заменяет injection classifier, wrapper warning не заменяет ни то ни другое.

Проверить не только `sanitize_context_text`, но `_inspect_recall_text`, `_model_safe_row`, public tool results, unified recall, `_prefetch_impl`, documents, episodes/events/observations/shared blocks и code-line output. У public code output нужно явно решить, возвращается ли literal untrusted source в отдельном typed channel или guard-rejected content omitted; ни один вариант нельзя считать trusted code instruction.

### 6. Отдельная, узкая граница F05

Предложенный F05 type narrowing допустим как план: unsupported connections → `set()`, не cached identities. SQLite и genuine subclasses обязаны сохранять полный SQL/ACL suffix, snapshot/provenance/hash/TTL checks и caller ownership connection/transaction.

Нативный `RELEASE` отказ требует отдельного decision/cleanup contract: после невозможности завершить проверяемую read boundary нельзя заявлять безошибочное successful validation; не закрывать чужое соединение и не commit-ить чужую transaction. Этот reviewer не вносит remediation, не расширяет lifecycle scope и не смешивает её с R03. Открытый контрпример сохранить как отдельный gate/concern.

### 7. Обязательные gates и честная приёмка

1. Заморозить baseline/candidate hashes, corpus и его SHA; разделить diagnostics от acceptance.
2. Сначала воспроизвести R03/G05/F05 counterexamples на baseline реальным native SDK без stubs. Записать declined/failed gates, не удалять evidence.
3. На будущем **готовом merged source** снять только соответствующие known-failure markers, добавить independent/held-out benign/adversarial cases и выполнить все paths выше с настоящими providers/backends. Frozen-baseline test из этого review не является candidate gate и намеренно проверяет baseline guard hash.
4. Все A01–A12/O01–O04 должны оставаться blocked; term-only positives допускаются лишь после отдельного одобрения decision contract и доказанных downstream invariants. Новая защита gaps не должна ухудшать benign controls.
5. Перед release нужна отдельно разрешённая strict-mode/shared-core verification; сегодняшний isolated mode 0 не заменяет её. Network/model/extraction/живые profiles в этом review запрещены.
6. JSON verdict fail-closed: непустые `security_concerns` **или** `logic_errors` → `passed=false`. Green diagnostics with xfails никогда не означают R03 closed, full security acceptance или tested exploit.

## Воспроизводимость и evidence

Из `coordination.json` взять `sdk_python`, затем:

```text
<sdk_python> -I -B -Xutf8 <root>/run_isolated.py --worker security-review --label <NEW_UNIQUE_LABEL> --package -- tests/test_audit_guard_security_diagnostics_20261003.py -o log_file=<root>/evidence/security-review/<NEW_UNIQUE_LABEL>/pytest.log
```

Нельзя использовать повторно `diag07`: labels сохраняют immutable receipts. Absolute log_file необходим, потому что harness разрешает writes только в output своей попытки; `diag01` зафиксировал denied pytest logging. `diag04/05code/06` содержат честные fixture/setup failures; исправлены только диагностические fixtures, не production. Append-only triggers не удалялись: negative fixture вставляет новую corrupt synthetic row, не UPDATE защищённого исходного события. In-memory `db_path` задан как `Path`, чтобы native public reader и native consumer-registration API работали без stand-ins.

Запустить read-only boundary verifier после появления deliverables:

```text
<sdk_python> -I -B -Xutf8 <root>/evidence/security-review/verify-review-inputs.py
```

Он проверяет ZIP CRC/paths/sizes/member hashes, все declared baseline SHA, native/JUnit receipts и corpus completeness; делает только `git apply --check`, **не применяет ZIP**. Literal F01/F05/hardening/all-code patches не накладываются на этот actual baseline: не трактовать browser-fixture replay как применимость к production.

Основные артефакты: `evidence/security-review/review.json`, `boundary-verification.json`, `diag07/{junit.xml,run-receipt.json,native-origins.json,diagnostic-observations.json}`. Evidence содержит synthetic case IDs, hashes и outcomes, а не настоящие user contexts или secrets. Профильные skills/config/auth/env не менялись; сохранение workflow в профильной skill отложено, поскольку этот scope явно запрещает profile modifications.
