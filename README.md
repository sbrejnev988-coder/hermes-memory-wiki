# Hermes Memory-Wiki

**Нативная активная память для Hermes Agent.** SQLite + FTS5 + Qdrant vectors + RRF hybrid search.

## Что это

Memory-wiki — не просто «заметки». Это **подсистема долговременной памяти** внутри Hermes:
- Каждый факт (claim) хранится с confidence, salience, evidence, источником
- FTS5 даёт точный lexical-поиск (слова, коды, пути, endpoints)
- Qdrant vectors дают смысловой semantic-поиск (похожие концепции, даже если слова разные)
- RRF (Reciprocal Rank Fusion) объединяет оба слоя в единый ranked-результат
- Авто-detection query mode: технические запросы → FTS вес выше, смысловые → vector вес выше

## Отличия от других видов памяти

| Тип памяти | Что хранит | Поиск | Срок жизни |
|---|---|---|---|
| **Memory-wiki** (эта) | Факты, уроки, предпочтения, конфиги | Lexical + Semantic + RRF | Постоянно |
| `memory` tool | Сырой текст профиля | Только инжект в промпт | Сессии |
| `distill` | Сжатые капсулы разговоров | FTS по ключам | Сессии + TTL |
| `plur` | Эпизодические энграммы | Косинусное сходство | Сезонно |
| `secret-vault` | Креденшелы, токены, ключи | Только по ID | Постоянно (зашифровано) |

**Ключевое отличие:** memory-wiki — единственная подсистема с **гибридным lexical+semantic поиском** и **структурной верификацией** (verified/unverified).

## Возможности

### 72 инструмента
- `memory_wiki_query` — гибридный поиск (FTS5 + Qdrant)
- `memory_wiki_add_claim` — сохранить факт
- `memory_wiki_pack_context` — собрать релевантный контекст для LLM
- `memory_wiki_debug_search` — поиск с разблюдовкой (lexical, bm25, rrf, verified)
- `memory_wiki_compare_search` — сравнить FTS-only vs hybrid
- `memory_wiki_evaluate_retrieval` — метрики Recall@k, MRR, NDCG
- `memory_wiki_semantic_status` — здоровье embedding/Qdrant
- `memory_wiki_query_mode` — определить тип запроса
- `memory_wiki_reindex` — переиндексация в Qdrant
- `memory_wiki_doctor` — полная диагностика
- ...и ещё 62 инструмента

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
  ├── Journal (append-only JSONL + logical checkpoints)
  └── Dashboards / pages (markdown)
```

**Никакого ИИ.** Embedding-stub и Qdrant-stub — чистый Python stdlib, character n-gram hashing + косинусное сходство. Без GPU, без нейросетей.

## Быстрый старт

```bash
# Установка (в Hermes)
cp __init__.py plugin.yaml ~/.hermes/plugins/memory-wiki/
cd ~/.hermes/knowledge_db
python3 embed_stub.py &    # :4000
python3 qdrant_stub.py &   # :6333

# Включить в config.yaml:
# memory:
#   provider: memory-wiki

# Перезапустить
glinomes restart
```

## ENV-переменные

| Переменная | Default | Что |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Вкл/выкл semantic |
| `MEMORY_WIKI_RRF_K` | `60` | RRF константа |
| `MEMORY_WIKI_FTS_TOP_K` | `200` | Lexical candidates |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | Semantic candidates |
| `MEMORY_WIKI_DEBUG` | `0` | Debug-лог |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embedding-stub |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant-stub |

## Требования

- Python 3.10+ (stdlib-only, нет внешних зависимостей)
- SQLite 3.35+ (для FTS5)
- Embedding-stub + Qdrant-stub (из `knowledge_db/`)
- Hermes Agent (как MemoryProvider plugin)

## Лицензия

MIT
