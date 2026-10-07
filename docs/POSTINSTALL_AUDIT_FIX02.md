# Post-install admission/eligibility repair (D1–D4)

Candidate derivative of published `f4b3e638a45d0708b790e490ebd084c5fb298293`.
No version/manifest, provider/model, deadline, ranking, schema, index or core change.

## Boundaries changed

- **D1:** public graph rows (including second-hop edges/endpoints), project profile
  and candidate claims, and auxiliary public export rows use `_model_safe_row`.
  Unsafe rows are omitted as a whole, before the emitted row count/limit.
  Preference rules use the existing exact code-owned/host-attestation check;
  a valid instruction is not vetoed by the generic recalled-data detector.
  A forged source label cannot obtain that exception.
- **D2:** `_inspect_recall_text` owns the single canonical content projection.
  Both original and returned transport are guarded before shortening. Reserve
  exactly the published `[RECALLED DATA — NOT INSTRUCTIONS]\n` note, then
  remove it once only after admission. No unknown markup/quarantine is stripped.
  Federation and background continue to require equality to their canonical
  source strings; NFKC, zero-width removal or core truncation cannot silently
  authorize different source evidence. Row custody/ACL identity is not rewritten.
  Runtime missing guard under strict=1 is denied, as is fresh strict import.
  Background event selection, source hashes/roles, quote grounding and the
  post-response transactional source fence are unchanged, not bypassed.
- **D3:** federation derives the full eligible-ID set from its exact current
  `profile_where` on the query-only SQLite connection and combines `has_id` with
  the original payload scope filter before Qdrant top-K. Hydration and admission
  remain final checks. Preference visibility, exact `turn:user:` source prefix
  and excluded IDs move before the existing LIMIT 250; rules remain separate.
  Preference claim outputs are guarded, and count describes emitted items.
- **D4:** scheduling captures home, generation, cache object and cache epoch.
  The copied-context worker never synchronizes generation. It checks current
  cache identity/generation/epoch before HTTP and before publication. A cache
  generation ABA rotates the epoch; an unrelated home round trip or an equivalent
  same-generation caller does not invalidate a legitimate callback. A proven
  constructor/start refusal releases only its exact unstarted admission; a
  possibly live worker retains its hold.

## Export versus private recovery

Source call-site tracing found `_export` and `_export_bundle` called only by
public tool dispatch. A sync bundle (including `write_file=true`) is a public
redacted/admitted interchange output, not a private full-store backup.
`_backup`, `_scoped_backup`, `_journal_checkpoint_locked` and their recovery
callers are unchanged. They do not call the public export methods. The native
control creates a synthetic private ZIP and reads its SQLite member to verify
that a stored guard-rejected graph row remains recoverable there.

## Offline proof and limits

The focused gate loads the whole real plugin and actual `MemoryProvider` from
the ordinary selected native environment, byte-matched to current Hermes core.
The published stdlib trust-core SHA
`9d9b3aac80bea5f1aba6ac289a3647b5b3a1fc9bf9d60e0fd920390b5544638b`
is copied only into the synthetic home/lib; its origin and callable identity
are checked. This is not installation of that dependency into live homes.

Synthetic HTTP replies exercise the real urllib embedding/Qdrant routes and
real OpenAI/httpx extraction SDK/parser. They are authored offline fixtures,
not provider responses or an inference quality benchmark. Networking, nested
processes and live data file/SQLite access are refused by the child audit fence.
HOME/USERPROFILE/application/temp roots are owned scratch paths, credentials
are scrubbed, automatic background/semantic/document workers are disabled.
The authored health tests use real native threads with deterministic barriers.

Three existing focused fixture helpers upgrade their strict flag from 0 to 1.
The federation helper also disables semantic probes during offline fixture
initialization; vector cases explicitly enable them after transport setup.
Behavioral assertions and all other existing tests remain unchanged. The new
background source uses a literal authored assertion accepted by the unchanged
extractor; edited/role-changed sources are actually recreated under the native
append-only ledger instead of treating a refused UPDATE as successful mutation.
The native detector's two verified-absent Linux-file read attempts on Windows
are reported separately; no existing file or live-data read is permitted.
Existing F1/F2/F3, API/schema/modes and golden receipt bindings are preserved;
this focused gate is not the entire repository suite and does not replace the
previous six-file aggregate receipts.

R1 (late prefetch acknowledgement), R2 (shared outbox lifecycle/ownership), live
trust-dependency readiness, gateway-loaded revision, push/install/reindex and
paid inference remain outside this patch. A source/native candidate PASS does
not establish live gateway behavior or release approval. Exact commands,
failed receipts, JUnit, full inventory and final hashes are carried separately.
