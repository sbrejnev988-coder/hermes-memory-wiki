# `gpt-6-luna`: консервативный extractor

## Что реализовано

Используется существующий `extractor._codex_content` → публичный
`agent.auxiliary_client.CodexAuxiliaryClient`, с прежними owner-local OAuth,
фиксированным Codex endpoint, profile/secret scope, `max_retries=0`, запретом
redirect и ambient proxy. Новый клиент, backend, SDK, resolver/fallback и
конфигурационные изменения не добавлены. Literal `gpt-6-luna` не исправляется,
не дополняется provider prefix и не заменяется другой моделью.

Reader по-прежнему читает только `home/config.yaml`, не экспортирует YAML в
process environment. Дополнительная проверка caller snapshot применяется и к
прямому вызову: disabled/error/unknown provider, неправильный model/timeout,
относительный home и Codex literal в API-key route не разрешают dispatch.
Graph settings и отдельный `model` должны совпасть. Родительские исходные
source/owner/erasure/once-origin fences не заменяются этой проверкой.

Цепочка ответа: одна choice с index=0 → assistant text без tools/function call
→ `finish_reason=stop` → **явное** отсутствие refusal → bounded strict JSON →
полная shape-проверка → exact source quote/index/speaker/time и существующие
actor/action/object/polarity/injection guards → grounded candidate. Markdown,
JSON repair, duplicate keys, NaN/Infinity/overflow, лишние/неверные поля и
оборванный JSON не принимаются. Форма schema проверяется целиком; отдельные
незаземлённые предложения отбрасываются без повышения доверия остальных.

Remote transcript очищается до dispatch. Ответ должен цитировать и локальный
оригинал, и реально отправленный sanitized span: withheld text нельзя
восстановить моделью. Secret guards распространяются также на topic/timezone и
локальную heuristic-персистенцию. Tool/system messages и объекты вложений не
становятся owner speech. Graph helper не обрезает source на 4000 символов:
больший source отвергается, чтобы не потерять trailing denial; raw secrets и
оперативные инструкции не отправляются. OCR/сырые документы не подключены.

`length/incomplete` → truncated, content_filter/refusal → refused, неизвестная
completion/refusal shape → fail-closed. Нет автоматического retry или другого
provider. Дедлайн сохраняется через подготовку запроса и окончательное
заземление; запоздавший корректный JSON не принимается. BaseException/cancel
не превращается в fallback. Используется прежний синхронный transport; это не
гарантия немедленного освобождения заблокированного native I/O или остановки
удалённого вычисления/расхода квоты. `max_tokens` Codex adapter не пересылает
как server-enforced cap.

`persisted`/`persisted_ids` теперь содержат только callback IDs `c_*`;
`rq_*` отдельно в `queued_for_review`/`review_ids`. Truthy неизвестный outcome
не считается сохранённым. Это классификация штатного callback, не независимый
readback SQLite. Ни accepted, ни assistant «verified» speech не устанавливают
verified fact. Extraction остаётся chat-scoped, evidence сохраняет source
quote/speaker/index/time и extractor origin; writer/quality/ACL не обходятся.

## Реально установленная граница capability

При разработке прочитан actual PM workspace
`installs/cc52de42393663ec/environments/5890d958b0ed44d3bc43c946bce59284/workspace`:

- `agent/auxiliary_client.py`, `_CodexCompletionsAdapter`: model в public
  namespace — **эхо requested model**, не server attestation. `response_format`
  и `max_output_tokens` этим Codex путём не пересылаются. Schema находится в
  instructions и затем проверяется локально; server-enforced schema UNKNOWN.
- `agent/auxiliary_codex_response.py`: partial/incomplete нормализуется в
  `length`; helper сохраняет finish_reason, но не независимый refusal marker.
- `agent/codex_responses_adapter.py`, `_extract_responses_message_text`: refusal parts
  становятся текстом. `CodexAuxiliaryClient` выдаёт message без поля `refusal`.
- `agent/model_metadata.py` содержит `gpt-6-luna` в статических Codex metadata.
  Это не актуальный owner model catalogue/entitlement и не inference proof.

