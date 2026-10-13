# Расширенные настройки Memory Wiki 1.24.5

Основа — immutable Wiki `3b77376b9098584538962977f227940e7e183ec3`. Приведённые host readers сверены с Core reference `79b45d1647f6b5680768d851c4c406e8cc550a1e`; цитируемые spans совпадают с наблюдавшейся ревизией Core `71d34bad1045610252eda02ee79549436896e784`. Равенство всего Core и состояние уже загруженного backend не заявляются. Это документация целевых настроек, не live inventory и не release/E2E приёмка.

[Вернуться в README](../README.md#расширенные-настройки-env-и-configyaml).

## Расширенные настройки `.env` и `config.yaml`

Ниже — переносимый **целевой рецепт**, а не снимок настроек чьего-либо ПК. Он описывает Memory Wiki 1.24.5 на source-checkpoint `3b77376` и не меняет файлы профилей. Declared Wiki version этого source-checkpoint — 1.24.5.[5] Полный source-grounded каталог дополнительных ENV-параметров, типов, условий и readers: [ADVANCED_SETTINGS.md](#каталог-env-параметров).

### Где хранить и как читать настройки

- `.env` содержит поддержанные ENV-параметры и отдельные credentials **этого owner-профиля**; это dotenv, не shell script. Не помещайте туда `source`, команды или credentials в URL.
- `config.yaml` выбирает один external memory provider рядом с built-in memory и задаёт host delivery, session `extraction` и `graph_extraction`.[12][13] Добавляйте только нужные leaves к существующему файлу, не заменяя main/delegation/compression models, paths, ACL и другие plugins/profiles.
- Секреты — не в YAML, README, командной строке или публичном отчёте. Нельзя переносить `.env`, `auth.json` либо базу между профилями ради одинаковых настроек.
- **Code default**, целевое значение, сохранённое значение и значение уже загруженного процесса различаются. Import-time ENV/globals и кешированный provider не получают новые значения только от записи файла.[3][9][19]

### Расширенный локальный режим: больше кандидатов, без новых модельных запросов

База включает SQLite/FTS и уже индексированные документы/код. Semantic embeddings, rerank и LLM extraction вынесены в отдельные opt-in ниже. Чтобы прежнее YAML `enabled:true` не оставило модельный маршрут активным, для этой базы **обе** extraction-ветки должны быть явно выключены в owner YAML.[1][2]

```dotenv
# Локальный поиск и приватность
MEMORY_WIKI_SEMANTIC=0
MEMORY_WIKI_RERANK_ENABLED=0
MEMORY_WIKI_LLM_PACK=0
MW_EXTRACTION_ENABLED=0
MEMORY_WIKI_GRAPH_EXTRACT_ENABLED=0
MEMORY_WIKI_GRAPH_AUTO_EXTRACT=0
MEMORY_WIKI_DEFAULT_VISIBILITY=chat

# 16 main claims / 64 candidates — цель, не capacity модели
MEMORY_WIKI_MAX_PREFETCH_CHARS=16000
MEMORY_WIKI_PREFETCH_CLAIM_LIMIT=16
MEMORY_WIKI_PREFETCH_EXPANSION_FACTOR=4
MEMORY_WIKI_PREFETCH_CANDIDATE_LIMIT=64
MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CLAIMS=4
MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CHARS=2000
MEMORY_WIKI_PREFETCH_CLAIM_MAX_CHARS=1200
MEMORY_WIKI_PREFETCH_EVIDENCE_MAX_CHARS=600
MEMORY_WIKI_PREFETCH_DEADLINE_SECONDS=5.5
MEMORY_WIKI_PREFETCH_DIAGNOSTICS=anomalies
MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC=8
MEMORY_WIKI_DIVERSITY_MAX_SOURCE_SHARE=0.65

# Использовать уже индексированное; не запускать scan/OCR/embed автоматически
MEMORY_WIKI_DOCUMENT_PREFETCH=1
MEMORY_WIKI_DOCUMENT_PREFETCH_CHARS=4000
MEMORY_WIKI_DOCUMENT_RERANK=0
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=0
MEMORY_WIKI_DOCUMENT_AUTO_EMBED=0
MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST=0
MEMORY_WIKI_DOCUMENT_OCR=0
MEMORY_WIKI_CODE_GRAPH_PREFETCH=1
MEMORY_WIKI_CODE_GRAPH_PREFETCH_CHARS=4000
MEMORY_WIKI_CODE_GRAPH_EMBED=0
MEMORY_WIKI_CODE_GRAPH_RERANK=0

# Новый retention и worker не включаются этим базовым блоком
MEMORY_WIKI_EVENT_LEDGER_ENABLED=0
MEMORY_WIKI_EPISODIC_ENABLED=0
MEMORY_WIKI_EPISODIC_PREFETCH=0
MEMORY_WIKI_EPISODIC_SEMANTIC=0
MEMORY_WIKI_BACKGROUND_JOBS_ENABLED=0
MEMORY_WIKI_OBSERVATIONS_ENABLED=1

# Не снимать защиту ради объёма или скорости
HERMES_SECURITY_STRICT=1
MEMORY_WIKI_STRICT_RECALL=1
MEMORY_WIKI_SUPPRESSION_FAIL_CLOSED=1
MEMORY_WIKI_BLOCK_RAW_VAULT_READS=1
MEMORY_WIKI_GLOBAL_SEARCH_ENABLED=0
MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH=0
MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_PREFERENCES=0
MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX=0
```

Source default main claims — **12**, candidate pool — **36** при defaults; приведённые `16/64` — рекомендуемая ограниченная выборка. Guard, ACL, relevance, deadline и общий character budget могут сократить результат. Explicit candidate limit уже итоговый; `64` не умножается снова. Source-share limit — мягкий штраф score, topic limit — отдельное ограничение.[3]

### Согласованный host YAML для базы

Это merge-фрагмент, не замена целого `config.yaml`. `.env` Wiki cap и host cap здесь согласованы на `16000` chars; если уже установлен другой допустимый owner budget, не повышайте его автоматически.[3][8][9]

```yaml
memory:
  provider: memory-wiki
  prefetch_spill_enabled: true

hooks:
  output_spill:
    enabled: true
    max_chars: 16000
    preview_head: 500
    preview_tail: 500

security:
  redact_secrets: true

plugins:
  entries:
    memory-wiki:
      settings:
        extraction:
          enabled: false
        graph_extraction:
          enabled: false
```

**Exact namespace:** `plugins.entries.memory-wiki.settings.extraction`, не `session_extraction`; graph — `settings.graph_extraction`. ENV-only prefetch/background/auto-graph knobs не получают portable nested YAML counterparts только от похожего имени.[1][2][11]

### Opt-in semantic embeddings и reranking

#### Семантика весов и граница rerank/diversity

В текущей ordinal correction `MEMORY_WIKI_RERANK_WEIGHT_TECHNICAL`,
`MEMORY_WIKI_RERANK_WEIGHT_MIXED` и `MEMORY_WIKI_RERANK_WEIGHT_SEMANTIC`
выбирают **local order при `0` / успешный ordinal order при любом `>0`**,
а не непрерывную силу blending. При `0.01` и `1` порядок одной успешно
ранжированной cohort одинаков. `0` не является выключателем HTTP: admission
запроса и cache lookup выполняются раньше fusion; для отключения rerank
существует отдельный `MEMORY_WIKI_RERANK_ENABLED` gate. Этот текст не меняет
настройки профилей, presets, ENV/config routing, модели или API routes.

Прежняя формула `(1-w)/(RRF_K+local_rank) + w/(RRF_K+model_rank)` остаётся
в `rerank_fusion_score` **только диагностикой**, не ключом сортировки после
успешного rerank. Отсутствующие model results идут после ranked rows в прежнем
локальном порядке. При skipped/failed/invalid-cache rerank порядок оставшихся
строк остаётся локальным; внешний RRF сохраняет прежнюю арифметику fallback.
Сохранение численных defaults/весов не означает сохранение прежнего sorting
behavior — это явное изменение совместимости weight-as-strength.

Recall/document guard refusals связываются с точными позициями исходного
top-K и исключаются до diversity; unknown/non-safe guard status тоже отказ.
Отказ одной строки не удаляет другую по совпавшему ID. Identity validation
по исходному набору, ACL и последняя schema/generation/disclosure revalidation
не ослаблены. Новые rows за пределами исходного top-K не подставляются,
дополнительных RPC нет. Topic quota (штатно `8`), source-share, candidate pool
и остальные budgets сохраняются.

Гарантия ограничена уже проверенной eligible cohort: ранний skip не запускает
новый guard pass; непроверенные gaps/tail, optional/mixed kinds и строки иных
источников не становятся ранжированными. Outer fusion сохраняет только
относительный порядок surviving ranked claims первой успешной query после
авторитетных фильтров (primary обычно первая; при её skip — возможен variant).
Это не гарантия абсолютного top1 во всём heterogeneous union и не сравнение
raw scores разных requests. Authored числовые cache fixtures проверяют
композицию компонента, но не реальное качество модели или live/native fleet.

Добавляйте этот блок **вместо соответствующих выключенных строк базы**, только после проверки owner endpoint/key, Qdrant и согласия на сеть/расход. Это маршрут OpenRouter, не бесплатный local preset. API-key placeholders ниже закомментированы и не являются credentials.

```dotenv
MEMORY_WIKI_SEMANTIC=1
MEMORY_WIKI_EMBED_PROVIDER=openrouter
MEMORY_WIKI_EMBED_URL=https://openrouter.ai/api/v1
MEMORY_WIKI_EMBED_MODEL=qwen/qwen3-embedding-8b
MEMORY_WIKI_EMBED_DIMENSIONS=4096
MEMORY_WIKI_VECTOR_SIZE=4096
MEMORY_WIKI_EMBED_INPUT_MAX_CHARS=12000
MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES=512
MEMORY_WIKI_EMBED_QUERY_CACHE_TTL_SECONDS=86400
MEMORY_WIKI_EMBED_DOCUMENT_CACHE_TTL_SECONDS=2592000
MEMORY_WIKI_EMBED_CACHE_SINGLEFLIGHT_WAIT_SECONDS=45
MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333
MEMORY_WIKI_QDRANT_COLLECTION=memory_wiki_claims
MEMORY_WIKI_QDRANT_ALIAS=memory_wiki_claims_active
MEMORY_WIKI_QDRANT_ALIAS_MODE=auto
MEMORY_WIKI_RERANK_ENABLED=1
MEMORY_WIKI_RERANK_MODEL=voyageai/rerank-2.5
MEMORY_WIKI_RERANK_TIMEOUT=3
# MEMORY_WIKI_EMBED_API_KEY=<OWNER_EMBED_KEY>
# MEMORY_WIKI_RERANK_API_KEY=<OWNER_RERANK_KEY>
# MEMORY_WIKI_QDRANT_API_KEY=<OWNER_QDRANT_KEY_IF_REQUIRED>
```

Embedding dimensions и Qdrant vector size обязаны совпадать с фактическим ответом выбранной модели. Смена model/dimensions/input/prefix/template меняет manifest; ENV save не доказывает завершённый reindex либо alias switch. Local stub — детерминированный fallback, не доказательство качества neural embeddings. Loopback URL не доказывает отсутствие удалённой или платной inference за прокси. Foreign profile требует собственный согласованный route/contract; credentials importer/sibling не становятся его grant.[3]

### Opt-in session и graph extraction

Следующий пример **не готов к применению без замены placeholder**: `<OWNER_CODEX_MODEL_ID>` умышленно не проходит model validator. Сначала выберите точный разрешённый владельцу ID, подтвердите его native OAuth и квоту. После этого замените соответствующие sections базы. `enabled:true` разрешает отдельные модельные запросы; chat/delegation model этим не меняется.[1][2]

```yaml
plugins:
  entries:
    memory-wiki:
      settings:
        extraction:
          enabled: true
          provider: openai-codex
          model: "<OWNER_CODEX_MODEL_ID>"
          timeout: 30
          max_tokens: 1800
          reasoning_effort: low
        graph_extraction:
          enabled: true
          provider: openai-codex
          model: "<OWNER_CODEX_MODEL_ID>"
          timeout: 30
          reasoning_effort: low
```

| Leaf | `extraction` | `graph_extraction` |
|---|---|---|
| `enabled` | strict boolean | strict boolean |
| `provider` | `openai-codex` или `openrouter`, explicit при включении | то же |
| `model` | exact provider-specific string, explicit при включении | exact effective model; owner override описан ниже |
| `timeout` | integer 1–60 секунд, bool запрещён | integer/float 1–60, bool запрещён |
| `max_tokens` | integer: Codex 256–9000, OpenRouter 256–3000 | key не поддержан; request использует 700-token hint |
| `reasoning_effort` | `low`, `medium`, `high`, `xhigh`, `max` | тот же accepted enum |

Это полный accepted leaf-набор. Не добавляйте `api_key`, `base_url`, `endpoint`, `retry`, `temperature`, `context_length` или graph `max_tokens`; неизвестные поля и неверные типы/ranges дают отказ. Code default disabled model literal `gpt-6-luna` — не рекомендация и не entitlement.[1][2]

Codex model grammar — 1–200 символов `[A-Za-z0-9][A-Za-z0-9._-]{0,199}`, без `/`. Session OpenRouter требует `org/model`; graph OpenRouter имеет свой validator и допускает bare ID. Не исправляйте slug и не выводите context capacity из suffix. Session effort передаётся обоим native routes; graph OpenRouter payload effort не передаёт. Native Codex может нормализовать effort к vocabulary модели.[1][2][14]

**Auth и стоимость:** Codex использует read-only owner-local native OAuth; present pool авторитетен, empty pool не разрешает singleton/root/sibling fallback. Extractor не выполняет sign-in, refresh, healing или auth-store writes. Subscription расходует квоту и не unlimited. Session OpenRouter — отдельный metered opt-in с owner `OPENROUTER_API_KEY`; graph OpenRouter сохраняет собственные graph endpoint/key readers. Ошибка выбранного route не включает платный fallback.[1][2][14]

Native Codex endpoint закреплён на `https://chatgpt.com/backend-api/codex`; transport/auth failure не выбирает новый endpoint.[14][15]

Codex adapter не отправляет серверный output-token cap: `max_tokens` — hint, **не hard spending/output limit**. Host acceptance deadline/size limits не гарантируют мгновенное прекращение blocked DNS/I/O или удалённой computation/billing.[1][14]

### Opt-in retention, durable jobs и document scan

Events/episodes сохраняют приватные excerpts: это отдельное разрешение, не обязательная часть локального поиска. Сначала выберите retention/scope; YAML extraction может оставаться выключенным.[4][16]

```dotenv
MEMORY_WIKI_EVENT_LEDGER_ENABLED=1
MEMORY_WIKI_EVENT_SCOPE=chat
MEMORY_WIKI_EVENT_TTL_DAYS=30
MEMORY_WIKI_EVENT_MAX_ROWS=20000
MEMORY_WIKI_EVENT_MAX_BYTES=32000000
MEMORY_WIKI_EPISODIC_ENABLED=1
MEMORY_WIKI_EPISODIC_SCOPE=chat
MEMORY_WIKI_EPISODIC_TTL_DAYS=30
MEMORY_WIKI_EPISODIC_PREFETCH=1
MEMORY_WIKI_EPISODIC_PREFETCH_MAX_RESULTS=5
MEMORY_WIKI_EPISODIC_PREFETCH_MAX_CHARS=2400
MEMORY_WIKI_BACKGROUND_JOBS_ENABLED=1
MEMORY_WIKI_BACKGROUND_DAILY_JOBS=100
MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS=10
MEMORY_WIKI_BACKGROUND_LEASE_SECONDS=120
MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS=3
MEMORY_WIKI_BACKGROUND_POLL_SECONDS=10
```

Daily requests ограничивает nominal leased jobs, **не все API calls, цену или provider quota**. Failed jobs могут повториться в пределах attempts; semantic outbox — отдельный путь. Worker работает пока owner/backend доступен, а не как обещание вечного сервиса. TTL не заменяет erasure. Observations default-on само по себе не включает event ledger или episodes.[3][4][16]

Для автоматического cache scan нужны разрешённые roots и project/access scope. Дополнительные roots на Windows разделяются `;`. Scoped документы ищите explicit scoped query: automatic document prefetch использует `global_only=true`, а не снимает ACL. Scan имеет call/cooldown gate, не самостоятельный daemon. OCR/Tika/semantic embedding имеют отдельные prerequisites; не включайте их одним общим флагом. Полные документные/code/worker controls — в [каталоге](#каталог-env-параметров).

### Precedence, типы и реальные лимиты доставки

1. **Host config:** defaults → user YAML → managed overlay; строковые `${VAR}` могут раскрываться host loader. Это не универсальный ENV override каждого leaf.[10]
2. **PluginContext.get_config:** plugin-relative `settings` leaf → legacy `config` leaf → default; global/cross-plugin/reserved root paths запрещены.[6][7]
3. **Wiki session:** raw owner `settings.extraction` авторитетен. Present disabled/malformed section не включается `MW_EXTRACTION_*`; legacy доступен при absent section только для genuine standalone/proven launch owner.[1]
4. **Wiki graph model:** own `MEMORY_WIKI_GRAPH_EXTRACT_MODEL` → process ENV только при proven launch owner → YAML model. Present empty/invalid override — ошибка, не fallback; override меняет только model, не provider/enablement/timeout. Graph auto enrichment дополнительно требует `MEMORY_WIKI_GRAPH_AUTO_EXTRACT=1` и eligibility/deadline gates.[2][3]
5. **Raw extraction sections** не раскрывают `${...}` model placeholders через host defaults/managed overlay. Literal model ID заменяют до записи.[1][2]
6. **ENV-only settings:** bare UPPER_SNAKE `hermes config set MEMORY_WIKI_… VALUE` пишет `.env`; это не доказательство nested YAML reader. Не переносите чужие ENV в routed multiplexer process.[10][11][19]

Gateway root-scalar bridge заполняет лишь gaps process ENV; это не универсальное применение nested YAML. CLI mirror имеет собственный ограниченный набор полей.[17][18]

Используйте unquoted YAML booleans и integer caps. Неположительный host character cap возвращает default, не unlimited.[8][20]

У host spill строка `"false"` truthy; у `memory.prefetch_spill_enabled` строка `"true"` не равна boolean `true`.[8][9]

Wiki ENV helpers обычно clamp-ят числа; strict extraction YAML отвергает bad types/ranges. Empty не всегда false: `SEMANTIC=` не выключает semantic path, `STRICT_RECALL=off` не отключает этот reader.[1][2][3]

Wiki рассчитывает бюджет **целого serialized relevant block**: при enabled spill `min(Wiki cap, owner hooks.output_spill.max_chars)`; wrapper/signature включены. При нехватке места удаляются целые units, не срезается готовый block. Doc/code budgets не складываются поверх общего cap. Host default max_chars — `10000`, Wiki default — `16000`; согласованные `16000` в примере — target, не обещание full prompt.[3][8][9]

`memory.prefetch_spill_enabled:false` не значит «spill выключен»: Core повышает receiving ceiling до `max(max_chars*10,100000)`, но Wiki по-прежнему учитывает свой owner host cap. Overflow возвращает в model-bound content preview/path, не только сокращает UI; середина автоматически не восстанавливается. Manager кеширует spill dict при `add_provider`: YAML save не доказывает новое loaded value. Activation отдельно, без private-cache mutation и самовольного restart.[3][8][9]

Не путайте `CONTEXT_MAX_*` XML/debug renderer с основным explicit pack; `FTS_TOP_K`/`HYBRID_TOP_K` declaration-only в root runtime, `MEMORY_WIKI_CODE_GRAPH` status-only. Эти имена не доказывают универсальный enable/cap control. Продолжайте сохранять strict recall, redaction, ACL и legacy/shared gates; больший preset не является native/release admission.

**Граница проверки:** examples и readers проверяются как документация; доступность модели, квота/цена, installed dependencies, реальная latency/качество, сохранённые и загруженные значения конкретного ПК этим не доказываются. Ничего из этого раздела автоматически не применяется к профилям.

Sources и полный каталог: [ADVANCED_SETTINGS.md](#каталог-env-параметров).


## Loaded source identity — не настройка

Ни `.env`, ни `config.yaml` не должны содержать `loaded_source_revision_known`: это result field, а не control. Restart сам по себе не превращает неподдержанную/непроверенную привязку в доказательство.

Bounded контракт `loaded_source_binding.version=2` (import snapshot, не current-code attestation):

| Поле | Значение и смысл |
|---|---|
| `status`, `reason` | `import_snapshot / current_callable_fields_not_checked`, `drifted / runtime_binding_changed` либо `unavailable` с безопасной enum-причиной |
| `scope`, `observation` | `compiled_entrypoint`, `import_time`: только root Python entrypoint и callable snapshot при import; не текущие поля функций и не dependency bundle |
| `import_snapshot_known` | `true` только после полного typed import match; исторический snapshot остаётся известен и при обнаруженном позднем drift |
| `current_callable_fields_known` | всегда `false` в этом контракте; audited current fields не читаются обоими producers |
| `unchecked_callable_fields` | `code`, `defaults`, `kwdefaults_binding`, `annotation_binding`; включает code/default поля retained annotation/wrapper функций |
| `runtime_checks` | module/namespace и declaration slots, `__wrapped__`, содержимое сохранённого kwdefault dict и сохранённые closure cells; не актуальность самого code/default/annotation binding |
| `revision_kind`, `source_sha256` | `code_matched_source_sha256` и raw SHA256 source, который при import совпал с actual module CodeType по полному typed content |
| `git_revision` | `null`; Git HEAD/документация/install PIN не используются как loaded proof |
| `full_bundle_known`, `exact_loader_bytes_known` | `false`; не подтверждены остальные модули/SDK и точные байты, ранее прочитанные loader |
| `disk_freshness` | `not_checked_after_import`; request не делает I/O для актуализации диска |

Флаг `loaded_source_revision_known` остаётся **`false` даже при здоровом import_snapshot**. Сильная current-callable attestation в no-new-terminal-hooks контракте не доказана; нельзя превращать import-time match в утверждение о текущих полях функций. При import source ограничен 2,000,000 bytes: обычный no-link/no-reparse файл с согласованной до/после read physical identity; compile выполняется без исполнения заново. CPython CodeType сравнивается по filename, flags, argument/local/stack metadata, bytecode, line/exception tables и всем вложенным typed constants, включая tuple/frozenset, float bits, slices и annotation code. Неизвестная форма или неподдержанный runtime отказывает. SOURCE packet не является native plugin boot.

При import читаются code/default/kwdefault поля функций и связываются с actual module CodeType; эти getters в CPython вызывают audit callbacks. Поэтому поздние producers **не читают их повторно**, не вызывают annotation thunk и не пытаются обойти audit guard. Сохраняются проверки module/declaration/descriptor и `__wrapped__`, mutation исходного kwdefault dict/closure cells. Замена code/default/kwdefault object/annotation binding после import остаётся **UNKNOWN**, а не гарантированно обнаруженным drift. Mutable application data, внутреннее содержимое mutable defaults, instance shadowing, dependency state и hostile in-process tampering также не аттестуются. Диагностика не снимает owner, ACL, profile, original context, native transaction и late-delivery fences.

Обычный identity, normal authority и pinned terminal identity используют **один и тот же ограниченный snapshot контракт**; healthy anchor не расходится. Terminal не вызывает новый helper/diagnostic callback, audited callable getter или annotation thunk и не добавляет SQL/source/Git reads сверх исходного body. Если файл после import заменён или удалён, digest описывает старую code-backed import-привязку, не новое installed содержимое. Compile-equivalent raw bytes могут дать одну code projection: digest описывает проверенный source candidate, **не exact loader-byte receipt**. Два docs-only commits не получают выдуманный `git_revision`.

Без import match возвращается `unavailable / import_attestation_unavailable`; missing/nonregular/read-refused source, wrong module/spec и несовпадение full compiled content имеют отдельные причины. Import-time `RuntimeError` от introspection даёт `unavailable / import_introspection_refused`, не доказательство current code. Failure не печатает paths, source text или exception details. **Обнаруживаемый** drift даёт `drifted` обоим producers; не наблюдаемые current fields остаются явно UNKNOWN. Terminal не заходит в заменённый `_runtime_identity` callback и не лечится одним расширенным except. Native boot, новые install/reload, full-suite и loaded fleet требуют собственных разрешений и receipts.

## Совместимость current plugin fixes

Это source/component checkpoint на runtime/tests PIN
`37afe64af95421a735c584e71f8717976393976d`, не новая installed/loaded версия.
Добавление публикационной документации не является повторным выполнением этих
тестов. Saved ENV/YAML, модели, credentials, ACL, schema и профили этим текстом
не меняются; loaded identity сохраняет описанные выше known=false ограничения.

Graph effects сохраняют исходные actor/source admissions и frozen background-job
lease у actual owning transaction до native COMMIT, включая legal joined ingest.
Shared/private writers проверяют поздний authorizer после пользовательского
callback. Поддержанные authorizers возвращают именно builtin `int` с
`SQLITE_OK`, `SQLITE_DENY` или `SQLITE_IGNORE`; user-defined `__index__` после
fence не принимается. Connection statements cache отключён при выдаче handle
(`cached_statements=0`), чтобы SQL/cursor/context shortcuts достигали той же
границы; отдельное измерение performance этой настройки не выполнено.

**Trace/progress callbacks при завершении graph stage не поддержаны:** такой
COMMIT отказывает с `graph_native_commit_late_callback_unsupported`, а не
игнорирует callback или объявляет его атомарно защищённым. Reentrant transaction
completion/изменение authorizer/закрытие handle во время graph COMMIT запрещены.
Обычные поддержанные shared/private writer positives сохранены; отказ вызывает
rollback всей пачки endpoints/relations либо retained exact owner/primary при
неподтверждённом cleanup. Это не универсальный SQLite sandbox или защита от
hostile in-process вмешательства через несогласованный native API.

Guarded recall не делает сохранённый текст инструкцией для модели. Operative
directives отсекаются, benign discussion/literal data и owned formatter prefix
сохраняются в проверенных случаях; bounded refill использует настоящий SQL
eligibility до LIMIT и final admission. Это не доказательство универсального
распознавания любой формулировки prompt injection. Memory Diff не подтверждает
проверенные actor/polarity swaps; неоднозначные Unicode identity случаи остаются
неподтверждёнными, не лечатся переписыванием literals.

Публичный `memory_wiki_query` удаляет internal `_rerank_order` после построения
результата, не меняя internal ordinals/guards. Prefetch diagnostic выбранного
fallback/empty outcome публикуется только исходным owning terminal admission;
detached/late worker не должен заменить выбранный trace. Эти contracts не
исполняют Core MemoryManager/bootstrap и не устраняют ограничения Core;
Core/SDK/PM source не изменялись. Full native, loaded fleet, CI и релиз требуют
своих отдельных проверок. Сводка counts и execution scope — в [README](../README.md#current-plugin-fixes--проверенный-source-checkpoint-не-релиз).

## Каталог ENV-параметров

143 уникальных осей из действующих readers; выборка, а не обещание полного списка всех internal/fault flags. Default относится к отсутствующему ключу. Тип и условие важнее имени: имя переменной само по себе не доказывает effect. Preset не включает все флаги.

### Обозначения readers и типов

- `M` — `__init__.py`.
- `B` — `background_jobs.py`.
- `X` — `extractor.py`.
- `D` — `document_knowledge_graph.py`.
- `K` — `code_knowledge_graph.py`.
- `G` — `entity_relation_extractor.py`.
- `E` — `memory_events.py`.
- `P` — `episodic_memory.py`.
- `O` — `memory_observations.py`.
- `V` — `vault.py`.
- `W` — `document_worker.py`.
- `F` — `document_extractors.py`.
- Чтение `I`: Import os.environ; не hot reload.
- Чтение `C`: Call-time os.environ; saved .env != loaded ENV.
- Чтение `O`: M:1610-1709 owner .env + nested scope; чужие routes/keys не наследуются.
- Чтение `R`: M:3708-3788 detached owner rerank snapshot; invalid -> disabled.
- Чтение `D`: D:82-150 owner DOCUMENT_ snapshot; foreign defaults/узкий allowlist. Worker ENV: D:851-866.
- Чтение `N`: Constructor/initialize; host kwargs выше ENV (M:7089-7099).
- Чтение `X`: X:227-306 own YAML extraction > MW_*; ambient legacy только launch home.
- Чтение `G`: G:28-63;M:22270: own YAML graph; own MODEL override до validation; auto gate отдельно.
- Чтение `L`: M:23155 own .env allowlist; ambient только без файла; generic YAML не grant.
- Чтение `F`: M:1509-1534 own public .env > ambient process; global policy.
- Тип `i/f[lo,hi]`: Clamp; обычный int malformed/empty -> default. ! raw import parse может raise. R empty/bad numeric -> весь rerank disabled; D float без finite-check.
- Тип `bY`: strip+lower; true=1/true/yes/on; другое=false.
- Тип `bYn`: bY без strip.
- Тип `bY3n`: Без strip: true=1/true/yes.
- Тип `bN`: strip+lower; false=0/false/no/off; empty/другое=true.
- Тип `bNn`: bN без strip.
- Тип `bN0`: bN, но empty=false.
- Тип `bN3n`: Без strip: false=0/false/no; empty/off=true.
- Тип `bR`: Import bN0; owner override принимает conventional bool/empty, bad -> весь rerank disabled.
- Тип `str/secret`: Empty/fallback индивидуальны; secrets не включены. | = варианты. Missing bool -> row default.

### Условия, затраты и безопасность

- `conditions:p` — Recall safe bounded; CONTEXT_* = XML/debug. Не full prompt.
- `conditions:e` — Semantic+owner contract+валидные vectors/route+ACL.
- `conditions:r` — Enabled+own key+safe top-K+query 12..cap+deadline/circuit; local fallback.
- `conditions:ev` — Ledger opt-in; host capture; chat/bot/project ACL.
- `conditions:ep` — Episode retention отдельно; prefetch opt-in при нехватке claims; semantic отдельный gate.
- `conditions:ob` — Derived retained events; O.enabled positive bool; empty caller gate отличается.
- `conditions:j` — Worker init M:7244; leases/budget profile/day UTC; requests!=все API calls.
- `conditions:d` — Explicit parsing/scan; cache-only default; auto требует scope; args могут override.
- `conditions:k` — Explicitly indexed code, не crawler; CODE_GRAPH status-only.
- `conditions:g` — Eligible public/current claim; YAML above legacy; exact own MODEL override; auto отдельно.
- `conditions:l` — Explicit pack; secondary LLM opt-in; sessions отдельный gate.
- `conditions:a` — Privacy/policy flags; no native admission bypass.
- `conditions:x` — YAML absent+launch home: MW_* legacy. Disabled LLM оставляет heuristic.
- `conditions:s` — Credential importer fallback OR/NOUS; foreign требует собственные explicit keys/routes.
- `cost:C` — Local CPU/RAM/disk.
- `cost:E` — Conditional embedding API/Qdrant; может стоить денег.
- `cost:R` — Conditional remote rerank cost/quota.
- `cost:X` — Conditional LLM inference/API/quota.
- `cost:J` — Local queue; extraction/graph могут вызвать LLM.
- `cost:D` — Local parser/scan/OCR; отдельные semantic/rerank/Tika gates.
- `security:A` — ACL/guard/native admission.
- `security:S` — Owner credential; не URL/log/prompt.
- `security:W` — Shared/legacy opt-in; оставить off без допуска.
- `security:P` — Private retention; TTL != erasure.
- `security:F` — Roots/scope/repository/resource boundary.
- `security:U` — HTTPS/loopback, credential-free URL; Tika отдельный validator.
- `security:H` — Manifest/reindex contract; slug != capacity.

### Параметры и actual readers

| ENV | Code default | Тип/диапазон | Reader → consumer | Conditions / cost / security |
|---|---|---|---|---|
| `MEMORY_WIKI_MAX_PREFETCH_CHARS` | `16000` | `i[4000,60000]` | `M:5915/I` → `M:8001 _prefetch_delivery_budget` | p / C / A |
| `MEMORY_WIKI_PREFETCH_CLAIM_LIMIT` | `12` | `i[5,50]` | `M:3904/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_CANDIDATE_LIMIT` | `claim_limit*expansion_factor (36 at defaults)` | `i[PREFETCH_CLAIM_LIMIT,200]` | `M:3911/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_EXPANSION_FACTOR` | `3` | `i[1,10]` | `M:3910/I` → `M:3911 PREFETCH_CANDIDATE_LIMIT expression` | p / C / A |
| `MEMORY_WIKI_PREFETCH_CLAIM_MAX_CHARS` | `1200` | `i[300,2400]` | `M:3917/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_EVIDENCE_MAX_CHARS` | `600` | `i[0,1600]` | `M:3918/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CLAIMS` | `4` | `i[0,20]` | `M:3908/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CHARS` | `2000` | `i[0,12000]` | `M:3909/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_DIAGNOSTICS` | `anomalies` | `off\|anomalies\|always` | `M:3920/I` → `M:8277 _prefetch_impl` | p / C / A |
| `MEMORY_WIKI_PREFETCH_DEADLINE_SECONDS` | `5.5` | `f[5.0,6.0]` | `M:3546/I` → `M:8113 prefetch` | p / C / A |
| `MEMORY_WIKI_CONTEXT_MAX_TOKENS` | `4000` | `i[800,32000]` | `M:3928/I` → `M:18979 _pack_selected_claims` | p / C / A |
| `MEMORY_WIKI_CONTEXT_MAX_CLAIMS` | `24` | `i[4,50]` | `M:3929/I` → `M:18979 _pack_selected_claims` | p / C / A |
| `MEMORY_WIKI_CONTEXT_MAX_PER_TOPIC` | `8` | `i[2,20]` | `M:3930/I` → `M:18979 _pack_selected_claims` | p / C / A |
| `MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC` | `8` | `i[3,20]` | `M:3924/I` → `M:18953 _apply_diversity` | p / C / A |
| `MEMORY_WIKI_DIVERSITY_MAX_SOURCE_SHARE` | `0.65` | `f[0.2,1.0]` | `M:3925/I` → `M:18953 _apply_diversity` | p / C / A |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | `i[10,1000]` | `M:3902/I` → `M:19838 _search` | p / C / A |
| `MEMORY_WIKI_REVISION_DELTA_LIMIT` | `3` | `i[0,4]` | `M:8289,23263/C` → `[2, 61]` | p / C / A |
| `MEMORY_WIKI_SEMANTIC` | `true` | `bNn` | `M:3479/I` → `M:5709 _semantic_available` | e / E / A |
| `MEMORY_WIKI_EMBED_PROVIDER` | `openrouter` | `openrouter\|nous\|stub` | `M:1033/I` → `M:4359 _openrouter_embed` | e / E / A |
| `MEMORY_WIKI_EMBED_URL` | `{"openrouter": "https://openrouter.ai/api/v1", "nous": "https://inference-api.nousresearch.com/v1", "stub": "http://127.0.0.1:4000"}` | `str` | `M:1042/I` → `M:4359 _openrouter_embed` | e / E / U |
| `MEMORY_WIKI_EMBED_MODEL` | `{"openrouter/nous": "qwen/qwen3-embedding-8b", "stub": "hash-ngram-{EMBED_DIMENSIONS}"}` | `str` | `M:1070/I` → `M:4359 _openrouter_embed` | e / E / H |
| `MEMORY_WIKI_EMBED_API_KEY` | `EMBED_API_KEY` | `secret` | `M:1732/IO` → `M:1731 _embed_api_key` | e / E / S |
| `MEMORY_WIKI_EMBED_DIMENSIONS` | `4096` | `i[8,65536]` | `M:1063/I` → `M:4359 _openrouter_embed` | e / E / H |
| `MEMORY_WIKI_VECTOR_SIZE` | `4096` | `i[8,65536]` | `M:1453/I` → `M:4250 _validate_embedding_vector` | e / E / H |
| `MEMORY_WIKI_EMBED_INPUT_MAX_CHARS` | `12000` | `i[256,131072]` | `M:1064/I` → `M:4359 _openrouter_embed` | e / E / A |
| `MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES` | `512` | `i[0,10000]` | `M:1075/I` → `M:1257 _embedding_cached_call` | e / E / A |
| `MEMORY_WIKI_QUERY_INSTRUCTION` | `Retrieve durable personal infrastructure facts, preferences, decisions and operational context relevant to the user's request.` | `str` | `M:1405/I` → `M:4271 _embed_for_qdrant` | e / E / H |
| `MEMORY_WIKI_DOCUMENT_PREFIX` | `` | `str` | `M:1410/I` → `M:4271 _embed_for_qdrant` | e / E / H |
| `MEMORY_WIKI_OUTBOX_BATCH_SIZE` | `8` | `i[1,200]!` | `M:2004/I` → `M:3426 _outbox_worker_loop` | e / E / A |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | `str` | `M:1418/IO` → `M:1751 _qdrant_url` | e / E / U |
| `MEMORY_WIKI_QDRANT_COLLECTION` | `memory_wiki_claims` | `str` | `M:1419/IO` → `M:1755 _qdrant_collection` | e / E / A |
| `MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION` | `EPISODIC_QDRANT_COLLECTION` | `str` | `M:1760/IO` → `M:1759 _episodic_qdrant_collection` | e / E / A |
| `MEMORY_WIKI_QDRANT_ALIAS` | `QDRANT_ALIAS` | `str` | `M:1764/IO` → `M:1763 _qdrant_alias` | e / E / A |
| `MEMORY_WIKI_QDRANT_ALIAS_MODE` | `QDRANT_ALIAS_MODE` | `auto\|require\|physical` | `M:1768/IO` → `M:1767 _qdrant_alias_mode` | e / E / A |
| `MEMORY_WIKI_QDRANT_API_KEY` | `` | `secret` | `M:1448/IO` → `M:1771 _qdrant_api_key` | e / E / S |
| `MEMORY_WIKI_RERANK_ENABLED` | `false` | `bR` | `M:3517/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_URL` | `https://openrouter.ai/api/v1/rerank` | `str` | `M:3518/IR` → `M:19071 _rerank_rows` | r / R / U |
| `MEMORY_WIKI_RERANK_MODEL` | `voyageai/rerank-2.5` | `str` | `M:3521/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_API_KEY` | `RERANK_API_KEY` | `secret` | `M:1740/IR` → `M:1735 _rerank_api_key` | r / R / S |
| `MEMORY_WIKI_RERANK_API_STYLE` | `auto` | `auto\|openrouter\|voyage` | `M:3523/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_TOP_K` | `30` | `i[5,100]` | `M:3532/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_MIN_CANDIDATES` | `8` | `i[3,RERANK_TOP_K]` | `M:3533/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_TIMEOUT` | `3.0` | `f[0.25,4.0]` | `M:3537/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_CACHE_TTL` | `1800` | `i[0,86400]` | `M:3538/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_DOCUMENT_MAX_CHARS` | `2600` | `i[600,16000]` | `M:3542/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_RULES_ENABLED` | `"rerank-2.5" in model` | `bR` | `M:3606/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_RERANK_RULES_POSITION` | `prepend` | `prepend\|append` | `M:3611/IR` → `M:19071 _rerank_rows` | r / R / A |
| `MEMORY_WIKI_EVENT_LEDGER_ENABLED` | `false` | `bY` | `E:32/C` → `E:30 enabled` | ev / C / P |
| `MEMORY_WIKI_EVENT_SCOPE` | `EPISODIC_SCOPE or chat (missing only)` | `chat\|bot\|project` | `M:8887/C` → `M:8866 sync_turn` | ev / C / P |
| `MEMORY_WIKI_EVENT_TTL_DAYS` | `90` | `i[1,3650]` | `E:873/C` → `E:797 capture_event` | ev / C / P |
| `MEMORY_WIKI_EVENT_MAX_ROWS` | `20000` | `i[1,10000000]` | `E:613/C` → `E:581 prune_events` | ev / C / P |
| `MEMORY_WIKI_EVENT_MAX_BYTES` | `32000000` | `i[16384,16000000000]` | `E:614/C` → `E:581 prune_events` | ev / C / P |
| `MEMORY_WIKI_EVENT_MAX_CONTENT` | `4000` | `i[128,16000]` | `E:845/C` → `E:797 capture_event` | ev / C / P |
| `MEMORY_WIKI_EPISODIC_ENABLED` | `false` | `bYn` | `P:27/C` → `P:26 enabled` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_SCOPE` | `chat` | `chat\|bot` | `P:31/C` → `P:30 _scope` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_PREFETCH` | `false` | `bYn` | `M:8498/C` → `M:8277 _prefetch_impl` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_RESULTS` | `5` | `i[1,8]` | `M:8488/C` → `M:8277 _prefetch_impl` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_CHARS` | `2400` | `i[350,8000]` | `M:8491/C` → `M:8277 _prefetch_impl` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_SEMANTIC` | `false` | `bY` | `M:3487/C` → `M:3483 _episodic_semantic_enabled` | ep / E / P |
| `MEMORY_WIKI_EPISODIC_TTL_DAYS` | `30` | `i[1,365]` | `P:503/C` → `P:472 capture_turn` | ep / C / P |
| `MEMORY_WIKI_EPISODIC_MAX_ROWS` | `5000` | `i[1,20000]` | `P:530/C` → `P:472 capture_turn` | ep / C / P |
| `MEMORY_WIKI_OBSERVATIONS_ENABLED` | `true` | `bY` | `O:48/C` → `O:46 enabled` | ob / C / P |
| `MEMORY_WIKI_OBSERVATION_TTL_DAYS` | `365` | `i[1,3650]` | `O:738/C` → `O:700 _write_version` | ob / C / P |
| `MEMORY_WIKI_OBSERVATION_MAX_ROWS` | `10000` | `i[1,100000]` | `O:1713/C` → `O:1664 prune_observations` | ob / C / P |
| `MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH` | `64` | `i[1,1000]` | `B:669/C` → `B:614 _run_job` | ob / C / P |
| `MEMORY_WIKI_OBSERVATION_BACKGROUND_SECONDS` | `5.0` | `f[0.05,60.0]` | `O:889/C` → `O:879 _consolidate_events` | ob / C / P |
| `MEMORY_WIKI_BACKGROUND_JOBS_ENABLED` | `false` | `bY` | `B:37/C` → `B:36 enabled` | j / J / A |
| `MEMORY_WIKI_BACKGROUND_POLL_SECONDS` | `10` | `i[1,300]` | `B:941/C` → `B:933 Worker._run` | j / J / A |
| `MEMORY_WIKI_BACKGROUND_LEASE_SECONDS` | `120` | `i[30,1800]` | `B:218/C` → `B:214 JobStore.lease` | j / J / A |
| `MEMORY_WIKI_BACKGROUND_DAILY_JOBS` | `500` | `i[1,100000]` | `B:219/C` → `B:214 JobStore.lease` | j / J / A |
| `MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS` | `100` | `i[1,100000]` | `B:220/C` → `B:214 JobStore.lease` | j / J / A |
| `MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS` | `5` | `i[1,20]` | `B:234/C` → `B:214 JobStore.lease` | j / J / A |
| `MEMORY_WIKI_DOCUMENT_CACHE_DIR` | `` | `str` | `D:288/D` → `D:286 _document_cache_root` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_ROOTS` | `` | `str` | `D:297/D` → `D:296 _roots` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID` | `` | `str` | `D:332/D` → `D:324 _document_access_scope` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE` | `false` | `bN0` | `D:345/D` → `D:324 _document_access_scope` | d / D / W |
| `MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION` | `false` | `bN0` | `D:1861/D` → `D:1853 _assert_ingest_source_scope` | d / D / W |
| `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE` | `false` | `bN0` | `D:2864/D` → `D:2857 document_cache_scan_journal_ready` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID` | `` | `str` | `D:2873/D` → `D:2857 document_cache_scan_journal_ready` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_ALLOW_GLOBAL_AUTO` | `false` | `bN0` | `D:2874/D` → `D:2857 document_cache_scan_journal_ready` | d / D / W |
| `MEMORY_WIKI_DOCUMENT_AUTO_EMBED` | `false` | `bN0` | `D:1619,2912/D` → `D:2877 maybe_ingest_document_cache` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST` | `false` | `bN0` | `D:2519/D` → `D:2225 ingest_document` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS` | `15` | `i[1,3600]` | `D:2869/D` → `D:2857 document_cache_scan_journal_ready` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_FILES` | `200` | `i[1,5000]` | `D:2906/D` → `D:2877 maybe_ingest_document_cache` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_CHANGED` | `3` | `i[1,100]` | `D:2907/D` → `D:2877 maybe_ingest_document_cache` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_AUTO_TRUST_STAT_FAST_PATH` | `false` | `bN0` | `D:2909/D` → `D:2877 maybe_ingest_document_cache` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_ALLOW_STAT_FAST_PATH` | `false` | `bN0` | `D:2742/D` → `D:2639 scan_documents` | d / D / W |
| `MEMORY_WIKI_DOCUMENT_SCAN_MAX_FILES` | `5000` | `i[1,100000]` | `D:2650/D` → `D:2639 scan_documents` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_SCAN_MAX_SECONDS` | `30.0` | `f[0.1,600.0]` | `D:2657/D` → `D:2639 scan_documents` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_PREFETCH` | `true` | `bN0` | `D:3789/D` → `D:3788 maybe_prefetch_document_context` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_PREFETCH_HITS` | `6` | `i[1,15]` | `D:3794/D` → `D:3788 maybe_prefetch_document_context` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_PREFETCH_CHARS` | `7000` | `i[1000,24000]` | `M:8339/C` → `M:8277 _prefetch_impl` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_RERANK` | `true` | `bN0` | `D:3340/D` → `D:3208 query_documents` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_OCR` | `false` | `bN0` | `D:2911/D` → `D:2877 maybe_ingest_document_cache` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_MAX_BYTES` | `134217728` | `i[1000000,2000000000]` | `D:834/D` → `D:828 _worker_options` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB` | `1024` | `i[128,16384]` | `D:1071/D,W:38/C` → `D:1069 _windows_worker_limit_config` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_WORKER_CPU_SECONDS` | `120` | `i[5,3600]` | `D:1072/D,W:39/C` → `D:1069 _windows_worker_limit_config` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT` | `180` | `i[10,1800]` | `D:1311/D` → `D:1309 _extract` | d / D / F |
| `MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB` | `512` | `i[8,4096]` | `D:1313/D,W:40/C` → `D:1309 _extract` | d / D / F |
| `MEMORY_WIKI_TIKA_URL` | `` | `str` | `D:847/D` → `D:828 _worker_options` | d / D / F |
| `MEMORY_WIKI_CODE_GRAPH` | `true` | `bN0` | `K:2945/C` → `K:2914 _code_graph_status_on_connection` | k / C / A |
| `MEMORY_WIKI_CODE_GRAPH_EMBED` | `true` | `bN0` | `K:1864/C` → `K:1843 _embed_graph_chunks` | k / E / A |
| `MEMORY_WIKI_CODE_GRAPH_EMBED_MAX_UNITS` | `2000` | `i[0,10000]` | `K:1866/C` → `K:1843 _embed_graph_chunks` | k / E / A |
| `MEMORY_WIKI_CODE_GRAPH_RERANK` | `true` | `bN0` | `K:2736/C` → `K:2597 _query_code_graph_on_connection` | k / E / A |
| `MEMORY_WIKI_CODE_GRAPH_PREFETCH` | `true` | `bN0` | `K:3205/C` → `K:3204 maybe_prefetch_code_context` | k / E / A |
| `MEMORY_WIKI_CODE_GRAPH_PREFETCH_CHARS` | `8000` | `i[1000,24000]` | `M:8331/C` → `M:8277 _prefetch_impl` | k / E / A |
| `MEMORY_WIKI_GRAPH_EXTRACT_ENABLED` | `false` | `bYn` | `M:22311/G` → `M:22299 _graph_extract_claim` | g / X / A |
| `MEMORY_WIKI_GRAPH_EXTRACT_URL` | `LLM_BASE_URL or https://openrouter.ai/api/v1` | `str` | `M:22329/G` → `M:22299 _graph_extract_claim` | g / X / U |
| `MEMORY_WIKI_GRAPH_EXTRACT_MODEL` | `LLM_MODEL or empty (legacy); YAML model otherwise` | `str` | `M:22336/G` → `M:22299 _graph_extract_claim` | g / X / A |
| `MEMORY_WIKI_GRAPH_EXTRACT_API_KEY` | `` | `secret` | `M:22342/G` → `M:22299 _graph_extract_claim` | g / X / S |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT` | `false` | `bY` | `M:9369/G` → `M:9367 relevant_graph_extraction_settings` | g / X / A |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT_MAX_CLAIMS` | `2` | `i[1,4]` | `M:9412/C` → `M:9390 _auto_graph_enrich_extracted_claims` | g / X / A |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT_TOTAL_DEADLINE_SECONDS` | `12.0` | `f[1,30]` | `M:9414/C` → `M:9390 _auto_graph_enrich_extracted_claims` | g / X / A |
| `MEMORY_WIKI_LLM_PACK` | `false` | `bYn` | `M:23180/L` → `M:23155 _llm_pack_context` | l / X / A |
| `MEMORY_WIKI_LLM_BASE_URL` | `http://127.0.0.1:18646/v1` | `str` | `M:23185/L` → `M:23155 _llm_pack_context` | l / X / U |
| `MEMORY_WIKI_LLM_MODEL` | `gpt-5.5` | `str` | `M:23187/L` → `M:23155 _llm_pack_context` | l / X / A |
| `MEMORY_WIKI_LLM_API_KEY` | `` | `secret` | `M:23186/L` → `M:23155 _llm_pack_context` | l / X / S |
| `MEMORY_WIKI_LLM_TIMEOUT` | `45.0` | `f[1,60]` | `M:23215/L` → `M:23155 _llm_pack_context` | l / X / A |
| `MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK` | `false` | `bY3n` | `M:23507/C` → `M:23234 _pack_context` | l / X / A |
| `MEMORY_WIKI_DEFAULT_VISIBILITY` | `global` | `global\|bot\|chat\|project\|private` | `M:6875,7098/N` → `M:7475 _default_visibility_for` | a / C / A |
| `MEMORY_WIKI_STRICT_RECALL` | `true` | `bN3n` | `M:7014/C` → `M:7001 _claim_metadata_eligibility_sql` | a / C / A |
| `MEMORY_WIKI_SUPPRESSION_FAIL_CLOSED` | `true` | `bN` | `M:10288/C` → `M:9724 handle_tool_call` | a / C / A |
| `MEMORY_WIKI_BLOCK_RAW_VAULT_READS` | `true` | `bN` | `M:24650/C` → `M:24648 _vault_raw_access_guard` | a / C / A |
| `MEMORY_WIKI_ALLOW_SHARED_RECOVERY` | `false` | `bYn` | `M:22595/C` → `M:22587 _transaction` | a / C / W |
| `MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA` | `false` | `bYn` | `M:21242/C` → `M:21239 _query_secrets` | a / C / W |
| `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH` | `false` | `bYn` | `M:22167/C` → `M:22163 _graph_row_visible` | a / C / W |
| `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_PREFERENCES` | `false` | `bYn` | `M:22997/C` → `M:22977 _import_bundle` | a / C / W |
| `MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX` | `false` | `bY` | `M:21256/C` → `M:21239 _query_secrets` | a / C / W |
| `MEMORY_WIKI_GLOBAL_SEARCH_ENABLED` | `false` | `bY` | `M:1517/F` → `M:1509 _global_search_settings` | a / C / A |
| `MW_EXTRACTION_ENABLED` | `false` | `bY` | `X:202/X` → `X:199 _settings` | x / X / A |
| `MW_EXTRACTION_MODEL` | `openai/gpt-4.1-mini` | `str` | `X:203/X` → `X:199 _settings` | x / X / A |
| `MW_EXTRACTION_BASE_URL` | `https://openrouter.ai/api/v1/chat/completions` | `str` | `X:204/X` → `X:199 _settings` | x / X / U |
| `MW_EXTRACTION_API_KEY` | `` | `secret` | `X:205/X` → `X:199 _settings` | x / X / S |
| `MW_EXTRACTION_TIMEOUT` | `30` | `i[1,60]` | `X:206/X` → `X:199 _settings` | x / X / A |
| `MW_EXTRACTION_MAX_TOKENS` | `1800` | `i[256,3000]` | `X:207/X` → `X:199 _settings` | x / X / A |
| `OPENROUTER_API_KEY` | `` | `secret` | `M:3522/I` → `M:4359 _openrouter_embed` | s / C / S |
| `NOUS_API_KEY` | `` | `secret` | `M:1048/I` → `M:4359 _openrouter_embed` | s / C / S |
| `HERMES_SECURITY_STRICT` | `true` | `bNn` | `M:1026/I,8999/C` → `M:8986 _inspect_recall_text` | s / C / A |
| `HERMES_ALLOW_LEGACY_VAULT` | `false` | `bY3n` | `V:4/I` → `V:4 legacy import gate` | s / C / W |
| `HERMES_DOCUMENT_CACHE_DIR` | `` | `str` | `D:289/D` → `D:286 _document_cache_root` | d / D / F |
| `MEMORY_WIKI_EMBED_QUERY_CACHE_TTL_SECONDS` | `86400` | `i[0,2592000]` | `M:1076/I` → `M:1257 _embedding_cached_call` | e / C/E / H |
| `MEMORY_WIKI_EMBED_DOCUMENT_CACHE_TTL_SECONDS` | `2592000` | `i[0,31536000]` | `M:1077/I` → `M:1257 _embedding_cached_call` | e / C/E / H |
| `MEMORY_WIKI_EMBED_CACHE_SINGLEFLIGHT_WAIT_SECONDS` | `45` | `i[1,120]` | `M:1079/I` → `M:1257 _embedding_cached_call` | e / C/E / H |

Declaration/status-only controls не превращаются в функциональные switches; scoped documents не попадают в global-only automatic prefetch. `CONTEXT_MAX_*` относится к XML/debug renderer, основной explicit pack имеет собственные arguments. Полный numeric range reader не означает, что выбранная модель/сервис его поддерживает.

## Sources

[1] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/extractor.py — extractor.py
[2] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/entity_relation_extractor.py — entity_relation_extractor.py
[3] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/__init__.py — __init__.py
[4] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/background_jobs.py — background_jobs.py
[5] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/plugin.yaml — plugin.yaml
[6] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/plugins.py — hermes_cli/plugins.py
[7] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/plugins_state.py — hermes_cli/plugins_state.py
[8] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/tools/hook_output_spill.py — tools/hook_output_spill.py
[9] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/agent/memory_manager.py — agent/memory_manager.py
[10] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/config.py — hermes_cli/config.py
[11] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/config_env_routing.py — hermes_cli/config_env_routing.py
[12] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/config_defaults.py — hermes_cli/config_defaults.py
[13] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/agent/agent_init.py — agent/agent_init.py
[14] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/agent/auxiliary_client.py — agent/auxiliary_client.py
[15] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/agent/codex_headers.py — agent/codex_headers.py
[16] https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/3b77376b9098584538962977f227940e7e183ec3/memory_events.py — memory_events.py
[17] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/gateway/run.py — gateway/run.py
[18] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/cli_config_load.py — hermes_cli/cli_config_load.py
[19] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/hermes_cli/env_loader.py — hermes_cli/env_loader.py
[20] https://github.com/NousResearch/hermes-agent/blob/79b45d1647f6b5680768d851c4c406e8cc550a1e/tools/tool_output_limits.py — tools/tool_output_limits.py
