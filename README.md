# Hermes Memory-Wiki

**Нативная долговременная память для AI-агентов на [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

SQLite FTS5 + Qdrant vectors + RRF hybrid search. Никаких внешних сервисов, только stdlib Python.

---

## Оглавление

- [Что это](#что-это)
- [Почему не RAG](#почему-не-rag)
- [Архитектура](#архитектура)
- [Структура репозитория](#структура-репозитория)
- [Быстрый старт](#быстрый-старт)
- [Гибридный поиск](#гибридный-поиск)
- [Инструменты](#инструменты)
- [Verification pipeline](#verification-pipeline)
- [Write Firewall](#write-firewall)
- [Journal и Recovery](#journal-и-recovery)
- [ENV-переменные](#env-переменные)
- [Smoke-тесты](#smoke-тесты)
- [Требования](#требования)
- [Лицензия](#лицензия)

---

## Что это

Memory-wiki — не просто база заметок. Это **подсистема оперативной памяти** для AI-агента, которая живёт внутри Hermes как нативный MemoryProvider и plugin:

- **Каждый факт (claim)** хранится с confidence, salience, freshness, trust class, evidence
- **FTS5** даёт точный lexical-поиск — слова, коды, пути, endpoints, команды
- **Qdrant vectors** дают смысловой semantic-поиск — похожие концепции, даже если слова разные
- **RRF (Reciprocal Rank Fusion)** объединяет оба слоя в единый ranked-результат
- **Авто-detection query mode**: технические запросы → FTS вес выше; смысловые → vector вес выше
- **Memory Diff Before Answer**: перед ответом сравнивает воспоминания с проверенными фактами
- **Write Firewall 2.0**: source policy + quality lint + secret scan перед durable-записью
- **Preference Priority Layer**: явные пользовательские инструкции приоритетнее старых фактов
- **Append-only JSONL journal** с hash-chain + logical checkpoints для recovery
- **Верификация**: curated-источники авто-verified, conversation-источники — unverified
- **Contradiction handling**: конфликтующие факты записываются явно, а не сосуществуют молча
- **Secret firewall**: секреты детектятся → quarantined → redacted recall

> Это source-only репозиторий. Рантайм-данные (SQLite БД, бэкапы, секреты, сессии, логи) исключены через `.gitignore`.

---

## Почему не RAG

**Кратко:** RAG достаёт документы. Memory-wiki управляет памятью агента.

| Измерение | Типичный RAG | Memory-wiki |
|---|---|---|
| **Единица хранения** | Чанк/документ | Claim, evidence, preference, task capsule, decision, secret metadata, graph relation |
| **Жизненный цикл** | Обычно нет | Active / retired / superseded / uncertain / queued / review |
| **Trust/качество** | source score | Confidence + salience + freshness + trust class + evidence + usage feedback |
| **Конфликты** | Оба текста в выдаче | Contradiction rows → policy/manual resolution |
| **Секреты** | Часто не защищены | Secret scan → quarantine → redacted recall |
| **Операционная память** | Нет | Task capsules, project profiles, mistakes, decisions, mutation log |
| **Вывод** | matching chunks | Sectioned pack_context: preferences / procedures / projects / diff / contradictions |
| **Обслуживание** | Реиндексация | Doctor / repair / backup / restore / FTS rebuild / topic normalization / compiler |
| **Интеграция** | Внешний retriever | Native Hermes MemoryProvider + plugin tools |
| **Recovery** | Переиндексация | Journal replay + SQLite rebuild из чекпоинтов |

Memory-wiki **использует** RAG-техники внутри (FTS5, semantic search, RRF), но его задача шире: держать многомесячную память агента полезной, аудируемой, курируемой, восстанавливаемой и безопасной.

### Сравнение с другими подсистемами памяти Hermes

| Подсистема | Что хранит | Поиск | Срок жизни | Верификация |
|---|---|---|---|---|
| **Memory-wiki** | Факты, уроки, предпочтения, конфиги | Lexical + Semantic + RRF | Постоянно | ✅ curated→verified |
| `memory` tool | Сырой текст профиля | Инжект в промпт | Сессии | ❌ |
| `distill` | Сжатые капсулы разговоров | FTS по ключам | Сессии + TTL | ❌ |
| `plur` | Эпизодические энграммы | Cosine similarity | Сезонно (ACT-R decay) | ❌ |
| `secret-vault` | Креденшелы, токены, ключи | По ID | Постоянно (зашифровано) | ❌ |

---

## Архитектура

```
┌─────────────────────────────────────────────────────┐
│                  Hermes Agent                        │
│  ┌───────────────────────────────────────────────┐  │
│  │          MemoryWikiProvider                    │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │           Recall Planner                 │  │  │
│  │  │  query → detect mode → plan topics/types │  │  │
│  │  └──────────────┬──────────────────────────┘  │  │
│  │                 │                              │  │
│  │     ┌───────────┴───────────┐                  │  │
│  │     ▼                       ▼                  │  │
│  │  ┌─────────┐          ┌──────────┐             │  │
│  │  │  FTS5   │          │ Qdrant   │             │  │
│  │  │ lexical │          │ semantic │             │  │
│  │  │ BM25    │          │ cosine   │             │  │
│  │  └────┬────┘          └────┬─────┘             │  │
│  │       │                    │                   │  │
│  │       └────────┬───────────┘                   │  │
│  │                ▼                               │  │
│  │         ┌─────────────┐                        │  │
│  │         │ RRF fusion  │                        │  │
│  │         │ k=60, веса  │                        │  │
│  │         └──────┬──────┘                        │  │
│  │                ▼                               │  │
│  │     ┌─────────────────────┐                    │  │
│  │     │  pack_context       │                    │  │
│  │     │  sectioned output   │                    │  │
│  │     │  → agent prompt     │                    │  │
│  │     └─────────────────────┘                    │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  Write path (tool result / explicit write)     │  │
│  │  scrub → redact → firewall → SQLite + journal  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘

Внешние сервисы (опционально):
  semantic/embed_stub.py  →  :4000  character n-gram hashing
  semantic/qdrant_stub.py →  :6333  JSON vector store
```

**Ключевые таблицы SQLite:** `claims`, `evidence`, `contradictions`, `secret_index`, `secret_quarantine`, `entities`, `relations`, `task_capsules`, `decisions`, `mistakes`, `project_profiles`, `preference_rules`, `recall_events`, `review_queue`, `mutation_log`, `audit_log`

**Никакого ИИ.** Embedding-stub и Qdrant-stub — чистый Python stdlib, character n-gram hashing + cosine similarity. Без GPU, без нейросетей, без внешних API.

---

## Структура репозитория

```
hermes-memory-wiki/
├── __init__.py              # MemoryProvider plugin (~3900 строк)
├── plugin.yaml              # Метаданные плагина (v1.4.0, Hermes)
│
├── scripts/
│   ├── smoke_test.py        # End-to-end smoke suite (72 схемы, 6 audit events)
│   └── memory_wiki_cli.py   # Standalone CLI для maintenance без запуска Hermes
│
├── semantic/                # Semantic search backend (stdlib-only)
│   ├── embed_stub.py        # Embedding-сервер (:4000), character n-gram hashing, 768-dim
│   └── qdrant_stub.py       # Qdrant-совместимая векторная БД (:6333), JSON-хранилище
│
├── README.md
├── LICENSE                  # MIT
└── .gitignore               # Исключает runtime DB, бэкапы, секреты
```

---

## Быстрый старт

### Установка плагина

```bash
# Клонировать в Hermes plugins
mkdir -p ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git \
  ~/.hermes/plugins/memory-wiki
```

### Поднять semantic-сервисы (опционально)

```bash
cd ~/.hermes/plugins/memory-wiki/semantic

# Оба — чистый Python stdlib
python3 embed_stub.py &    # → http://127.0.0.1:4000
python3 qdrant_stub.py &   # → http://127.0.0.1:6333
```

Без них memory-wiki работает в FTS-only режиме.

### Включить в Hermes

В `~/.hermes/config.yaml`:

```yaml
memory:
  provider: memory-wiki

plugins:
  enabled:
    - memory-wiki
```

Перезапустить Hermes.

### Проверить установку

```bash
cd ~/.hermes/plugins/memory-wiki

# Синтаксис
python3 -m py_compile __init__.py \
  scripts/smoke_test.py \
  scripts/memory_wiki_cli.py \
  semantic/embed_stub.py \
  semantic/qdrant_stub.py

# Smoke-тест (без LLM, без CDP, полностью офлайн)
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py
```

Ожидаемый вывод:

```json
{
  "ok": true,
  "home": "removed",
  "backup": "/tmp/memorywiki_smoke_xxxxxx/memory-wiki/backups/bak_...zip",
  "schemas": 72,
  "audit_events": 6
}
```

### Standalone CLI (без Hermes)

```bash
cd ~/.hermes/plugins/memory-wiki

# Полная диагностика
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor

# Поиск
python3 scripts/memory_wiki_cli.py --home ~/.hermes query "project configuration" --limit 10

# Сбор контекста для LLM
python3 scripts/memory_wiki_cli.py --home ~/.hermes pack \
  "какой контекст нужен для задачи" --max-chars 3800

# Бэкап
python3 scripts/memory_wiki_cli.py --home ~/.hermes backup --reason manual

# Dashboard
python3 scripts/memory_wiki_cli.py --home ~/.hermes dashboard

# Ремонт
python3 scripts/memory_wiki_cli.py --home ~/.hermes repair --target fts --apply
```

---

## Гибридный поиск

```
user query
  │
  ├─► query mode detection (technical / semantic / mixed)
  │     technical: слова, коды, пути → lexical вес 0.85
  │     semantic:  идеи, концепции   → vector вес  0.85
  │     mixed:     и то и другое     → balanced (0.5/0.5)
  │
  ├─► FTS5 top-200 (lexical, BM25 rank)
  │     точные совпадения по словам, кодам, путям
  │
  ├─► Qdrant vector top-200 (semantic, cosine)
  │     смысловые совпадения даже при разных словах
  │
  ├─► RRF fusion (k=60, авто-веса по режиму)
  │     RRF_score = Σ 1/(k + rank_i)  для каждого источника
  │
  └─► score_breakdown per claim
        confidence, salience, verified_boost, freshness, rrf
```

### Режимы запросов

```bash
# Включить debug-лог для анализа поиска
MEMORY_WIKI_DEBUG=1
# → /tmp/memory_wiki_debug.log
# Содержит: query, query_mode, FTS candidates, vector candidates, RRF fused count
```

---

## Инструменты

Версия 1.4.0 — **72 инструмента**. Ниже — основные группы.

### Поиск и контекст
| Инструмент | Описание |
|---|---|
| `memory_wiki_query` | Гибридный поиск (FTS5 + Qdrant + RRF) |
| `memory_wiki_pack_context` | Сбор релевантного контекста для LLM |
| `memory_wiki_memory_diff` | Сравнение воспоминаний с проверенными фактами |
| `memory_wiki_recall_plan` | План: какие топики/типы/секреты достать |
| `memory_wiki_preference_layer` | Слой приоритетов пользователя |
| `memory_wiki_mark_used` | Обратная связь: полезность recall |
| `memory_wiki_debug_search` | Поиск с разблюдовкой по слоям |
| `memory_wiki_compare_search` | FTS-only vs hybrid сравнение |
| `memory_wiki_query_mode` | Определение типа запроса |

### Запись и обновление
| Инструмент | Описание |
|---|---|
| `memory_wiki_add_claim` | Сохранить факт |
| `memory_wiki_add_evidence` | Добавить evidence к claim |
| `memory_wiki_update_claim` | Обновить confidence/salience/freshness |
| `memory_wiki_rewrite_claim` | Переписать claim in-place |
| `memory_wiki_merge_claims` | Слить дубликаты |
| `memory_wiki_pin_claim` | Закрепить claim |

### Контроль качества
| Инструмент | Описание |
|---|---|
| `memory_wiki_review_queue` | Очередь на проверку (list/approve/reject/rewrite) |
| `memory_wiki_lint_claim` | Линтинг кандидата |
| `memory_wiki_write_firewall` | Проверка перед durable-записью |
| `memory_wiki_source_policy` | Политика приёма по источнику |
| `memory_wiki_normalize_topics` | Нормализация топиков |
| `memory_wiki_immune_scan` | Авто-детект проблем: секреты, блобы, битые топики |
| `memory_wiki_compile_topic` | Компиляция микро-claimов в curated summary |
| `memory_wiki_compress_topic` | Сжатие топика + supersede старых |

### Конфликты и provenance
| Инструмент | Описание |
|---|---|
| `memory_wiki_contradict` | Записать конфликт |
| `memory_wiki_resolve_contradiction` | Ручное разрешение |
| `memory_wiki_resolve_by_policy` | Авто-разрешение по политике (prefer_explicit_user / prefer_recent / prefer_verified) |
| `memory_wiki_why_believe` | Provenance card: evidence, trust, contradictions |

### Операционная память
| Инструмент | Описание |
|---|---|
| `memory_wiki_add_decision` | Записать решение |
| `memory_wiki_add_mistake` | Записать ошибку + fix + prevention |
| `memory_wiki_add_project_profile` | Профиль проекта |
| `memory_wiki_get_project_context` | Контекст проекта |
| `memory_wiki_add_task_capsule` | Капсула задачи (план, файлы, команды, верификация) |
| `memory_wiki_add_preference_rule` | Правило приоритета пользователя |

### Graph memory
| Инструмент | Описание |
|---|---|
| `memory_wiki_add_entity` | Создать сущность |
| `memory_wiki_add_relation` | Создать связь |
| `memory_wiki_graph_query` | Поиск по графу |

### Секреты
| Инструмент | Описание |
|---|---|
| `memory_wiki_add_secret` | Добавить в secret index (redacted по умолчанию) |
| `memory_wiki_query_secrets` | Поиск по secret index (reveal=false → redacted) |
| `memory_wiki_secret_quarantine` | Карантин секретов |

### Обслуживание и recovery
| Инструмент | Описание |
|---|---|
| `memory_wiki_health` | Быстрая проверка |
| `memory_wiki_doctor` | Полная диагностика (таблицы, FTS, WAL, топики, journal) |
| `memory_wiki_repair` | Восстановление (fts / integrity / dashboards / all) |
| `memory_wiki_backup` | Бэкап SQLite + vault |
| `memory_wiki_list_backups` | Список бэкапов |
| `memory_wiki_restore` | Восстановление из бэкапа |
| `memory_wiki_snapshot` | Человеко-читаемый снепшот |
| `memory_wiki_audit_log` | Аудит-лог |
| `memory_wiki_mutation_log` | Журнал мутаций (before/after) |
| `memory_wiki_undo_last` | Откат последней мутации |
| `memory_wiki_transaction` | Batch-операции с dry-run |
| `memory_wiki_journal_status` | Статус JSONL journal + hash-chain |
| `memory_wiki_journal_checkpoint` | Создать logical checkpoint |
| `memory_wiki_rebuild_from_journal` | Восстановить SQLite из journal |
| `memory_wiki_semantic_status` | Здоровье embedding/Qdrant |
| `memory_wiki_reindex` | Переиндексация в Qdrant |
| `memory_wiki_evaluate_retrieval` | Recall@k, MRR, NDCG метрики |

---

## Verification pipeline

```
Источник claim
  │
  ├─► curated (post_task, task_capsule, decision, mistake, project)
  │     → auto-verified ✅ (boost +0.35)
  │
  ├─► tool (результат проверенной команды, конфиг)
  │     → probable (boost +0.15)
  │
  ├─► explicit_user (прямая инструкция)
  │     → verified ✅ (boost +0.50)
  │
  └─► conversation / unknown
        → unverified ⚠️ (no boost, флаг на review)
```

Проверенные claim'ы получают scoring-буст и считаются authoritative при conflict resolution.

---

## Write Firewall

Перед durable-записью каждый claim проходит:

1. **Source policy** — tool/task/decision → пропускать; raw/blob → queue
2. **Quality lint** — проверка на:
   - Артефакты (truncation markers, prompt wrappers)
   - Пустые claims
   - Системный мусор (interim_assistant, gateway wrappers)
3. **Secret scan** — если найден ключ/пароль → quarantine, в claims не класть
4. **Deduplication** — поиск похожих claims перед записью

Режимы: `check` (dry-run), `queue` (в review_queue), `apply` (прямая запись).

---

## Journal и Recovery

```
Каждая мутация (write/update/delete)
  │
  ▼
append-only JSONL journal  (hash-chain: prev_hash → row_hash)
  │
  ▼  (периодически)
logical checkpoint (SQLite-совместимый снепшот таблиц)
```

### Восстановление

```bash
# Шаг 1: проверить journal
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor

# Шаг 2: если SQLite повреждён — перестроить из последнего checkpoint + journal
# (через Hermes tool):
# memory_wiki_rebuild_from_journal apply=true

# Шаг 3: верифицировать
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor
```

---

## ENV-переменные

| Переменная | Default | Описание |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Вкл/выкл semantic search |
| `MEMORY_WIKI_RRF_K` | `60` | RRF константа |
| `MEMORY_WIKI_FTS_TOP_K` | `200` | Lexical candidates до fusion |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | Semantic candidates до fusion |
| `MEMORY_WIKI_HYBRID_TOP_K` | `100` | Hybrid candidates после fusion |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embedding-stub endpoint |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant-stub endpoint |
| `MEMORY_WIKI_DEBUG` | `0` | Debug-лог → `/tmp/memory_wiki_debug.log` |
| `MEMORY_WIKI_LLM_PACK` | `0` | LLM-рефайнмент контекста |
| `MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK` | `0` | Включать историю сессий в pack_context |
| `MEMORY_WIKI_STRICT_RECALL` | `1` | Strict active/non-stale recall |
| `MEMORY_WIKI_MAX_PREFETCH_CHARS` | `12000` | Макс. символов в prefetch |

---

## Smoke-тесты

Smoke-тест не требует ни LLM, ни CDP, ни сети:

```bash
cd ~/.hermes/plugins/memory-wiki

# Базовый
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py

# С изолированным home (без влияния на реальную БД)
tmp_home=$(mktemp -d)
HERMES_HOME="$tmp_home" MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py
```

**Что проверяется:**
- Загрузка плагина через `importlib`
- 72 tool schema (все зарегистрированы)
- Claim CRUD: add → query → update → merge
- Evidence: add → why_believe
- Contradictions: detect → resolve
- Secrets: add → redacted query → revealed query → no leak
- Lint, review_queue, decisions, mistakes, project profiles
- Task capsules, graph memory (entities + relations)
- Preference layer, memory_diff
- Journal: status → checkpoint
- Import/export bundles
- Бэкап, снепшот, audit_log, mutation_log
- doctor, health, repair
- Semantic status
- Безопасность: zip-slip protection, secret redaction во всех output-путях

---

## Требования

- **Python 3.10+** — используется только stdlib
- **SQLite 3.35+** — для FTS5
- **Hermes Agent** — как MemoryProvider plugin
- **semantic/embed_stub.py + semantic/qdrant_stub.py** — опционально, для гибридного поиска

---

## Лицензия

MIT. См. [`LICENSE`](LICENSE).

---

## Development

```bash
# Синтаксис
python3 -m py_compile __init__.py \
  scripts/smoke_test.py \
  scripts/memory_wiki_cli.py \
  semantic/embed_stub.py \
  semantic/qdrant_stub.py

# Smoke
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py

# Schema count (быстрая проверка)
python3 - <<'PY'
import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location('mw', '__init__.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
os.environ['HERMES_HOME'] = tempfile.mkdtemp(prefix='mw_dev_')
p = mod.MemoryWikiProvider()
p.initialize('dev')
print(len(p.get_tool_schemas()))  # → 72
PY
```

При изменении schema-полей обновлять **все** эти слои:
- SQLite migrations
- Import/export/sync bundle paths
- FTS rebuild/upsert logic
- pack_context rendering
- Doctor/repair checks
- Smoke tests
