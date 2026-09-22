# Security Review: memory-wiki

## Scope

Independent read-only repository scan of current working tree; focused verification of model-facing provenance, auxiliary persistence, and document scope controls.

- Scan mode: repository
- Target kind: git_worktree
- Target ID: target_sha256_9588b714145045075c0cf18e0de4e4516aa6732bebfa469d3c55a74155264870
- Revision: 68790251406e824281da80270b19135f6083708f
- Snapshot digest: codex-security-snapshot/v1:sha256:9de3adb3f82c3df471d11fe10e3672ceff8e17f41858fb7da208c21b27e2bc53
- Inventory strategy: repository
- Included paths: .
- Excluded paths: none
- Runtime or test status: not recorded

Limitations and exclusions:
- Partial coverage: not all 201 in-scope files were fully audited.
- Production files may change concurrently after scan start.

### Scan Summary

| Field | Value |
| --- | --- |
| Scan outcome | completed |
| Reportable findings | 2 |
| Severity mix | high: 1, medium: 1 |
| Confidence mix | high: 2 |
| Coverage | partial |
| Validation mode | static source review |

Canonical artifacts: `scan-manifest.json`, `findings.json`, and `coverage.json`. This report is a deterministic projection of those files.

## Threat Model

Hermes Memory Wiki registers model-facing memory tools and lifecycle hooks. It stores claims and auxiliary records in a local SQLite database, renders bounded recall into prompts, and optionally uses Qdrant/OpenRouter and external document connectors. Source anchors: __init__.py:2933-3000,3432-3481,4398-4504,5138-5158; document_knowledge_graph.py:197-265.

### Assets

- Private chat and project memory in SQLite (__init__.py:3284-3365).
- Integrity of future system prompts assembled from preferences (__init__.py:3432-3481).
- Credential material that should be kept out of ordinary SQLite memory (__init__.py:2728-2732,13651-13667).

### Trust Boundaries

- Model tool arguments enter handle_tool_call and durable SQLite mutations; tool arguments do not authenticate a user instruction (__init__.py:4430,5054,8175-8205).
- SQLite preference rows are promoted into system_prompt_block based on a caller-supplied source string (__init__.py:3432-3481).
- External document queries require the initialized project scope; requested scope mismatches are rejected in normal lifecycle (__init__.py:2995-2997; document_knowledge_graph.py:197-223).
- Full-store backup can copy SQLite content into a ZIP; it is restricted to trusted-host recovery by default (__init__.py:4670-4700,14075-14103).

### Attacker Capabilities

- Untrusted content can influence an agent to call exposed memory tools, subject to model/tool behavior; it does not directly control host configuration or SQLite files.
- A model-facing caller can supply preference rule/source/visibility and post-task or decision arrays via published tool schemas (__init__.py:4402,4411,4430).

### Security Objectives

- Only host-attested user preferences may be promoted to system-level prompt instructions.
- Untrusted tool fields containing raw secrets must be rejected or redacted before persistent auxiliary writes.
- Bot, chat, and project ACL checks must be enforced at each direct read/write path.

### Assumptions

- Static source review; no application code or live exploit was executed.
- The documented normal provider lifecycle calls initialize(), which supplies nonempty current_project_id() when no project ID is configured.
- The reported preference impact requires a model-facing caller to invoke the exposed tool; inducing a model to do so from untrusted text is plausible but was not measured.
- Coverage is partial: the large repository and active concurrent edits were not exhaustively reviewed.

## Findings

