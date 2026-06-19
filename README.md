# Hermes Memory-Wiki

**Нативная активная память для Hermes Agent.** SQLite + FTS5 + Qdrant vectors + RRF hybrid search.

## Что это

Memory-wiki — не просто «заметки». Это **подсистема долговременной памяти** внутри Hermes:
- Каждый факт (claim) хранится с confidence, salience, evidence, источником
- FTS5 даёт точный lexical-поиск (слова, коды, пути, endpoints)
- Qdrant vectors дают смысловой semantic-поиск (похожие концепции, даже если слова разные)
- RRF (Reciprocal Rank Fusion) объединяет оба слоя в единый ranked-результат
- Авто-detection query mode: технические запросы → FTS вес выше, смысловые → vector вес выше

> **Source-only репозиторий.** Содержит только код плагина и документацию. Рантайм-данные (SQLite БД, бэкапы, секреты, сессии, логи) исключены через `.gitignore`.

## Отличия от других видов памяти

| Тип памяти | Что хранит | Поиск | Срок жизни |
|---|---|---|---|
| **Memory-wiki** (эта) | Факты, уроки, предпочтения, конфиги | Lexical + Semantic + RRF | Постоянно |
| `memory` tool | Сырой текст профиля | Только инжект в промпт | Сессии |
| `distill` | Сжатые капсулы разговоров | FTS по ключам | Сессии + TTL |
| `plur` | Эпизодические энграммы | Косинусное сходство | Сезонно |
| `secret-vault` | Креденшелы, токены, ключи | Только по ID | Постоянно (зашифровано) |

### Memory-wiki vs обычный RAG

**Коротко:** RAG достаёт документы. Memory-wiki управляет памятью агента.

| Измерение | Типичный RAG | Memory-wiki |
|---|---|---|
| Единица хранения | Чанк/документ | Claim, evidence, task capsule, decision, preference, secret metadata, graph relation |
| Жизненный цикл | Обычно нет | Active/retired/superseded/uncertain/queued/review |
| Trust | На уровне источника | Confidence + salience + freshness + trust class + evidence + usage feedback |
| Конфликты | Возвращает оба текста | Явные contradiction rows + policy/manual resolution |
| Секреты | Часто не защищены | Secret scan → quarantine → redacted recall |
| Операционная память | Нет | Task capsules, project profiles, mistakes, decisions |
| Вывод | matching chunks | Sectioned pack_context: preferences/procedures/projects/diff/contradictions |
| Обслуживание | Реиндексация | Doctor/repair/backup/restore/FTS rebuild/topic normalization/journal checks |
| Интеграция | Внешний retriever | Native Hermes memory provider + plugin tools |

Memory-wiki **использует** RAG-техники внутри (FTS, semantic search, RRF), но его задача шире: держать многомесячную память агента полезной, аудируемой, курируемой, восстанавливаемой и безопасной.

## Возможности

### 72 инструмента
- `memory_wiki_query` — гибридный поиск (FTS5 + Qdrant)
- `memory_wiki_add_claim` — сохранить факт
- `memory_wiki_pack_context` — собрать релевантный контекст для LLM
- `memory_wiki_memory_diff` — сравнить воспоминания с проверенными фактами перед ответом
- `memory_wiki_debug_search` — поиск с разблюдовкой (lexical, bm25, rrf, verified)
- `memory_wiki_compare_search` — сравнить FTS-only vs hybrid
- `memory_wiki_evaluate_retrieval` — метрики Recall@k, MRR, NDCG
- `memory_wiki_semantic_status` — здоровье embedding/Qdrant
- `memory_wiki_query_mode` — определить тип запроса
- `memory_wiki_reindex` — переиндексация в Qdrant
- `memory_wiki_doctor` — полная диагностика
- `memory_wiki_repair` — восстановление (FTS, integrity, dashboards)
- `memory_wiki_backup` / `memory_wiki_restore` — бэкап и восстановление
- `memory_wiki_undo_last` — откат последней мутации
- `memory_wiki_transaction` — транзакционные batch-операции с dry-run
- `memory_wiki_write_firewall` — проверка claim перед durable-записью
- ...и ещё 56 инструментов

### Гибридный поиск (RRF)

```
user query
  → query mode detection (technical / semantic / mixed)
  → FTS5 top-200 (lexical, BM25 rank)
  → Qdrant vector top-200 (semantic, cosine)
  → RRF fusion (k=60, авто-веса по режиму)
  → score_breakdown (confidence, salience, verified, rrf)
  → top-k результат
```