**На этом actual public adapter отсутствие refusal field приводит к
`response_refusal_unconfirmed`; даже schema-valid JSON не принимается как
LLM candidate.** Это намеренное сужение, а не подтверждённая работа модели.
Реальные availability/entitlement/SDK execution/качество модели UNKNOWN.
Prerequisite: поддерживаемый upstream public auxiliary result, сохраняющий
refusal provenance (включая mixed refusal+JSON), completion state и желательно
server model identity; затем отдельный разрешённый offline genuine-SDK packet
и bounded owner-authorized real-provider canary. Не добавлять поле `None`
локальным monkeypatch и не считать его доказательством non-refusal. Изменять
Core/SDK/PM в рамках этой lane запрещено. Live/paid canary не выполнялся.

## Diagnostics и отдельный hook для родителя

Возвращается `llm_diagnostics`: фиксированные outcome/code, числа offered,
grounded/rejected; actual_model/model_capability/server_schema_enforced
остаются UNKNOWN. Без response body, transcript, auth, home/endpoint, usage
оценок и foreign exception metadata. Heuristic output при LLM отказе остаётся
отдельным `source=extractor:heuristic`, не LLM success.

В correction01 изменён **только** raw-content вход метода
`MemoryWikiProvider._extract_session_claims`, по узкому поручению координатора.
Отдельное предложение родителю для существующего `_audit` payload:
добавить явные scalar counters `accepted`, `queued_for_review`,
`persistence_unknown` и allowlisted `llm_diagnostics.outcome/code` из результата.
Не сериализовать весь result/settings/entries. Existing `persisted_ids` consumer
теперь получает только c_*; once-origin background enqueue, fresh-source,
original `_admit`, erasure и terminal fences оставить неизменными. Статическая
проверка wiring не доказывает исполнение provider lifecycle.

## Correction01: raw speech и полное выбранное source-window

Независимое review исходного `f7c9d2547bd1a7d0cb63cedeca5858f3be2a3ca6`
сохраняется с `passed=false`: LUNA-S1 (caller делал `str(content)` раньше
type guard) и LUNA-L1 (prefix cut мог потерять trailing denial). Оба механизма
существовали до этого кандидата; это не новые baseline regressions и не
наблюдённый live/SQLite incident. Исходный review и два прежних SOURCE запуска
не переписываются и не обнуляются новым supplemental packet.

Actual caller теперь принимает только `type(content) is str`: dict/list,
вложения, foreign objects и string subclasses не вызывают `str`, `bool` или
`strip` до отказа. Обычная plain-string речь передаётся с исходным whitespace,
role/time metadata; trim остаётся внутри normalizer после сохранения raw
длины. Tool/system речь не получает owner attribution.

Лимиты прежние: последние **32 целых сообщения**, **6000 raw characters** на
сообщение, **48000 raw characters** всего выбранного окна. Whitespace тоже
расходует бюджет. Это консервативное ужесточение: бывший trimmed-fit input может
теперь отказать; лимиты не повышены. Они не являются pre-strip bound на
allocation, память или всё retained input: нормализация/`strip` и полученные
ранее объекты могут расходовать ресурсы до проверки. Native CPU/memory
containment здесь не доказан. Более старые сообщения вне intentional
last-32 window по-прежнему вне контракта. Внутри выбранного окна нельзя
сохранить безопасный на вид positive, выбросив более длинное сообщение, denial
или неизвестный кусок: никаких prefix cuts, частичных clauses или дополнительного
whole-message dropping ради transcript budget.