| Finding | Severity | Confidence | Detailed write-up |
| --- | --- | --- | --- |
| [Model-created preference becomes a trusted system instruction](#finding-1) | high | high | inline below |
| [Post-task and decision lists persist unredacted secrets](#finding-2) | medium | high | inline below |

### Confidence Scale

| Label | Meaning |
| --- | --- |
| high | Direct evidence supports the finding with no material unresolved blocker. |
| medium | Evidence supports a plausible issue, but material runtime or reachability proof remains. |
| low | Evidence is incomplete and the item is retained only for explicit follow-up. |

<a id="finding-1"></a>

### [1] Model-created preference becomes a trusted system instruction

| Field | Value |
| --- | --- |
| Severity | high |
| Confidence | high |
| Confidence rationale | The tool schema, persistence path, global visibility check, and system prompt consumer form a direct source-to-sink trace; no host provenance check appears on this path. |
| Category | prompt-injection |
| CWE | CWE-345, CWE-807 |
| Affected lines | __init__.py:8180-8200, __init__.py:3432-3469, __init__.py:4430 |

#### Summary

A model-facing caller can save a rule with caller-selected `source=explicit` and `visibility_scope=global`; the next prompt builder treats the row as a trusted user preference and inserts it into the system prompt for every bot sharing the database.

#### Root Cause

The model-facing write API accepts provenance and visibility as ordinary tool arguments. The write path stores those fields without host attestation. Later, the prompt builder uses the stored source string as the trust decision, so model-authored text can cross from untrusted memory into system-level instructions.

**Model tool accepts claimed provenance** — `__init__.py:4430`

The caller controls both the alleged source and audience of the rule; `explicit` is the default.

```python
{"name":"memory_wiki_add_preference_rule","description":"Add/update a scoped first-class preference priority rule used by the preference layer.","parameters":P({"rule":{"type":"string"},"priority":{"type":"integer","default":100},"scope":{"type":"string","default":"global"},"source":{"type":"string","default":"explicit"},"status":{"type":"string","enum":["active","retired"],"default":"active"},"visibility_scope":{"type":"string","enum":["global","bot","chat","project","private"]},"project_id":{"type":"string"}}, ["rule"])},
```

**Unattested source and rule are stored** — `__init__.py:8180-8198`

Only a literal `system` label is rewritten; no host or user event authenticates `explicit`, and the caller-selected visibility is persisted.

```python
source = short(redact_secrets(str(a.get('source') or 'explicit')), 200)
if source.lower() == 'system':
    source = 'explicit'
...
c.execute("""INSERT INTO preference_rules(...,source,...,visibility_scope,...)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET ... source=excluded.source,...""",
          (rid, rule, priority, scope, source, status, ts, ts, h,owner['visibility_scope'],...))
```

**Source label grants system-prompt authority** — `__init__.py:3434-3469`

The renderer equates the self-asserted `explicit` source with trusted user provenance and turns the stored text into prompt instructions.

```python
trusted_exact = {"system", "explicit", "user", "user_correction", "explicit_correction"}
...
if source not in trusted_exact and not source.startswith(trusted_prefixes):
    continue
...
return (
    "# Trusted User Preference Layer\n"
    "These are active first-class preference rules with explicit/system provenance. "
    "Apply them as durable user preferences ...\n"
    + "\n".join(rendered)
)
```

**Trusted block is appended to system prompt** — `__init__.py:3471-3481`

The future system prompt consumes the preference text.

```python
trusted_preferences = self._trusted_preference_system_block()
return base + (("\n\n" + trusted_preferences) if trusted_preferences else "")
```

#### Validation

The public tool can submit `source=explicit` and `visibility_scope=global`; the persistence path retains them, and the prompt builder selects `explicit` rows for system_prompt_block. Existing ACLs limit some audiences but do not verify provenance.

Validation method: static source trace

**Model tool accepts claimed provenance** — `__init__.py:4430`

The caller controls both the alleged source and audience of the rule; `explicit` is the default.

```python
{"name":"memory_wiki_add_preference_rule","description":"Add/update a scoped first-class preference priority rule used by the preference layer.","parameters":P({"rule":{"type":"string"},"priority":{"type":"integer","default":100},"scope":{"type":"string","default":"global"},"source":{"type":"string","default":"explicit"},"status":{"type":"string","enum":["active","retired"],"default":"active"},"visibility_scope":{"type":"string","enum":["global","bot","chat","project","private"]},"project_id":{"type":"string"}}, ["rule"])},
```

**Unattested source and rule are stored** — `__init__.py:8180-8198`

Only a literal `system` label is rewritten; no host or user event authenticates `explicit`, and the caller-selected visibility is persisted.

```python
source = short(redact_secrets(str(a.get('source') or 'explicit')), 200)
if source.lower() == 'system':
    source = 'explicit'
...
c.execute("""INSERT INTO preference_rules(...,source,...,visibility_scope,...)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET ... source=excluded.source,...""",
          (rid, rule, priority, scope, source, status, ts, ts, h,owner['visibility_scope'],...))
```

**Source label grants system-prompt authority** — `__init__.py:3434-3469`

The renderer equates the self-asserted `explicit` source with trusted user provenance and turns the stored text into prompt instructions.

```python
trusted_exact = {"system", "explicit", "user", "user_correction", "explicit_correction"}
...
if source not in trusted_exact and not source.startswith(trusted_prefixes):
    continue
...
return (
    "# Trusted User Preference Layer\n"
    "These are active first-class preference rules with explicit/system provenance. "
    "Apply them as durable user preferences ...\n"
    + "\n".join(rendered)
)
```

**Trusted block is appended to system prompt** — `__init__.py:3471-3481`

The future system prompt consumes the preference text.

```python
trusted_preferences = self._trusted_preference_system_block()
return base + (("\n\n" + trusted_preferences) if trusted_preferences else "")
```

Limitations:
- No live model-inducement experiment was run.

#### Dataflow

model tool args -\> `_add_preference_rule` -\> SQLite preference_rules -\> `_trusted_preference_system_block` -\> `system_prompt_block`

- **Source:** model-controlled `rule`, `source`, and `visibility_scope`

- **Sink:** system prompt text

- **Outcome:** persistent cross-bot instruction injection

**Model tool accepts claimed provenance** — `__init__.py:4430`

The caller controls both the alleged source and audience of the rule; `explicit` is the default.

```python
{"name":"memory_wiki_add_preference_rule","description":"Add/update a scoped first-class preference priority rule used by the preference layer.","parameters":P({"rule":{"type":"string"},"priority":{"type":"integer","default":100},"scope":{"type":"string","default":"global"},"source":{"type":"string","default":"explicit"},"status":{"type":"string","enum":["active","retired"],"default":"active"},"visibility_scope":{"type":"string","enum":["global","bot","chat","project","private"]},"project_id":{"type":"string"}}, ["rule"])},
```

**Unattested source and rule are stored** — `__init__.py:8180-8198`

Only a literal `system` label is rewritten; no host or user event authenticates `explicit`, and the caller-selected visibility is persisted.

```python
source = short(redact_secrets(str(a.get('source') or 'explicit')), 200)
if source.lower() == 'system':
    source = 'explicit'
...
c.execute("""INSERT INTO preference_rules(...,source,...,visibility_scope,...)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET ... source=excluded.source,...""",
          (rid, rule, priority, scope, source, status, ts, ts, h,owner['visibility_scope'],...))
```

**Source label grants system-prompt authority** — `__init__.py:3434-3469`

The renderer equates the self-asserted `explicit` source with trusted user provenance and turns the stored text into prompt instructions.

```python
trusted_exact = {"system", "explicit", "user", "user_correction", "explicit_correction"}
...
if source not in trusted_exact and not source.startswith(trusted_prefixes):
    continue
...
return (
    "# Trusted User Preference Layer\n"
    "These are active first-class preference rules with explicit/system provenance. "
    "Apply them as durable user preferences ...\n"
    + "\n".join(rendered)
)
```

**Trusted block is appended to system prompt** — `__init__.py:3471-3481`

The future system prompt consumes the preference text.

```python
trusted_preferences = self._trusted_preference_system_block()
return base + (("\n\n" + trusted_preferences) if trusted_preferences else "")
```

#### Reachability

The published memory tool is model-facing; a malicious influence must convince a model/tool caller to invoke it. The direct tool path itself needs no user provenance proof.

- **Attacker:** untrusted content author influencing a model-facing caller

- **Entry point:** memory_wiki_add_preference_rule

- **Outcome:** durable system-prompt instruction

#### Severity

**High** — Persistent cross-bot system-prompt instruction injection is a high-impact integrity failure. Exploitation requires a model/tool caller or successful inducement of that caller.

Additional runtime or deployment evidence could raise or lower this severity.

Impact assessment:
- **Level:** high
- **Why:** The rule can modify future assistant behavior and cross bot boundaries when global.

Likelihood assessment:
- **Level:** medium
- **Why:** Requires tool invocation by the model, which depends on prompt-injection success.

#### Remediation

Derive trusted preference provenance and audience from a host-attested user action. Store model-created rules as untrusted memory and keep them out of `system_prompt_block` until explicit user confirmation.

Tests:
- A model tool call with `source=explicit` cannot create a trusted system-prompt rule.
- A model tool call requesting global visibility cannot publish a trusted rule to another bot.
- A host-attested user preference appears only for its authorized audience.

Preventive controls:
- Use separate APIs/storage states for proposed model preferences and host-confirmed user preferences.

<a id="finding-2"></a>

### [2] Post-task and decision lists persist unredacted secrets

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | The tool schemas expose these fields and the implementation inserts their raw list/source values into SQLite before constructing a redacted claim. |
| Category | sensitive-data-exposure |
| CWE | CWE-312 |
| Affected lines | __init__.py:13654-13660, __init__.py:14213-14217 |

#### Summary

Model-facing post-task and decision tools copy array elements and source strings directly into auxiliary SQLite tables. Scalar fields use `normalize_claim()` for redaction, but these list fields bypass it and are included in full-store database backups.

#### Root Cause

The auxiliary write handlers sanitize some scalar strings through `normalize_claim()` but never apply the same secret filter to model-supplied list elements or source labels. They write the raw values directly to tables before the corresponding claim is generated, so claim-level filtering cannot prevent plaintext retention.

**Model supplies raw list fields** — `__init__.py:4402-4411`

Both published tools allow the model to submit arbitrary array elements and source labels.

```python
{"name":"memory_wiki_post_task", ... "changed_files":{"type":"array","items":{"type":"string"}},"backups":{"type":"array","items":{"type":"string"}}, ... "services":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"post_task"} ...}
{"name":"memory_wiki_add_decision", ... "alternatives":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"tool"} ...}
```

**Post-task arrays and source go to SQLite unchanged** — `__init__.py:13651-13661`

The scalar `verification` is sanitized, while list elements and `source` are serialized and stored without secret scanning or redaction.

```python
changed=list(a.get("changed_files") or []); backups=list(a.get("backups") or [])
verification=normalize_claim(a.get("verification") or ""); services=list(a.get("services") or []); source=a.get("source") or "post_task"
...
c.execute("INSERT OR IGNORE INTO post_task_log(...) VALUES(?,?,?,?,?,?,?,?,?)", (pid,summary,topic,json.dumps(changed,ensure_ascii=False),json.dumps(backups,ensure_ascii=False),verification,json.dumps(services,ensure_ascii=False),source,ts))
```

**Decision alternatives and source go to SQLite unchanged** — `__init__.py:14213-14216`

The alternative strings and source are inserted verbatim; the subsequent claim write cannot remove them from the auxiliary table.

```python
alts=list(a.get('alternatives') or []); ts=now(); h=sha(decision.lower()+rationale.lower()); did='dec_'+h[:12]
with self._connect() as c: c.execute('INSERT OR IGNORE INTO decisions(id,decision,rationale,topic,alternatives,source,created_at,hash) VALUES(?,?,?,?,?,?,?,?)',(did,decision,rationale,topic,json.dumps(alts,ensure_ascii=False),a.get('source') or 'tool',ts,h))
```

**Full backup copies SQLite database** — `__init__.py:14088-14099`

The auxiliary rows persist into the database copy used by host-level backup.

```python
self._conn.execute("VACUUM INTO ?", (str(backup_db_path),))
...
z.write(backup_db_path, 'memory_wiki.sqlite3')
```

#### Validation

Published tool schemas accept unrestricted string arrays. `_post_task` and `_add_decision` serialize those arrays and `source` into SQLite without calling `redact_secrets` on each element; the full backup includes that SQLite file.

Validation method: static source trace

**Model supplies raw list fields** — `__init__.py:4402-4411`

Both published tools allow the model to submit arbitrary array elements and source labels.

```python
{"name":"memory_wiki_post_task", ... "changed_files":{"type":"array","items":{"type":"string"}},"backups":{"type":"array","items":{"type":"string"}}, ... "services":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"post_task"} ...}
{"name":"memory_wiki_add_decision", ... "alternatives":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"tool"} ...}
```

**Post-task arrays and source go to SQLite unchanged** — `__init__.py:13651-13661`

The scalar `verification` is sanitized, while list elements and `source` are serialized and stored without secret scanning or redaction.

```python
changed=list(a.get("changed_files") or []); backups=list(a.get("backups") or [])
verification=normalize_claim(a.get("verification") or ""); services=list(a.get("services") or []); source=a.get("source") or "post_task"
...
c.execute("INSERT OR IGNORE INTO post_task_log(...) VALUES(?,?,?,?,?,?,?,?,?)", (pid,summary,topic,json.dumps(changed,ensure_ascii=False),json.dumps(backups,ensure_ascii=False),verification,json.dumps(services,ensure_ascii=False),source,ts))
```

**Decision alternatives and source go to SQLite unchanged** — `__init__.py:14213-14216`

The alternative strings and source are inserted verbatim; the subsequent claim write cannot remove them from the auxiliary table.

```python
alts=list(a.get('alternatives') or []); ts=now(); h=sha(decision.lower()+rationale.lower()); did='dec_'+h[:12]
with self._connect() as c: c.execute('INSERT OR IGNORE INTO decisions(id,decision,rationale,topic,alternatives,source,created_at,hash) VALUES(?,?,?,?,?,?,?,?)',(did,decision,rationale,topic,json.dumps(alts,ensure_ascii=False),a.get('source') or 'tool',ts,h))
```

**Full backup copies SQLite database** — `__init__.py:14088-14099`

The auxiliary rows persist into the database copy used by host-level backup.

```python
self._conn.execute("VACUUM INTO ?", (str(backup_db_path),))
...
z.write(backup_db_path, 'memory_wiki.sqlite3')
```

Limitations:
- No real credential or user database content was inspected.

#### Dataflow

model-controlled list/source -\> auxiliary INSERT -\> SQLite -\> host backup

- **Source:** post-task or decision tool argument

- **Sink:** post_task_log or decisions SQLite table

- **Outcome:** plaintext secret retention outside the secret vault

**Model supplies raw list fields** — `__init__.py:4402-4411`

Both published tools allow the model to submit arbitrary array elements and source labels.

```python
{"name":"memory_wiki_post_task", ... "changed_files":{"type":"array","items":{"type":"string"}},"backups":{"type":"array","items":{"type":"string"}}, ... "services":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"post_task"} ...}
{"name":"memory_wiki_add_decision", ... "alternatives":{"type":"array","items":{"type":"string"}},"source":{"type":"string","default":"tool"} ...}
```

**Post-task arrays and source go to SQLite unchanged** — `__init__.py:13651-13661`

The scalar `verification` is sanitized, while list elements and `source` are serialized and stored without secret scanning or redaction.

```python
changed=list(a.get("changed_files") or []); backups=list(a.get("backups") or [])
verification=normalize_claim(a.get("verification") or ""); services=list(a.get("services") or []); source=a.get("source") or "post_task"
...
c.execute("INSERT OR IGNORE INTO post_task_log(...) VALUES(?,?,?,?,?,?,?,?,?)", (pid,summary,topic,json.dumps(changed,ensure_ascii=False),json.dumps(backups,ensure_ascii=False),verification,json.dumps(services,ensure_ascii=False),source,ts))
```

**Decision alternatives and source go to SQLite unchanged** — `__init__.py:14213-14216`

The alternative strings and source are inserted verbatim; the subsequent claim write cannot remove them from the auxiliary table.

```python
alts=list(a.get('alternatives') or []); ts=now(); h=sha(decision.lower()+rationale.lower()); did='dec_'+h[:12]
with self._connect() as c: c.execute('INSERT OR IGNORE INTO decisions(id,decision,rationale,topic,alternatives,source,created_at,hash) VALUES(?,?,?,?,?,?,?,?)',(did,decision,rationale,topic,json.dumps(alts,ensure_ascii=False),a.get('source') or 'tool',ts,h))
```

**Full backup copies SQLite database** — `__init__.py:14088-14099`

The auxiliary rows persist into the database copy used by host-level backup.

```python
self._conn.execute("VACUUM INTO ?", (str(backup_db_path),))
...
z.write(backup_db_path, 'memory_wiki.sqlite3')
```

#### Reachability

Requires a model-facing tool call containing sensitive material; backup creation is trusted-host gated, and no cross-principal auxiliary read tool was established.

- **Attacker:** untrusted tool input or an agent processing a sensitive task

- **Entry point:** memory_wiki_post_task or memory_wiki_add_decision

- **Outcome:** secret remains in ordinary memory storage

#### Severity

**Medium** — A credential embedded in a task artifact path, service name, decision alternative, or caller-provided source is durably retained in plaintext SQLite and backups. Exploitation is local/shared-memory-context dependent; no direct remote read path was established.

Additional runtime or deployment evidence could raise or lower this severity.

Impact assessment:
- **Level:** high
- **Why:** Credential material can remain outside the dedicated secret storage boundary.

Likelihood assessment:
- **Level:** medium
- **Why:** Sensitive paths or alternatives can occur in task summaries, but no direct remote retrieval path was established.

#### Remediation

Validate type and size, then secret-scan and redact or reject every array element and `source` before inserting any auxiliary row; make auxiliary and claim writes atomic.

Tests:
- A post-task list containing a credential leaves no raw credential in post_task_log or a full backup.
- A decision alternative and source containing a credential leave no raw credential in decisions.
- A failed claim write cannot leave an unredacted auxiliary row.

Preventive controls:
- Centralize auxiliary-field sanitization for all model-facing durable writes.

## Reviewed Surfaces

| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| Model preference provenance and system prompt | prompt integrity | Reported | __init__.py:3432-3481,4430,5054,8175-8205 traced end to end. |
| Auxiliary post-task and decision writes | sensitive data retention | Reported | __init__.py:2728-2732,4402-4411,13651-13667,14075-14103,14213-14217 traced; scalar fields are redacted but arrays/source are not. |
| Document scope selection | access control | Rejected | The apparent empty-scope bypass needs an uninitialized/custom provider. Normal initialize() always supplies nonempty current_project_id(), and document scope validation then rejects mismatches (__init__.py:2868-2880,2995-2997; document_knowledge_graph.py:197-223). |

## Open Questions And Follow Up

- Most in-scope source files were not fully reviewed in this independent pass; the repository-wide coverage remains partial.
- Concurrent production edits after scan start may change the target snapshot before finalization.