### Verification pipeline
- **Curated источники** (post_task, task_capsule, decision) → auto-verified
- **Conversation** → unverified, флаг на review
- Verified claims получают +0.35 boost в scoring

### Topic hierarchy
- `hermes:memory → hermes`, `hermes:gateway → hermes` etc.
- При поиске по дочернему топику автоматически расширяется на родительский

### Write Firewall
- Source policy: tool/task/decision → пропускать, raw/blob → queue
- Quality lint: проверка на артефакты, truncation markers, пустые claims
- Secret scan: автоматическое quarantining секретов

### Journal + Recovery
- Append-only JSONL journal с hash-chain
- Logical checkpoints для быстрого восстановления
- `memory_wiki_rebuild_from_journal` — replay-восстановление SQLite из journal

### Debug-логирование
```bash
MEMORY_WIKI_DEBUG=1  # → /tmp/memory_wiki_debug.log
```
Логирует: query, query_mode, FTS candidates, vector candidates, RRF fused count

## Архитектура

```
MemoryWikiProvider (Hermes plugin)
  ├── SQLite (claims, evidence, entities, relations, journal)
  ├── FTS5 (lexical search + BM25)
  ├── Embedding-stub (:4000) — character n-gram hashing, без ML
  ├── Qdrant-stub (:6333) — векторная БД, cosine similarity
  ├── RRF fusion (lexical rank + semantic rank)
  ├── Verification pipeline (curated → verified)
  ├── Write Firewall (source policy + lint + secret scan)
  ├── Journal (append-only JSONL + logical checkpoints)
  └── Dashboards / pages (markdown)
```

**Никакого ИИ.** Embedding-stub и Qdrant-stub — чистый Python stdlib, character n-gram hashing + косинусное сходство. Без GPU, без нейросетей.

## Быстрый старт

```bash
# Клонировать плагин
mkdir -p ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git ~/.hermes/plugins/memory-wiki

# Поднять semantic-сервисы (опционально, из knowledge_db/)
cd ~/.hermes/knowledge_db
python3 embed_stub.py &    # :4000
python3 qdrant_stub.py &   # :6333

# Включить в config.yaml (~/.hermes/config.yaml):
#   memory:
#     provider: memory-wiki
#   plugins:
#     enabled:
#       - memory-wiki

# Перезапустить Hermes
```

### Проверка установки

```bash
cd ~/.hermes/plugins/memory-wiki
python3 -m py_compile __init__.py smoke_test.py memory_wiki_cli.py
MEMORY_WIKI_LLM_PACK=0 python3 smoke_test.py
```

Ожидаемый вывод:
```json
{"ok": true, "schemas": 72, "audit_events": 6}
```

## ENV-переменные

| Переменная | Default | Что |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Вкл/выкл semantic |
| `MEMORY_WIKI_RRF_K` | `60` | RRF константа |
| `MEMORY_WIKI_FTS_TOP_K` | `200` | Lexical candidates |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | Semantic candidates |
| `MEMORY_WIKI_HYBRID_TOP_K` | `100` | Hybrid candidates after fusion |
| `MEMORY_WIKI_DEBUG` | `0` | Debug-лог |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embedding-stub |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant-stub |
| `MEMORY_WIKI_LLM_PACK` | `0` | LLM-рефайнмент контекста |
| `MEMORY_WIKI_STRICT_RECALL` | `1` | Strict active/non-stale recall |

## Файлы репозитория

```
.
├── __init__.py              # Hermes MemoryProvider plugin (3911 строк)
├── plugin.yaml              # Метаданные плагина (v1.4.0)
├── smoke_test.py            # End-to-end smoke suite
├── memory_wiki_cli.py       # Standalone CLI для maintenance
├── embed_stub.py            # Embedding-сервер (:4000), character n-gram хеширование
├── qdrant_stub.py           # Qdrant-совместимая векторная БД (:6333), JSON-хранилище
├── .gitignore               # Исключает runtime DB, бэкапы, секреты
├── LICENSE                  # MIT
└── README.md
```

## Требования

- Python 3.10+ (stdlib-only, нет внешних зависимостей)
- SQLite 3.35+ (для FTS5)
- Embedding-stub + Qdrant-stub (из `knowledge_db/`) — опционально
- Hermes Agent (как MemoryProvider plugin)

## Лицензия

MIT. См. [`LICENSE`](LICENSE).
