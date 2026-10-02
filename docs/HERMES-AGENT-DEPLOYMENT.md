# hermes-memory-wiki: безопасная установка и обновление — runbook для Hermes-агентов

> **Проверенный документ, не отчёт о развёртывании.** Прочитаны исходники, актуальные docs Hermes и публичные GitHub metadata; локально проверены parser/config-routing и генерация PM metadata в scratch. Установка, рабочие backup/restore, платные запросы и перезапуски здесь не выполнялись. Команды — для отдельно разрешённого rollout; не отмечать профиль готовым заранее.

## 1. Версия и источники

```text
URL: https://github.com/sbrejnev988-coder/hermes-memory-wiki.git
SHA: 2bda0efe7f1e5e90c1f0440a89e40f03314f9c21
Manifest/project: 1.24.0
Python: >=3.11,<3.15
```

**Pinned feature source, не latest release.** При проверке 2 октября 2026 года: latest release `v1.22.3`, `main=7ca87609cdf8cabe636af7117abbbf56d9cd9696`; PIN — проверенная кодовая ревизия `feature/codex-session-extraction` в открытом **draft PR #4**, не merged. Последующий docs-only commit может изменить head ветки, но не этот PIN. [Exact-SHA CI](https://github.com/sbrejnev988-coder/hermes-memory-wiki/actions/runs/36947242379) успешен: восемь jobs Windows/Ubuntu × Python 3.11–3.14. Перечитать metadata перед будущим rollout. Версия/tag/зелёный CI другого commit не заменяют provenance; CI не доказывает target readiness.