При превышении возвращается bounded `source_message_budget_exceeded` либо
`source_transcript_budget_exceeded`, `llm_diagnostics.outcome=source_refused`;
entries/accepted/queued/persistence_unknown равны нулю. **Внутри extractor**
оба пути — heuristic и LLM — останавливаются до его собственного разрешения
routing/settings, outbound и persistence callback. Это не обещание отказа
до любых действий provider caller: `_extract_session_claims` может раньше
попробовать owner snapshot через `_connect` и прочитать settings, а после
пустого результата пройти свой audit/auto-graph путь. Эти native/SQL/lifecycle
эффекты данным SOURCE packet не квалифицированы. Отказ не превращается в
пустой model request или повтор на другом provider.
`heuristic_only=false` в таком отказе означает, что extraction не исполнялась,
а не LLM success. `extractor_score_session` для того же известного отказа
возвращает прежнюю форму `{"total": 0.0}` без lifecycle exception и без сигнала
на фоновую обработку. Cancellation/BaseException не поглощается.

`tests/test_luna_extractor_source_scope.py` добавляет связанные caller/plain/raw,
exact/+1/whitespace/trailing-denial/message/transcript/score controls и выполняет
прежние 20 Luna controls без изменения их bytes/assertions. В том же SOURCE
packet возможны два явно помеченных witness на immutable f7 Git blobs: успешный
witness подтверждает ожидаемое **нарушение baseline**, не исправность baseline.
Штатный entrypoint превышает literal binder 1 MB, поэтому SOURCE carrier
содержит только exact method + dependency-closed неизменённые privacy helpers;
его source spans/AST/raw и полный originating Git blob связываются до запуска.
Binder/harness/bootstrap/limits не меняются.

Роли: actual source-extracted caller body и реальные local redactor/scan;
полные local extractor/http-safety/graph; synthetic routing snapshot и
authored transport/parser input; passive callback/audit observer. `_connect`
явно отказывает: native profile/identity/SDK/HTTP/SQL и реальное сохранение
**NOT_RUN**. Observer не возвращает выдуманные `c_*` и не доказывает stored
claim. Полная provider initialization/lifecycle композиция не исполняется.
Известный public Codex refusal-provenance blocker остаётся fail-closed UNKNOWN;
никакого добавления `refusal=None` настоящему adapter, Core edit или model call.
Actual outcomes, commit/tree и ORIGINAL outer tool return — только в
`parallel/foundation-documents-20261019/corrections/luna01/evidence/RESULT.json`
и связанных immutable captures. Delta-review/acceptance/integration — родителю.

## Проверка и scope

Первый packet сохранил behavioral FAIL: `uses` и `does not use` имели разные
surface action keys, поэтому cropped positive мог пережить отрицание того же
actor/object. Correction добавляет только явные inflection pairs уже
поддержанной грамматики (без stemming/synonym inference), сохраняя actor,
полный object, qualifiers и spans; добавлены inverse и cross-actor/cross-scope
positive controls. Отдельный ERROR первого packet — конфликт имени argument
`content` в новой authored fixture; исправлена fixture, не ослаблены assertions.
Первичные captures и opening bytes сохранены. Public `openai.APITimeoutError`
также явно преобразуется в безопасный timeout outcome, без provider error body;
его genuine-SDK execution остаётся NOT_RUN.

`tests/test_luna_extractor_boundaries.py` — законченный stdlib SOURCE packet
через существующие `devtools/harness.py` и `source_bootstrap.py`. Он исполняет
полные локальные extractor/http-safety модули без package initializer, SDK или
пользовательского home. Authored transport/response inputs проверяют
request/parser/grounding-контракт, не выдают себя за настоящую модель. Reader и
native transport wiring проверяются статически; YAML/core profile identity,
OAuth/SDK HTTP/cleanup и installed/runtime integration **NOT_RUN**. Прямой
standalone запуск требует изолированного synthetic TMPDIR; в CI файл также
поддерживает unittest collection.

Фактические exits, roster, captures, source pins и результаты correction —
в lane `evidence/RESULT.json`. SOURCE PASS не означает native/FULL, model
quality, crash recovery, публикацию, установку или release acceptance.

Четыре плоскости: целостность — SOURCE evidence/schema, не DB/recovery;
безопасность — SOURCE secret/grounding/fail-closed controls, не native ACL;
совместимость — static public bindings, native lifecycle NOT_RUN; качество/
производительность — authored behavioral controls, реальный benchmark/usage
UNKNOWN. Исторические spend/отказы/допуски не обнуляются.
