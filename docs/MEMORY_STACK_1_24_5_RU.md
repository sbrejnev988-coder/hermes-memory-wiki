# Memory Stack 1.24.5: переносимый гайд для Hermes

## Новый RI-R01 / hybrid SOURCE checkpoint

Подготовлен **локальный публикационный кандидат поверх current main**, не новый tag/GitHub Release и не выполненная установка. Приняты cumulative runtime SOURCE bytes; текущий пакет отдельно проверяет переносимые carrier regressions и offline wheel correspondence. Схемы 121, DDL/migrations и версия 1.24.5 не повышены. Исходный owner, raw source images, private reader lifetime, serialization/cleanup ordering и primary UNKNOWN не превращаются в разрешение на live/native execution.

Точные primary E и metadata-only secondary M указываются последующим doc-only binding после создания настоящих commits; raw SHA256 source никогда не используется как Git PIN. Пока remote readback этих новых refs не выполнен, они не называются опубликованными или пригодными для remote install. Старые E42d2/M02eed и current-main 6a748/a503 — исторические checkpoints, не current feature PIN. Сканирование, install/PM/liveness, собственные rollout markers и owner reload проверяются координатором отдельно.

Регрессионные границы и cold-process prerequisites: [TEST_CONTRACT.md](TEST_CONTRACT.md). SOURCE-only PASS, package readback, сохранённые settings, installed source и loaded/runtime/full-recovery — разные доказательства.

> **Целевой режим, а не отчёт «всё уже работает».** Memory Wiki — долгосрочная память; LCM-X — история и сжатие контекста; PPLX — независимая оценка результатов. Ни версии, ни saved settings не доказывают загрузку работающим процессом, полноту индекса, native lifecycle или восстановление данных.

## 1. Статус и точные исходники

На этапе обновления 6 октября 2026 года исходники Wiki опубликованы; Wiki 1.24.5, LCM-X 0.25.1 и PPLX 0.1.8 установлены штатным installer во всех пяти согласованных профилях. Parent readback подтвердил 15 установленных targets и 355 сохранённых memory-setting значений: по 8 YAML и 63 ENV на профиль, с сохранением собственных моделей, ключей, paths и aliases. Это подтверждение **installed/saved**, не native feature acceptance, не полная проверка восстановления и не успешный CI/runtime всего релиза. Перезапуск оставлен владельцу. Для другого ПК дальнейший текст остаётся целевым preset, а не заявлением о его настройке.