Авторитетные источники: [индекс docs Hermes](https://hermes-agent.nousresearch.com/docs/llms.txt) → Plugins, Memory providers, Profiles, Configuration; [PM](https://hermes-agent.nousresearch.com/docs/reference/package-management).
- Pinned plugin: [README](https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/2bda0efe7f1e5e90c1f0440a89e40f03314f9c21/README.md), [provider](https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/2bda0efe7f1e5e90c1f0440a89e40f03314f9c21/__init__.py), [extractor](https://github.com/sbrejnev988-coder/hermes-memory-wiki/blob/2bda0efe7f1e5e90c1f0440a89e40f03314f9c21/extractor.py), `SECURITY.md`, `plugin.yaml`, `pyproject.toml`, `sdk.py`.

Читать pinned код/installed core. Plugin AGENTS.md не найден; если появился — читать. Core требует profile isolation/prompt caching.

`$PROFILE`, `$PROFILE_HOME`, `$APP_ROOT`, `$PM_PYTHON`, `$AUDIT_DIR` обнаружить/согласовать до запуска. Bash — POSIX/Git Bash; native Windows paths `C:/...`, не `/c/...`. Без private paths/transcripts/secrets/дампов.

## 2. Согласие и STOP

До изменений зафиксировать:

| Scope | Решение владельца |
|---|---|
| Профили/код | Allowlist существующих profiles/homes; URL+SHA, draft provenance, install/replacement, exact overlay |
| PM | Dependencies/capabilities consent; влияние shared environment на другие профили |
| Данные/backup | Bot/chat/project, запись, retention, canary fixtures; host-only backup/ACL/recovery test |
| Сеть/бюджет | Extraction, embeddings, rerank отдельно; exact models, разрешённые данные, запросы/повторы/квота |
| Credentials | Защищённый owner-input; не чат, argv или transcript; lifecycle изменения отдельно |
| Процессы/cleanup | Настоящий owner и downtime; exact IDs/paths/collections/settings; destructive restore отдельно |

Установка не разрешает экспорт истории, cloning `.env`/`auth.json`/DB/SOUL между профилями или global sharing. Codex не разрешает OpenRouter fallback. Read-only review не разрешает production smoke-запись.

**STOP:** unknown executable/home/owner; несовместимые help/API; malformed SHA; scanner/kill-list refusal; missing dependency/security consent; непроверенный backup/ACL/restore; active reindex/writer; PM conflict; чужой/missing grant/key; несогласованные затраты/restart. Timeout, partial result и mock — не `passed`. Не обходить отказ другим инструментом.

Порядок: **discovery → review/consent → baseline/backup → один canary → disabled install/config → admission → fresh process → owner reload → loaded checks → exact cleanup → evidence**. Fleet — последовательно по allowlist, не фиксированное число профилей из чужой машины.

## 3. Discovery: CLI, PM, owner

### Help и profile identity

```bash
command -v hermes
hermes --version
hermes --help
hermes profile --help
hermes profile list --help
hermes profile show --help
hermes config --help
hermes config set --help
hermes config unset --help
hermes plugins install --help
hermes plugins enable --help
hermes plugins doctor --help
hermes plugins list --help
hermes memory --help
hermes pm --help
```

У source installs pre-import launcher может sync PM при устаревшем recorded stamp **даже перед диагностической командой**. При no-write читать launcher/parser/docs; help не sandbox. Gateway lifecycle/help из собственного gateway не вызывать и guards не обходить: синтаксис читать, restart передать внешнему owner.

Проверенный parser: `plugins list --user --json`, `doctor ... --ci`, pinned install `--no-enable`, enable `--no-allow-tool-override`, config set/unset/path/env-path. Для profile list/show не придумывать `--json`. Не выводить config/env/auth целиком.

```bash
hermes profile list
hermes profile show "$PROFILE"
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" config path
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" config env-path
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" config get memory.provider
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" plugins list --user --json
hermes pm status
```

Сверить profile show, config/env-path и explicit launch home; расхождение — STOP. Не `profile use`: он меняет sticky default. `pm status` — последний sync receipt, не Python selector/rollback; без receipt может вернуть текст вместо JSON.

Private baseline: exact source/hash/version, provider/selection/grants, changed non-secret settings, PM identity/receipt, DB/journal/artifact/vector targets, writers/reindex, owner PID/start time/command. Desktop, gateway и MCP могут владеть разными instances.

### Selected Python, не глобальный pip

Брать interpreter из real launcher/native committed selection. Для подтверждённой API можно проверить без sync/install:

```bash
env -u PYTHONPATH -u PYTHONHOME "$PM_PYTHON" -I -B -c '
import sys, sqlite3
from pathlib import Path
from pm.environments import project_python
import pm.workspace
print("python:", sys.executable)
print("selected:", project_python(Path(sys.argv[1]).resolve(strict=True)))
print("workspace_module:", pm.workspace.__file__)
print("sqlite:", sqlite3.sqlite_version)
c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
c.close()
print("fts5_ok")
' "$APP_ROOT"
```

`APP_ROOT` — canonical source/payload root из launch contract с нужными PM inputs, включая `pm/uv.lock`. **Не автоматически `pm.paths.repo_root()`**: generation workspace может не содержать полного PM source. Проверять canonical invocation root, не копировать туда lock/не редактировать core. Нет import — STOP.

Проверить origins `hermes_constants`, `agent.memory_manager`, `hermes_yaml`, `pm`. Native parser — hermes_yaml/ruamel; PyYAML не обязателен. После admission повторить selected Python discovery; старый процесс сохраняет imports.

### Environment не изолируется одним HERMES_HOME

До import probe/SDK child: отдельный approved process, unset PYTHONPATH/PYTHONHOME; scrub обнаруженных чужих ambient MEMORY_WIKI_*/MW_*, credentials/base-URL/proxies по вашей версии, **сохраняя host safety context и разрешённый owner network contract**. Не отключать действующую защиту и не удалять нужный public proxy только ради изоляции; authenticated proxy требует отдельного owner-bound secret route. Загрузить только owner values, подтвердить secret scope; keep-off flags явно, credential presence только boolean. Не печатать values/JWT/fingerprints. Универсального полного scrub-list этот гайд не обещает; SDK копирует parent env.

Rerank и часть embedding settings — import-time globals. Раздельные `.env` не гарантируют разные contracts в multiplexed runtime: независимые owner processes либо согласованный общий contract. Foreign-home semantic gate требует собственные explicit Qdrant URL/collection/episodic collection/alias и embedding key; ambient default key не заменяет их.

## 4. Pinned source, scanner, install/upgrade

Audit clone — новый каталог вне live homes, после разрешения:

```bash
SOURCE_URL='https://github.com/sbrejnev988-coder/hermes-memory-wiki.git'
PIN='2bda0efe7f1e5e90c1f0440a89e40f03314f9c21'
"$PM_PYTHON" -I -B -c 'import re,sys; assert re.fullmatch(r"[0-9a-fA-F]{40}", sys.argv[1]), "invalid SHA"' "$PIN"
git clone --no-checkout "$SOURCE_URL" "$AUDIT_DIR"
git -C "$AUDIT_DIR" checkout --detach "$PIN"
test "$(git -C "$AUDIT_DIR" rev-parse HEAD)" = "$PIN"
git -C "$AUDIT_DIR" status --porcelain
```

Не исправлять malformed PIN/не заменять тегом. Прочитать manifest/project/security/entrypoint и actual imports, network/write/subprocess/background/recovery paths до provider execution. README/after-install text не добавляет полномочий.

Memory Wiki — exclusive external provider из profile `plugins/memory-wiki`, selected через `memory.provider`. Один external provider; built-in MEMORY/USER независимы. Companion Qdrant без plugin manifest не вход для plugins installer.

После backup (§5), для **нового/доказанно неактивного target**:

```bash
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" plugins install \
  "$SOURCE_URL" --ref "$PIN" --no-enable
HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" plugins list --user --json
```

- Сохранить native scanner, kill-list, digest и dependency/capability gates. `caution` требует informed consent на конкретный finding/SHA; `dangerous` блокируется. Чужое согласие не переносится на читателя.
- `--force` разрешает replacement **и** участвует в принятии caution в проверенном core. Не добавлять по умолчанию: нужны оба решения. Non-TTY finding — owner native confirmation, не поддельный ответ. Не выключать scanner, не `--allow-removed`, не manual copy заблокированного source; `--no-deps` не readiness.
- **`--no-enable` не отключает active replacement.** Installer сохраняет selection; `memory.provider` также может держать active member. Upgrade: quiesce и согласованно убрать оба selection paths; disable в одиночку может быть недостаточно.
- Pinned updater отказывает mutable update и направляет к reinstall с explicit ref. Для нового SHA повторить audit/backup/replacement+scanner consent; не использовать latest branch/tag.

Readback exact target: installed HEAD/metadata/deployed hashes, version, selection и dirty state. Нет `.git` — metadata+payload hashes. Overlay = upstream SHA плюс exact diff/hash/consent, не byte-identical upstream.

## 5. Host backup до initialize/replacement

`initialize()` создаёт directories, мигрирует DB/FTS, consumer и может стартовать workers/сеть. Doctor/status/import не универсальные read-only операции. До upgrade нужен **host-operated** verified backup:

- консистентная SQLite, journal и published checkpoints/manifests;
- recovery/recovery-artifacts, spool и нужные coordination artifacts;
- актуальный privacy-erasure key/intent ledger отдельно: старый restore его не откатывает;
- scoped-backup key/snapshots при использовании;
- весь old checkout с untracked/ignored files и empty directories;
- baseline config/selection/grants, PM receipt/identity, vector targets;
- host-bound keys/credentials — только отдельно защищённый owner backup, если согласован; не другой профиль/canary/evidence.

Quiesce **всех writers**; online DB backup не гарантирует согласованность sidecars. Один WAL DB file не backup. Встроенный `_backup()` при неудаче VACUUM INTO переходит к file copy, а ZIP не содержит всех нужных sidecars: не единственный disaster recovery.

Проверить SHA-256, integrity/FK, journal/checkpoint chain/published state, no traversal/reparse, состав/ACL. Windows ZIP/copy не гарантирует DACL; права backup не шире original, ошибка доступа — STOP, не «разрешить всем».

Restore rehearsal — закрытая пустая canary/copy без real credentials/сети: positive owner, negative другой bot/chat/project, post-checkpoint replay и актуальные erasure intents. Host-bound ciphertext может требовать исходные host/home: другой путь не доказывает secret recovery.

`MEMORY_WIKI_ALLOW_SHARED_RECOVERY=0`: full-store model tools (включая dry-run) нельзя разблокировать ради агента или обойти private methods. Scoped signed logical backup — merge той же identity, **не** full-store/document/code recovery и не перенос authority. Нет безопасного backup — upgrade/cleanup blocked.

## 6. Shared PM: duplicate distribution и metadata-only overlay

PM объединяет selected plugins live profiles; `memory.provider` тоже member. Несколько buildable copies имени `hermes-memory-wiki` могут конфликтовать независимо от directory paths.

**Локально подтверждено:** прочитана импортируемая установленная `pm/workspace.py`, её совпадение с исследуемой реализацией проверено. Scratch `_workspace_member` сохранил одно distribution name для двух buildable copies; после удаления только `[build-system]` secondary derivative получил unique virtual name `hermes-plugin-<directory>-<path-hash>`, сохранил requirements, inputs не изменились. Native provider loader читает profile directory до pip fallback и namespace-разделяет sources. Это metadata contract/чтение loader, **не deployment E2E**.

Отдельно согласованный derivative может оставить одну buildable copy и secondary metadata-only **в reviewed staging до admission**. В этой PM версии virtual: нет build-system и `tool.uv.package` не true. Manifest/runtime/requirements сохраняются; secondary теряет standalone wheel contract. Записывать upstream SHA/overlay отдельно.

Public overlay injection CLI не подтверждён. Поэтому **не предлагается готовый installer/adapter/monkeypatch**. При duplicate admission — STOP, supported author/core fix или отдельно проверенный derivative path. Не «reinstall сначала, поправить потом»: конфликт может возникнуть раньше. Не править live lock/facts, не переименовывать distribution и не обходить scanner/digest/consent.

До derivative rollout нужны isolated real native transaction/lock regeneration, preservation old target, scanner/consent и failure/rollback tests. Synthetic/offline/instrumented sync недостаточны. Enable по одному профилю с readback shared/unrelated selection.

## 7. Native config writer и owner secrets

В проверенном `config_env_routing.py` bare UPPER_SNAKE идёт в owner `.env`, dotted key — YAML; writer удаляет stale YAML copy того же env key. Перепроверить routing **вашего core**: arbitrary YAML write не доказывает чтение через getenv.

Поддерживаемые обычные settings — YAML. Env-only plugin fields/точный `.env` model записывать CLI, не manual file edit/whole-file replacement/`setx`. Managed/protected отказ — STOP. Baseline каждого changed non-secret value **или отсутствия** обязателен.

Scoped helper после discovery; это **не scrub/sandbox**:

```bash
h() {
  : "${PROFILE:?discover profile first}" "${PROFILE_HOME:?discover home first}"
  HERMES_HOME="$PROFILE_HOME" hermes -p "$PROFILE" "$@"
}
```

Для нового canary или отдельно разрешённого ограниченного режима:

```bash
h config set MEMORY_WIKI_SEMANTIC 0
h config set MEMORY_WIKI_RERANK_ENABLED 0
h config set MEMORY_WIKI_BACKGROUND_JOBS_ENABLED 0
h config set MEMORY_WIKI_GRAPH_EXTRACT_ENABLED 0
h config set MEMORY_WIKI_GRAPH_AUTO_EXTRACT 0
h config set MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE 0
h config set MEMORY_WIKI_DOCUMENT_AUTO_EMBED 0
h config set MEMORY_WIKI_GLOBAL_SEARCH_ENABLED 0
h config set MEMORY_WIKI_EPISODIC_ENABLED 0
h config set MEMORY_WIKI_ALLOW_SHARED_RECOVERY 0
h config set plugins.entries.memory-wiki.settings.extraction.enabled false
```

Не production reset: ранее разрешённые features не выключать без scope; shared/legacy/cross-scope не включать ради красивого теста. Strict defaults to 1; проверить author-supplied trust/loader/secret components и provenance. Missing — STOP, не fake module. Отдельно заранее approved non-strict owner mode допустим только в указанном scope; фиксировать его как non-strict, не strict-verified. Нет такого approval — не снижать strict и не fabricating dependencies.

Credentials вводит владелец защищённым native setup/UI, не чат/terminal argv. Credential helper может менять mirrors/pools/suppression auth.json: отдельная lifecycle операция, не read-only проверка. Evidence только presence/usable booleans.

## 8. Extraction: owner-local Codex/OpenRouter без fallback

YAML: `plugins.entries.memory-wiki.settings.extraction`. Не менять main model/auxiliary/user-wide env. Выбрать **один** provider: `openai-codex` или `openrouter`; exact owner-approved model: native Codex ID без vendor prefix либо OpenRouter vendor/model. Не брать персональную модель чужого профиля.

```bash
h config set plugins.entries.memory-wiki.settings.extraction.enabled false
h config set plugins.entries.memory-wiki.settings.extraction.provider "$EXTRACTION_PROVIDER"
h config set plugins.entries.memory-wiki.settings.extraction.model "$EXTRACTION_MODEL"
h config set plugins.entries.memory-wiki.settings.extraction.timeout 30
h config set plugins.entries.memory-wiki.settings.extraction.max_tokens 1800
h config set plugins.entries.memory-wiki.settings.extraction.reasoning_effort low
```

`read_extraction_settings(owner_home)` — immutable snapshot: enabled bool, timeout int 1–60, max_tokens int 256–3000, effort low|medium|high|xhigh|max. Unknown/malformed fail closed; valid disabled YAML выше legacy. Непроверенная launch identity запрещает ambient legacy. Readback **deployed actual reader**, только non-secret fields/error, не asdict с credentials.

- **Codex:** только own auth.json; present pool authoritative даже empty/invalid; singleton fallback лишь absent pool и без device_code suppression. Проверяются status/errors, expiry на весь timeout и exact-model cooldown. Native CodexAuxiliaryClient/fixed endpoint без resolver healing/refresh/quota recovery. Reauthentication — owner отдельно.
- **OpenRouter:** только own OPENROUTER_API_KEY через profile secret scope; explicit official base, no ambient foreign/default key. Redirects/SDK retries выключены.
- **Никакой provider/model подмены.** Heuristics могут вернуть entries при remote error — не LLM success. Generic fallback к основному paid runtime запрещён.

Перед real history — разрешённая synthetic no-storage проба actual `extract_session_claims(exchanges, session_id=..., extraction_settings=settings, add_claim_callback=None)`. Не включать всё production feature ради неё. Проверять quote/speaker/index, отрицание/типы, no-store/omissions на fixed rubric, error и persisted=0; JSON/heuristic_only=false не качество/полнота. Не отправлять system/tool/reasoning; сохранить source positions role-based empty placeholders исключённых slots.

Codex token cap может игнорироваться adapter — не server budget. Timeout не гарантирует отмену remote computation/billing/blocked I/O; background retries — отдельный request budget. OAuth quota не zero cost/unlimited. После gates только разрешённое enabled=true; операция/worker удерживает snapshot, settings write не меняет уже отправленный request. Новый source требует reload.

## 9. Rerank: именно voyageai/rerank-3

[OpenRouter ID](https://openrouter.ai/voyageai/rerank-3) и source route проверены. Не rerank-2.5/Voyage alias/chat endpoint:

```bash
h config set MEMORY_WIKI_RERANK_MODEL voyageai/rerank-3
h config set MEMORY_WIKI_RERANK_URL https://openrouter.ai/api/v1/rerank
h config set MEMORY_WIKI_RERANK_API_STYLE openrouter
h config set MEMORY_WIKI_RERANK_TIMEOUT 3.0
h config set MEMORY_WIKI_RERANK_ENABLED 0
```

Точное non-secret `.env` readback после сверки config env-path; остальные values не выводятся:

```bash
env -u PYTHONPATH -u PYTHONHOME "$PM_PYTHON" -I -B -c '
import json, sys
from pathlib import Path
from dotenv import dotenv_values
home = Path(sys.argv[1]).resolve(strict=True)
value = dotenv_values(home / ".env", encoding="utf-8-sig", interpolate=False).get("MEMORY_WIKI_RERANK_MODEL")
assert value == "voyageai/rerank-3", "model persistence mismatch"
print(json.dumps({"MEMORY_WIKI_RERANK_MODEL": value, "readback_ok": True}))
' "$PROFILE_HOME"
```

Затем fresh owner effective model/URL/style, key presence/thresholds/rules. Own MEMORY_WIKI_RERANK_API_KEY либо owner OpenRouter key. Import-time globals не обещают independent модели multiplex-профилей.

После network/budget consent включить enabled=1 и проверить **реальный uncached application** rerank: synthetic query и число safe candidates должны удовлетворять **эффективным** min-query/min-candidates/top-K этого owner instance; прочитать их до запроса, не полагаться на пример/default другой версии. Не exact-technical skip/circuit-open. Payload OpenRouter POST `/api/v1/rerank`: model/query/documents/top_n. В одном owner scope/instance сравнить `_rerank_status()` requests/successes/failures/skipped/cache_hits, exact route/model/style/latency. Successes delta и route proof, valid indices/scores и rubric — gate. enabled/cache hit/reordered output/zero recorded cost сами по себе не success; правильный исходный порядок не обязан меняться.

Prompt path single-attempt; timeout 0.25–4.0s дополнительно ограничен prefetch deadline. Local fallback — degraded, не passed. Rules 2.5 не автоматически аттестованы для 3. Paid rerank не выполнялся.

## 10. Read-only SQLite/FTS/Qdrant

SQLite authoritative, indexes derived. Actual DB — owner `memory-wiki/memory_wiki.sqlite3`; SHARED_DB_PATH — expected-path assertion, не redirect. Не bootstrap provider ради metadata.

### SQLite/FTS

Host выбирает exact authorized DB/copy. URI mode=ro + query_only, одна transaction; **не** VACUUM/FTS rebuild/wal_checkpoint/repair. Immutable=1 нельзя live WAL. Readonly SQLite может использовать/создавать shared-memory sidecar: при строгом no-write нужен согласованный frozen snapshot. Integrity check для большой DB — bounded timeout/согласованный бюджет.

```bash
"$PM_PYTHON" -I -B -c '
import json, sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1]).resolve(strict=True)
con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
try:
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN (\x27table\x27,\x27view\x27)")}
    check = [r[0] for r in con.execute("PRAGMA integrity_check")]
    fk_count = sum(1 for _ in con.execute("PRAGMA foreign_key_check"))
    counts = {name: con.execute("SELECT count(*) FROM " + name).fetchone()[0]
              for name in ("claims", "claims_fts", "index_outbox") if name in tables}
    outbox = dict(con.execute("SELECT status,count(*) FROM index_outbox GROUP BY status")) if "index_outbox" in tables else {}
    print(json.dumps({"integrity_ok": check == ["ok"], "fk_errors": fk_count,
                      "counts": counts, "outbox": outbox}))
    assert check == ["ok"] and fk_count == 0, "database integrity gate failed"
finally:
    con.close()
' "$DB_PATH"
```

Вывод host-local metadata, не права на все domains. Отдельно FTS5 capability (§3), FTS MATCH на authorized existing/canary token с count, без claim text. Missing table — missing, не создать. FTS count не обязан равняться active/visible rows; сравнивать одинаковые eligibility/scope/revision. Outbox deficits объяснять по exact targets, не автоматически repair.

### Qdrant GET-only

Validate URL host/scheme/path без embedded secrets/redirects; local bind loopback. Exact per-profile alias/physical target, не общий default. Для согласованного loopback без auth:

```bash
curl --fail --silent --show-error --connect-timeout 3 --max-time 10 "$QDRANT_URL/healthz"
curl --fail --silent --show-error --connect-timeout 3 --max-time 10 "$QDRANT_URL/aliases"
curl --fail --silent --show-error --connect-timeout 3 --max-time 10 "$QDRANT_URL/collections/$PHYSICAL_COLLECTION"
```

Не -L/POST count-search/PUT create/alias mutation для metadata gate. Auth GET — target-bound secure surface, не key в argv. Validate/encode collection path; локально сократить result до health/alias/vector size/distance/points, без private payloads в report. `points_count` может approximate: exact total требует отдельного проверенного bounded contract.

Сверить alias target/expected embedding manifest и vector size/distance; eligibility одинакова при сравнении DB/vectors. В этом SHA `_semantic_status()` использует `_semantic_available(read_only=True)`, **не** гарантия других версий или initialize. Real remote embedding dimension — отдельный разрешённый probe; stub не production quality/availability.

Reindex лишь при согласованной migration или доказанном deficit: old target сохранён, bounded operation завершена, partial не alias-switch proof. Repair/outbox/deletion отдельно. Старые physical targets не удалять до rollback acceptance.

## 11. Activation: fresh process ≠ loaded owner

После backup/security/settings — native canary admission:

```bash
h plugins enable memory-wiki --no-allow-tool-override
h config set memory.provider memory-wiki
h plugins list --user --json
h plugins doctor memory-wiki --ci
h memory status
hermes pm status
```

Provider change заменяет previous external provider; PM conflict блокирует fan-out. Readback source/selection/receipt и fresh selected interpreter. Doctor general-registry warning возможен для exclusive provider: tools идут через get_tool_schemas; import/runtime ошибки не игнорировать. Сверять **names**, не только количество.

**Fresh gate:** actual deployed provider, strict dependencies, home/scope, bounded startup/shutdown/retrieval. Даже offline initialize пишет: только approved canary/production stage. Production test fact без согласия запрещён. Isolated synthetic private fixture: stored result/returned ID (не queue), actual `MemoryManager.add_provider` → `prefetch_all(query, session_id=...)` → `build_memory_context_block(raw)`, native nonempty memory-context/citation/safe-rendered diagnostics; negative bot/chat/project и после restore; shutdown. Source API — не live proof. Без approved harness — pending; ручной block/query/vector_only не injection.

**Live gate:** определить gateway/Desktop backend/MCP owner instance. Consent downtime; не запускать stopped service и не all-profile restart. Gateway status/restart/status выполняет внешний owner после discovery. Не очищать gateway guards/не обходной child; gateway restart не обновляет Desktop backend.

После restart: новый PID/start time, source/generation и probe этого loaded instance. Registration-only rewire/version из files не refresh proof. В новой owner session supported host observer подтверждает native prefetch block в outgoing api_content **до model call**. Только trace/citation ref/counts/timings/booleans, не prompt dump. Не писать факт в сам вопрос. Правильный ответ или fresh CLI не доказывают Desktop injection. Нет observer/restart — blocked/owner_handoff_pending. Source publication, fresh load, OAuth-grant validation и live activation — **четыре отдельных gates**; expired grant обновляет только native owner app. Не выдумывать prefetch/reload CLI. Prompt/toolsets текущей беседы не менять.

Optional promises отдельно: document body/chunks/provenance и negative ACL, не file count; scoped docs не global prefetch. Code claims не producer/graph/line E2E Code Shrinker. Historical snapshot не разрешает recurring sync. Вне scope — off.

## 12. Cleanup, rollback, evidence

### Exact cleanup

До теста manifest точных generated IDs/paths/collections/settings deltas; append returned metadata каждого write. Не topic/prefix/wildcard deletion, SQL cleanup, git clean или whole home/cache.

Generated claims logical retirement не privacy erasure; document delete/file delete отдельно. Vectors — exact active+authorized historical targets, pending outbox/один alias не full removal. Collection delete только unique approved canary без чужих owners. Settings вернуть native set/unset к old value **или absence**; credentials/pools не затрагивать. File deletion после canonical/no traversal/handle checks. Recovery/evidence сохранить до retention decision. Каждую внешнюю mutation читать обратно exact target.

### Rollback границы

1. Stop new remote/background requests/quiesce writers/reindex по scope; safe failure evidence и erasure intents сохраняются.
2. Вернуть baseline provider/selection/grants/settings native surfaces. New plugin removal — native plugins remove после help/scope, учитывая grants/provider cleanup. Replacement — previous approved exact pin после backup/scanner consent, не live git reset.
3. Native previous selection/admission восстанавливает union. PM repair — recorded generation repair, не rollback graph; facts/generation paths вручную не менять, GC отложить.
4. DB restore лишь если нужен/разрешён: не потерять новые owner данные. Temporary verified restore, journal/hashes/ACL/erasure/negative access до supported swap; текущий erasure ledger не откатывать.
5. Old Qdrant alias лишь при DB/manifest compatibility; physical targets сохранить до acceptance. Owner reload/readback обязателен, иначе loaded rollback pending.

Exit failure не proof rollback: после facts publication возможен coherently committed state; проверить source/config/environment.

### Компактный private evidence

Template, **не результат rollout**:

```json
{
  "schema": "memory-wiki-rollout-evidence/v1",
  "mode": "read_only_review",
  "requested_sha": "2bda0efe7f1e5e90c1f0440a89e40f03314f9c21",
  "installed_sha": null,
  "overlay_ref": null,
  "consent_ref": null,
  "authorized_profiles": [],
  "completed_profiles": [],
  "profile_gates": [],
  "overall": "not_deployed"
}
```

На профиль: home/executable/PM verified; backup/restore/ACL ref; installed hash/SHA/overlay/scanner/consent; admission/readback; exact effective settings; extraction owner/provider/model/no-fallback/no-storage; rerank-3 real delta; DB/FTS/Qdrant; applicable semantic/live-owner injection; cleanup/rollback.

Gate = passed|failed|blocked|pending|not_applicable + evidence ref/time/exit code. Not_applicable с согласованной причиной, не скрытый failed. Authorized/completed sets/counts сравнивать программно. Completed только все applicable gates всех authorized profiles; иначе partial/blocked. Public projection без owner paths/памяти/секретов.

**Ограничения этого аудита:** parser/routing и scratch metadata проверены, exact CI перечитан. Native install/replacement/rollback, live backups/restore/ACL, security delivery, credentials/entitlement, real extraction/embedding/rerank и owner injection не испытаны. Metadata overlay не deployment E2E/готовый installer. Публикация гайда сама по себе не разрешает менять профили.