| Компонент | Публичный источник и immutable PIN | Назначение |
|---|---|---|
| Wiki 1.24.5, исторический buildable source **E** | [репозиторий](https://github.com/sbrejnev988-coder/hermes-memory-wiki), [`42d2e943f887efda00d65ebf143adce28873103e`](https://github.com/sbrejnev988-coder/hermes-memory-wiki/commit/42d2e943f887efda00d65ebf143adce28873103e) | Native plugin/provider `memory-wiki` |
| Wiki 1.24.5, исторический secondary metadata-only source **M** | [тот же репозиторий](https://github.com/sbrejnev988-coder/hermes-memory-wiki), [`02eed6da5b5cdba02a4fb114534730067e2d21ea`](https://github.com/sbrejnev988-coder/hermes-memory-wiki/commit/02eed6da5b5cdba02a4fb114534730067e2d21ea) | Подготовленный до admission virtual PM member; runtime payload сохранён |
| LCM-X 0.25.1 | [официальный v0.25.1](https://github.com/electricsheephq/lcm-x/releases/tag/v0.25.1), [`f47b55e031b507b424ff5f480d8f2a80d358f1f0`](https://github.com/electricsheephq/lcm-x/commit/f47b55e031b507b424ff5f480d8f2a80d358f1f0) | Plugin `hermes-lcm-x`, `context.engine: lcm-x`; YAML-раздел остаётся `lcm`, tools — `lcm_*` |
| PPLX reviewer 0.1.8 | [репозиторий](https://github.com/sbrejnev988-coder/pplx-decider-review), [`4b61c8631031dfee30b9240adfb16d27ea6d80c2`](https://github.com/sbrejnev988-coder/pplx-decider-review/commit/4b61c8631031dfee30b9240adfb16d27ea6d80c2) | Plugin `pplx-decider-review`; не поиск и не разрешение на действия |

Для Wiki 1.24.5 и PPLX 0.1.8 этим этапом не создавались tag/GitHub Release. Наличие официального Release LCM-X не принимает интеграцию другого ПК. Ссылки выше — заданные source bindings, не новая проверка GitHub этим гайдом; оператор перед установкой сверяет доступность exact PIN и состояние remote самостоятельно.

### Один shared PM, разные владельцы

В подготовленной композиции одна Wiki-copy buildable, четыре secondary — virtual по **M**, без `[build-system]` и без `tool.uv.package=true`. `[project]`, distribution name, зависимости и runtime не переименовываются. Secondary не получает standalone wheel contract без build metadata.

**PIN M и рабочий bound source URL каждого secondary фиксируются до admission.** На новом ПК сначала обнаружить собственные URL в native install metadata; не исправлять malformed token молча и не копировать alias другого профиля. Если прежний URL не работает либо владелец явно выбирает другой origin, разрешён отдельно проверенный **source replacement через штатный installer**: новые URL/PIN фиксирует сам installer; оригиналы и user-owned files сохраняются, полный merged payload проходит scanner/readback. Именно такой переход на публичный GitHub source использован в этом code-stage. Canonical source equality сама не доказывает carry при смене origin. Не править installed TOML после admission, PM lock/facts или install metadata. Конфликт duplicate distributions — STOP, а не повод вручную изменить установленный plugin.

Текущий doc-only update не меняет runtime, schemas, metadata или tests этих PIN. Старые заметки [1.24.0](RELEASE_NOTES_1_24_0_RU.md), [packing source-only](PREFETCH_PACKING_SOURCE_ONLY_RU.md) и [deployment runbook](HERMES-AGENT-DEPLOYMENT.md) сохраняют исторические наблюдения; их прежние статусы не заменяют текущую матрицу этапов в [1.24.5 notes](RELEASE_NOTES_1_24_5_RU.md).

## 2. Предварительные условия и границы

1. Обнаружить версию Hermes, выбранный native PM/interpreter, разрешённые профили и настоящий backend owner. На Windows пути для native программ брать из discovery; не переносить чужой home и не предполагать `~/.hermes`. Несколько профилей могут обслуживаться одним multiplexer.
2. Согласовать exact source/PIN, replacement, PM dependencies/capabilities, сеть/квоту для embeddings, rerank, extraction и reviewer **отдельно**. Этот гайд не разрешает платные canary, hosted CI, reindex или миграцию aliases.
3. Сохранить профильные модели, credential bindings, OAuth, main/delegation/auxiliary routes, PPLX mode/thresholds и инструкции. Значения моделей, credentials, auth stores, data paths и идентификаторы владельцев не входят в публичный preset.
4. Требуемые действующей strict policy trust/loader/secret dependencies должны иметь проверенное происхождение и оставаться доступными. Missing dependency — STOP. Не снижать strict mode, не добавлять sharing/legacy/ACL overrides и не подменять защитные модули.
5. Native scanner сохраняет точный verdict/findings/severity для exact source. `caution` требует отдельного informed consent; `dangerous` блокирует. `--force` не добавлять по умолчанию: в некоторых версиях он одновременно разрешает replacement и принятие caution. Отказ не обходить copy, private helper или security flag.
6. Обнаружить writers/reindex и допустимый quiesce до replacement. Installer/первый load может менять dependency environment, мигрировать store и запускать workers. `--no-enable` **не выключает** уже enabled replacement и не гарантирует отсутствия последующей загрузки.

### Сохранность данных — отдельный договор

Для другого ПК рекомендуется отдельный **ручной owner-run** согласованный backup до обновления: actual stores, journal/checkpoints, recovery artifacts, актуальный privacy-erasure ledger/keys и необходимые sidecars. Кодовая копия, ZIP integrity и scoped snapshot не доказывают full-data recovery; LCM SQLite и externalized payloads — отдельный слой, не backup Wiki.

В описанном code-stage владелец явно отказался от нового Wiki data backup для этой операции. Это решение не переносится на другого оператора и **не закрывает** native/full-recovery gates. Совместимое безопасное whole-store восстановление не доказано; отдельная подготовленная owner-утилита оставляет restore/rollback disabled при `SEMANTIC_REPLACEMENT_UNPROVEN` и не входит в plugin package. Этот гайд не предлагает restore-команд, private SDK helpers или разрешающих флагов. Согласие на code-only не даёт полномочий на разрушительное восстановление, cleanup, sharing или ослабление guards.

## 3. Discovery и native install

Примеры — POSIX/Git Bash. В PowerShell использовать собственный синтаксис аргументов, сохраняя те же native команды. Не запускать их из гайда без разрешения оператора. Launcher может выполнять PM preparation даже перед help; сначала проверить его побочные эффекты и ресурсы.

```bash
hermes --version
hermes profile list
hermes config set --help
hermes config get --help
hermes plugins install --help
hermes plugins enable --help
```

Не придумывать `profile list --json` и не менять sticky profile через `profile use`. Для **одного обнаруженного и разрешённого** профиля задать `$PROFILE` и `$PROFILE_HOME`; home сверить с native discovery:

```bash
hermes profile show "$PROFILE"
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" config path
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" config env-path
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" plugins list --user --json
```

Config home, chat/store owner и backend launch owner — разные идентичности. При несовпадении STOP до разрешения причины. Не печатать config/env/auth целиком.

Scoped helper используется только после discovery, не является sandbox:

```bash
h() {
  : "${PROFILE:?выберите разрешённый профиль}" "${PROFILE_HOME:?обнаружьте его home}"
  HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" "$@"
}
```

Для **нового** source подходят публичные Git URLs:

- `https://github.com/sbrejnev988-coder/hermes-memory-wiki.git`
- `https://github.com/electricsheephq/lcm-x.git`
- `https://github.com/sbrejnev988-coder/pplx-decider-review.git`

Для уже установленного target сохранить его собственный exact bound URL; особенно secondary Wiki aliases. До запуска определить `$WIKI_SOURCE_URL`, `$WIKI_PIN` (E либо M по принятой PM матрице), `$LCM_SOURCE_URL`, `$PPLX_SOURCE_URL`. PIN — ровно полный 40-character Git SHA, не branch, tag или «похожая» исправленная строка.

После review, scanner/PM consent и решения о сохранности, для нового/доказанно неактивного target:

```bash
h plugins install "$WIKI_SOURCE_URL" --ref "$WIKI_PIN" --no-enable
h plugins install "$LCM_SOURCE_URL" --ref f47b55e031b507b424ff5f480d8f2a80d358f1f0 --no-enable
h plugins install "$PPLX_SOURCE_URL" --ref 4b61c8631031dfee30b9240adfb16d27ea6d80c2 --no-enable
h plugins list --user --json
```

При existing replacement выбирать дополнительные флаги только по своему verified help и отдельным решениям владельца. Не переключать source URL ради удобства, не использовать `--no-deps` как доказательство readiness и не устанавливать Qdrant через plugin installer. Если PM общий, выполнять install-транзакции последовательно и заново обнаруживать selected interpreter после каждой.

Readback до конфигурации: собственные installed PIN/version, полный tracked payload/blobs/modes, native enabled state, provider directory selection, virtual/buildable shape. Сверить сохранность unrelated config/auth без публикации их содержимого. Если code-stage уже установлен, doc update сам по себе не требует reinstall.

На согласованном этапе совместимости `plugins doctor <id> --ci` относится к отдельной проверке и может загрузить код. Он не доказывает новый model call, capture, compaction, prompt delivery или recovery; не запускать его скрыто под видом metadata-only чтения, когда tests/native execution отложены.

После admission выбрать уже проверенные native surfaces, не новый GUI/MCP/worker:

```bash
h plugins enable memory-wiki --no-allow-tool-override
h plugins enable hermes-lcm-x --no-allow-tool-override
h plugins enable pplx-decider-review --no-allow-tool-override
h config set memory.provider memory-wiki
h config set context.engine lcm-x
```

Это **selection prerequisites**, а не дополнительные поля общего preset ниже. Уже правильный выбор не переписывать. Не держать одновременно две enabled LCM generations. Registration PPLX не включает его policy `settings.enabled`; существующую собственную policy сохранить, для нового owner настроить её отдельно после egress consent по [PPLX README](https://github.com/sbrejnev988-coder/pplx-decider-review/blob/4b61c8631031dfee30b9240adfb16d27ea6d80c2/README.md).

## 4. Ровно 8 YAML targets

Это allowlist отдельных leaves, **не replacement config**. Перед записью extraction должен уже иметь валидные собственные provider/model/reasoning settings; не заменять раздел примером чужого маршрута.

| Dotted key | Тип | Target |
|---|---|---|
| `compression.enabled` | bool | `true` |
| `compression.threshold` | number | `0.78` |
| `lcm.context_threshold` | number | `0.78` |
| `hooks.output_spill.enabled` | bool | `true` |
| `hooks.output_spill.max_chars` | integer | `15000` |
| `plugins.entries.memory-wiki.settings.extraction.enabled` | bool | `true` |
| `plugins.entries.memory-wiki.settings.extraction.timeout` | integer | `45` |
| `plugins.entries.memory-wiki.settings.extraction.max_tokens` | integer | `3000` |

```bash
h config set compression.enabled true
h config set compression.threshold 0.78
h config set lcm.context_threshold 0.78
h config set hooks.output_spill.enabled true
h config set hooks.output_spill.max_chars 15000
h config set plugins.entries.memory-wiki.settings.extraction.enabled true
h config set plugins.entries.memory-wiki.settings.extraction.timeout 45
h config set plugins.entries.memory-wiki.settings.extraction.max_tokens 3000
```

Сразу после **каждого** set выполнить `h config get <тот-же-dotted-key> --json`, сверить тип и значение, а весь parsed config — с его собственным baseline плюс только разрешённая дельта. `--force` у config writer не доказывает reader support и не является scanner consent.

Для нового явно выбранного ratio preset перед `lcm.context_threshold=0.78` проверить effective overrides: `LCM_CONTEXT_THRESHOLD` отсутствует либо ровно `0.78`; `LCM_ABSOLUTE_THRESHOLD_TOKENS` отсутствует/0; model-threshold maps/presets не заменяют выбранный ratio. Существующие owner overrides, включая absolute threshold `700000`, сохранить: portable ratio/absolute0 не навязывается нынешнему владельцу. Конкурирующий override нельзя молча удалить. Приёмка требует loaded LCM threshold и его source, а не одного YAML readback. `compression.enabled` остаётся global compaction gate; выбор LCM-X не отключает обычное сохранение истории.

Extraction — выборочная работа на поддерживаемых lifecycle boundaries, не LLM на каждом сообщении и не автоматическое подтверждение истины. Timeout 45 — acceptance budget, не гарантия мгновенной отмены OS/remote I/O. Для Codex `max_tokens=3000` — hint, **не server-enforced spending cap**; для OpenRouter действуют собственные валидатор и transport. Не менять transport или добавлять paid fallback.

## 5. Ровно 65 ENV targets

В этом PIN эти параметры читаются через ENV, поэтому их не переводят в придуманные dotted YAML keys. Ниже только non-secret common targets; string literals сохранены точно. Сохранить **каждую** строку через supported profile-local writer:

```bash
h config set MEMORY_WIKI_SEMANTIC 1
# Общий шаблон для одной строки KEY=VALUE из allowlist:
h config set "$KEY" "$VALUE"
```

Не `source`/`eval` блока, не user-wide `setx`, не whole-file copy `.env`. Bare UPPER_SNAKE маршрутизируется native writer в owner ENV surface в проверенном CLI; на другом core сначала подтвердить это help/reader. Для readback использовать **настоящий профильный ENV reader**, а не YAML-копию: native `config get` считать ENV readback лишь если его текущая реализация действительно возвращает этот surface. Иначе approved read-only native dotenv reader проецирует только этот allowlist. Credential checks — presence-only. Saved readback не заменяет effective importer/engine readback после restart.

```env
LCM_RECALL_SCAN_MAX_ROWS=100000
LCM_RECALL_SCAN_BUDGET_S=2.0
MEMORY_WIKI_SEMANTIC=1
MEMORY_WIKI_RRF_K=10
MEMORY_WIKI_VECTOR_TOP_K=200
MEMORY_WIKI_PREFETCH_CLAIM_LIMIT=24
MEMORY_WIKI_PREFETCH_CANDIDATE_LIMIT=200
MEMORY_WIKI_PREFETCH_EXPANSION_FACTOR=3
MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CLAIMS=6
MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CHARS=3000
MEMORY_WIKI_PREFETCH_CLAIM_MAX_CHARS=1200
MEMORY_WIKI_PREFETCH_EVIDENCE_MAX_CHARS=600
MEMORY_WIKI_PREFETCH_DIAGNOSTICS=anomalies
MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC=12
MEMORY_WIKI_DIVERSITY_MAX_SOURCE_SHARE=0.55
MEMORY_WIKI_MAX_PREFETCH_CHARS=48000
MEMORY_WIKI_PREFETCH_DEADLINE_SECONDS=6.0
MEMORY_WIKI_PREFETCH_NETWORK_RESERVE_SECONDS=0.20
MEMORY_WIKI_PREFETCH_FALLBACK_RESERVE_SECONDS=0.60
MEMORY_WIKI_RERANK_ENABLED=1
MEMORY_WIKI_RERANK_TOP_K=48
MEMORY_WIKI_RERANK_MIN_CANDIDATES=10
MEMORY_WIKI_RERANK_TIMEOUT=4
MEMORY_WIKI_RERANK_CACHE_MAX=256
MEMORY_WIKI_RERANK_CACHE_TTL=1800
MEMORY_WIKI_RERANK_CIRCUIT_FAILURES=3
MEMORY_WIKI_RERANK_CIRCUIT_SECONDS=300
MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES=512
MEMORY_WIKI_EMBED_QUERY_CACHE_TTL_SECONDS=86400
MEMORY_WIKI_EMBED_DOCUMENT_CACHE_TTL_SECONDS=2592000
MEMORY_WIKI_OUTBOX_BATCH_SIZE=8
MEMORY_WIKI_OUTBOX_POLL_SECONDS=3.0
MEMORY_WIKI_OUTBOX_LEASE_SECONDS=90
MEMORY_WIKI_OUTBOX_EMBED_DELAY_SECONDS=0.15
MEMORY_WIKI_DOCUMENT_AUTO_EMBED=1
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=0
MEMORY_WIKI_DOCUMENT_PREFETCH=1
MEMORY_WIKI_DOCUMENT_PREFETCH_HITS=8
MEMORY_WIKI_DOCUMENT_PREFETCH_CHARS=8000
MEMORY_WIKI_CODE_GRAPH_PREFETCH=1
MEMORY_WIKI_CODE_GRAPH_PREFETCH_CHARS=8000
MEMORY_WIKI_EPISODIC_PREFETCH=1
MEMORY_WIKI_EPISODIC_PREFETCH_MAX_RESULTS=5
MEMORY_WIKI_EPISODIC_PREFETCH_MAX_CHARS=2400
MEMORY_WIKI_REVISION_DELTA_LIMIT=3
MEMORY_WIKI_GRAPH_AUTO_EXTRACT=1
MEMORY_WIKI_GRAPH_AUTO_EXTRACT_MAX_CLAIMS=2
MEMORY_WIKI_GRAPH_AUTO_EXTRACT_TOTAL_DEADLINE_SECONDS=12
MEMORY_WIKI_BACKGROUND_JOBS_ENABLED=0
MEMORY_WIKI_LLM_PACK=0
LCM_EXPANSION_CONTEXT_TOKENS=64000
LCM_EMBEDDINGS_ENABLED=false
LCM_RERANK_ENABLED=false
LCM_PROACTIVE_RECALL_ENABLED=false
LCM_EXTRACTION_ENABLED=false
LCM_ASSERTIONS_ENABLED=false
LCM_ASSERTION_EXTRACTION_ENABLED=false
LCM_QUERY_VIEWS_ENABLED=false
LCM_ADAPTIVE_RETRIEVAL_ENABLED=false
LCM_PREANSWER_EVIDENCE_ENABLED=false
LCM_SELECTIVE_COMPILER_ENABLED=false
LCM_TEMPORAL_ROLLUPS_ENABLED=false
LCM_DEFERRED_MAINTENANCE_ENABLED=false
LCM_SENSITIVE_PATTERNS_ENABLED=true
LCM_EMBEDDING_PRIVACY_ENABLED=true
```

Для каждого разрешённого профиля сверить exact strings всех 63 ENV targets и 8 YAML targets программно. Число readbacks равно `число обнаруженных разрешённых профилей × 71`; missing/invalid/duplicates не считать PASS. Это матрица saved settings, **не** доказательство loaded runtime. Остальные строки, models/auth/paths/aliases и профильные различия должны остаться прежними.

### Почему это не «поставить все флаги в 1»

- **Wiki retrieval:** SQLite/FTS + semantic Qdrant IDs → owner-safe SQLite hydration → локальный RRF K=10 → при eligibility один rerank до 48 candidates, минимум 10 → diversity → bounded rendered units. Reranker упорядочивает, не устанавливает истинность. При ошибке/timeout применяется локальный fallback, не разрешающий обход guards.
- **Ёмкости:** до 200 vector/prefetch candidates, до 24 основных claims; 6 claims/3000 chars — мягкие relevant-content цели, не padding. Claim/evidence field caps 1200/600 остаются. Диагностика `anomalies`, а не постоянный полный dump.
- **Общая автоматическая доставка — не более 15000 Python characters**, включая claims, metadata, delta, documents, code, episodes, attached shared blocks и wrappers. `48000` — provider ceiling; при enabled host spill фактический ceiling `min(48000, 15000)`. Document/code budgets по 8000 и episodes 2400 **не суммируются** поверх него. Whole rendered units отбрасываются целиком при overflow; upstream field limits не означают сохранение всего исходного graph hit. Actual model-bound delivery ещё требует native наблюдения.
- **Время/кэш:** deadline 6.0 s, fallback reserve 0.60 s, network reserve 0.20 s; rerank timeout до 4 s дополнительно ограничен оставшимся budget. TTL/LRU/circuit уменьшают повторную работу, не обещают постоянную доступность внешних сервисов или бесплатность.
- **Документы:** auto scan attachment cache выключен. Это не post-response queue и не чтение всего filesystem. `DOCUMENT_AUTO_EMBED=1` разрешает embedding только в поддерживаемом ingestion path для выбранных разрешённых документов; ручные ingest/scan и их `embed` semantics проверить по actual schema, scope и бюджету. Automatic document prefetch остаётся global-only; scoped материал запрашивается явно. Document hits=8, code hit count остаётся 6. Не расширять ACL ради заполнения бюджета.
- **Episodes:** prefetch разрешён как fallback существующего owner-scoped episode store. Он не включает capture/semantic episodes сам; существующие `EPISODIC_ENABLED/SEMANTIC`, TTL, scopes и event/observation settings сохранить. Отсутствующий capture не чинить новым флагом без собственного допуска.
- **Graph:** auto enrichment дополнительно требует действующего собственного graph route и grounded eligible новых claims. Max 2, total deadline 12 s не включает этот маршрут автоматически. Session extraction и graph extraction — разные readers; model overrides могут иметь приоритет над YAML. Не унифицировать профильные providers/models/effort.
- **LCM-X:** сохраняет обычную историю/DAG/compaction и ручной recall; дополнительные embeddings, rerank, proactive recall, extraction, assertions/query views/controllers, temporal rollups и deferred maintenance остаются выключены до отдельного opt-in. Не все эти функции платные, но новые store/lifecycle операции здесь не нужны. Privacy flags включены; это не универсальный secret-erasure/security guarantee и не доказательство защиты старой истории.
- **PPLX:** installation/selection не унифицирует review policy. Сохраняются собственные mode, thresholds, routes, key bindings и `agent.pre_verify_all_finals`. Advisory verdict — не факт, не proof исполнения и не разрешение на новый child/tool; DRAFT review не принимается за повторную оценку исправленного final. Native runtime PPLX 0.1.8 проверяется отдельно.

## 6. Индексация: автоматическая очередь, не обещание 100%

Committed eligible безопасный claim обновляет SQLite/FTS/cache revision и transactional semantic outbox. Active content edit инвалидирует прежние targets и ставит delete/upsert; retirement/deletion сохраняет target-specific privacy deletes. Existing outbox worker обрабатывает задачи асинхронно после commit при доступном правильно настроенном owner/backend и providers. **`MEMORY_WIKI_BACKGROUND_JOBS_ENABLED=0` не выключает semantic outbox**: это другая general extraction/maintenance очередь.

Pending review, archived/superseded rows, event/episode evidence и graph/document rows не равны новым active claim points. Revision — изменение состояния, а не число фактов. Edit может заменить vector point без увеличения count; одинаковые aggregate counts не доказывают equality IDs/revisions/payload/ACL.

До вывода «индекс догнал» сверить actual initialized owner store, manifest, alias/physical target, unique eligible IDs, target-matched delivered receipts, indexed revisions и queue states **по object type и operation**. Registry row `active` без подтверждённой доставки не доказывает vector. Episode failure не объявлять claim-index failure. Не отбрасывать outstanding historical privacy-delete из-за более нового upsert.

После retry cap (обычно пять попыток) failed claim upserts не становятся healthy от новых budgets. Нужны отдельная owner-approved диагностика/repair; не сбрасывать failures/leases или запускать reindex автоматически. Не одобрять review queue и не оживлять архив ради растущего счётчика.

Бюджеты не исправляют collision двух owner aliases на одном physical target. До **любого** alias change/reindex нужны native owner/target readback и отдельное решение; имя `SHARED_DB_PATH` также может быть health assertion, не routing. Cached semantic health и point count не принимаются за свежий embedding success или полноту всех индексов.

## 7. Большой ручной контекст — отдельно от auto prefetch

`MEMORY_WIKI_CONTEXT_MAX_TOKENS`, `MEMORY_WIKI_CONTEXT_MAX_CLAIMS` и `MEMORY_WIKI_CONTEXT_MAX_PER_TOPIC` в этом source обслуживают **debug packing**. Они не увеличивают automatic prefetch или canonical public pack; существующие значения не переписываются общим preset.

Для отдельного owner-authorized запроса через native tool:

```json
{"query":"конкретный вопрос владельца","max_tokens":12000,"output_mode":"canonical"}
```

Это аргументы `memory_wiki_pack_context`, не ENV/YAML. Public `max_tokens` принимает 200–15000; host/tool spill может всё равно ограничить доставку. Не использовать deprecated `max_chars` вместо поддерживаемого параметра, не включать отдельный LLM pack ради большего числа.

LCM bounded expansion без вспомогательного synthesis:

```json
{"prompt":"Восстанови точные источники по вопросу владельца","query":"конкретные термины","output":"evidence","context_max_tokens":64000,"max_results":8}
```

Это аргументы `lcm_expand_query`. `LCM_EXPANSION_CONTEXT_TOKENS=64000` — default сериализованного expansion context, **не** размер постоянно активного prompt. `output=answer` запускает auxiliary synthesis и требует своего разрешения/бюджета; `output=evidence` не запускает этот synthesis. Active-session scope по умолчанию не разрешает произвольные чужие sessions. Для обычного поиска доступен `lcm_recall` с `detail=answer_ready`, например limit 12; результаты/цитаты надо читать, не превращать summary в новую истину.

Не настраивать нерабочие aliases: `MEMORY_WIKI_SEMANTIC_ENABLED`, `MEMORY_WIKI_PREFETCH_SEMANTIC`, `MEMORY_WIKI_DECIDER_ENABLED`; не обещать эффект `MEMORY_WIKI_RERANK_RETRY_COUNT` или неиспользуемых FTS/HYBRID top-K. У LCM-X не использовать `lcm.enabled`, `lcm.expansion_context_tokens` или игнорируемый `LCM_NATIVE_RECOVERY`; реальные surfaces указаны выше.

## 8. Credentials и owner-local contracts

Реальные значения вводит владелец только через свою защищённую native setup/Vault/local secret surface, не чат, argv, Git, public report или ENV-блок этого гайда. Не копировать `.env`, auth pools или data между профилями. PPLX использует native owner secret scope; наличие key в чужом process ENV не доказывает доступность reviewer.

Существующий embedding provider/model/endpoint сохраняется. Для описанного 4096D contract сверить actual embedding response dimensions = configured dimensions = vector size = Qdrant target contract (**4096 — длина вектора, не count points**). На новом ПК модель и dimension contract выбираются владельцем отдельно. Не переключать stub на remote, не заменять embedding модель и не менять manifest/alias этим preset. Credential presence не является authenticated server acceptance; Qdrant reachability не доказывает качество поиска.

Главная модель, delegation, compression/extraction/graph routes, generative auxiliary review и PPLX Decisions — независимы. Не переносить персональные model literals, endpoint/key overrides или filesystem roots из чужой машины. Сохранять точный model identifier, не «чинить» строку и не вводить тихий paid fallback.

## 9. Перезапуск делает владелец; затем readbacks

Порядок: **discovery/consent → exact native install/readback → точечный config и saved readbacks → handoff владельцу → owner-run restart → loaded/effective readbacks → отдельно разрешённые runtime/recovery gates**. Fresh CLI не обновляет уже открытый gateway/Desktop.

Wiki retrieval/rerank/cache/outbox constants частично captured при import из process ENV. Document/code char ceilings также могут читать process ENV, хотя некоторые readers owner-local. LCM config captured при engine construction; storage rebind сам его не обновляет. Поэтому одинаковые профильные files не доказывают значения multiplexer importer. Не мутировать `os.environ` в routed request и не создавать дополнительный backend ради обхода.

Владелец обнаруживает настоящий owner каждого обслуживаемого профиля, ждёт завершения согласованных задач и использует штатный lifecycle. Restart messaging gateway не обязательно перезапускает Desktop-owned backend; Reconnect не равен reload. Self-restart guards не обходить. Здесь агент **не** перезапускает владельца. Raw config invalidation не гарантирует обновление cached MemoryManager spill snapshot.

После owner restart собрать профильную матрицу, не один удачный чат:

| Проверка | Что фиксировать локально; что она НЕ доказывает |
|---|---|
| Source и owner | Новый PID/start time, loaded module/source PIN и собственный chat/store/launch owner; manifest version без source не достаточно |
| Selection | `plugins list --user --json`, `config get memory.provider`, `config get context.engine`; YAML/registration не feature proof |
| Saved settings | Все 8 YAML/63 ENV через actual readers; effective process overrides и snapshot отдельно |
| LCM | Native `lcm_status`: version/engine identity, threshold 0.78 и source, privacy settings/active config; tools existence не capture/compaction/recovery proof |
| Wiki budgets | Effective importer constants, owner host cap 15000, getter versus cached host spill snapshot; не private cache patch |
| Prefetch | В рамках отдельно разрешённого наблюдения whole guarded rendered units и финальные counters, budget/deadline/withheld/cancellation, actual model-bound length ≤15000; below-cap пример не доказывает все будущие запросы |
| Semantic targets/outbox | Actual store, dimensions/manifest, alias, delivered target receipts, eligible/indexed revision coverage и pending/processing/failed раздельно; point count не всё здоровье |
| Rerank/extraction/PPLX | Собственные effective routes и уже наблюдённые request/response/usage либо `unknown`; cached success/сохранённый key не свежий API proof |
| Lifecycle/recovery | Отдельно разрешённые capture, compaction, fresh-process raw recovery, ACL/privacy и full-data restore gates; не выводить PASS из установки |

Перед вызовом status handler проверить side effects; обычный native dispatch может сохранить текущий turn даже при read-only handler. Не обещать глобально нулевые writes/network на основании имени tool. Не создавать durable smoke claims, не закрывать чат ради extraction и не форсировать compaction без отдельного согласия.

При расхождении readback сохранить blocker и прекратить зависящие операции, не считать нужное значение «почти применённым». Rollback настроек — только точечная native запись прежнего собственного non-secret value либо unset ранее отсутствовавшего key; старый code PIN должен сохранять собственный source alias/virtual metadata и native admission. Откат кода не откатывает данные или authority удаления; whole-store restore этим гайдом не разрешён.

## 10. Критерий завершения и источники

В отчёте отдельно показать: опубликованный exact source; installed code; saved settings; owner restart; loaded/effective values; фактические runtime и recovery проверки. Пока последний этап не выполнен, корректный статус — **code/settings подготовлены или сохранены; loaded/runtime/recovery неизвестны**, не «все индексы здоровы» или «всё всегда индексируется и попадает в prompt».

Новые GUI, MCP, дополнительные sync workers, security-core/subagent-memory features и LCM extensions не начинать в этой операции. Существующая mandatory protection не откладывается. Для другого бюджета/набора профилей сначала получить новый allowlist, не слепо увеличить каждое число.

Публичные первичные references (на другом ПК сверять актуальную CLI/core версию):

- [Hermes docs index](https://hermes-agent.nousresearch.com/docs/llms.txt), [CLI](https://hermes-agent.nousresearch.com/docs/reference/cli-commands), [configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration), [plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins), [package management](https://hermes-agent.nousresearch.com/docs/reference/package-management).
- [Wiki README exact E](https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/42d2e943f887efda00d65ebf143adce28873103e/README.md), [security policy](../SECURITY.md), [1.24.5 release-stage notes](RELEASE_NOTES_1_24_5_RU.md).
- [LCM-X README exact PIN](https://github.com/electricsheephq/lcm-x/blob/f47b55e031b507b424ff5f480d8f2a80d358f1f0/README.md).
- [PPLX README exact PIN](https://github.com/sbrejnev988-coder/pplx-decider-review/blob/4b61c8631031dfee30b9240adfb16d27ea6d80c2/README.md).

### Saved-only срез лимитов

Target/current saved snapshot: `extraction.max_tokens=3000` (integer), `LCM_RECALL_SCAN_MAX_ROWS=100000` и `LCM_RECALL_SCAN_BUDGET_S=2.0` (ENV strings). Этот срез не доказывает loaded значения. Собственные host spill `15000`, absolute threshold `700000`, модели/маршруты/данные/ACL сохраняются; другой ПК применяет только свой согласованный preset. Scanner/liveness и exact PIN readback обязательны до install; собственный untracked rollout marker сохраняет future native same-source carry, не публикуется в payload.
