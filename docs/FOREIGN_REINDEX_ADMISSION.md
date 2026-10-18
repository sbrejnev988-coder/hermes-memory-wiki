# Invisible foreign-vector full reindex: original admission

ADJ-REINDEX-FOREIGN-01 was a **conditional SOURCE mechanism**, not an observed
live leak. The invisible branch could reuse a compatible registered vector and
PUT it after canonical/registry/privacy/owner drift: only visible rows supplied
an original `_admit` callback. Later reconciliation could detect disagreement,
but did not prevent that PUT.

## Narrow plugin-only correction

- The existing `DisclosureFence` captures a fixed claim metadata projection and
  all of that claim's registry rows **before** source HTTP. Neither `claim`,
  `normalized_claim` nor `SELECT * FROM claims` is returned for this copy.
  SQLite evaluates the existing nonempty predicate as a boolean.
- The source verifier consumes that original registry, retains payload/manifest/
  vector compatibility checks and carries the same `admit_index` through source
  dispatch and response. Both verifier callers are bound: `index_row` and the
  read-only reconciliation/fast-path `expected_row_state`.
- Only after a genuine compatible response may the existing recorder write the
  destination intent. Its optional `_disclosure` path predicts the **complete**
  write_pending after-image before the original SQL, requires one affected row
  and exactly one total_changes increment, and verifies that image. The original
  authority, metadata, erasure and data_version anchors are never recaptured.
  Commit remains with the existing caller; a pending transaction is not admitted
  for dispatch. Trigger/callback effects, same-connection ABA and external ABA
  cannot be accounted as this one owned change.
- The same callback is passed unconditionally to the destination upsert and hence
  the existing `_qdrant_req` / `_observed_semantic_http` final before-dispatch
  seam, after request preparation. A sole active source-target row is not
  overwritten before verification, including source == destination.
- Missing/incompatible points and withdrawn admissions remain failed IDs in a
  partial/running job. No visibility, recall quality, scoped/outbox, native
  owner, reader/UNKNOWN or transport guards are relaxed. Synchronous admission
  is not an OS-atomic wire lease or remote-completion guarantee.

## Metadata-only erasure limit

The authenticated ledger and applied sequence must be current and unchanged.
Original claim-ID tombstones are checked with the actual owner matcher. If a
row is no newer than an applicable nonempty phrase tombstone, absence of a match cannot
be established without forbidden foreign text: that copy is withheld, not
hydrated or silently trusted. Unrelated owners, empty markers and rows newer
than the phrase tombstone retain their healthy metadata path. This conservative
case can reduce availability; it is not described as proof of a text match.

## Shipped checks and proof boundaries

| Entry | What it establishes | What it does not establish |
|---|---|---|
| `tests/ci_owned/foreign_reindex_cases.py` | Static old/current forwarding counterexample; actual generic SQLite metadata, epoch, registry, fixed-recorder/prediction, MAC/parser and erasure matching; real missing-owner refusal; exact cold-file metadata rebind | No healthy native admission, reindex/HTTP composition, actual PUT, SPI, host or live proof |
| `tests/test_foreign_reindex_admission.py` | Authored genuine-SPI regressions for three request seams, canonical/registry/ABA/erasure/owner/generation drift, compatible sole-source positive and unusable-source partial outcomes | These cases require separate genuine SDK/fixture admission; their presence is not execution |

The SOURCE entry is self-contained apart from exact product inputs. Invoke it
with existing `devtools/harness.py.run_source` under the selected `-I -B -S`
Python and synthetic scratch. To respect the permanent binding count/1MB bounds,
provide `FOREIGN_REINDEX_INPUTS.zlib`, a lossless UTF-8 JSON mapping for current
`__init__.py`, `disclosure_fence.py`, `shared_blocks.py`, `privacy_erasure.py`,
`current_scope_reindex.py`, and exact immutable `BEFORE/__init__.py` /
`BEFORE/current_scope_reindex.py`. Supply `COLD_LANES.json`,
`tests/cold_lane_entry.py`, independent complete test census carriers named
`COLD_TEST_INPUTS*.zlib`, and `COLD_ENTRY_INPUTS.zlib` for the manifest's named
source pins. All carriers are data, not loaders or alternative product sources;
the controller binds their SHA and verifies decoded raw bytes against the frozen
checkout before launch. Current native tests and peers are only parsed, not
imported by the SOURCE packet. No SDK stand-ins, profile_ready overrides,
protected settings, native/model/network children or broad old suites are used.

The lane RESULT records exact current commit/tree, source/carrier bindings,
actual case outcomes, child exits, audit/capture/supervisor/ownership, reservations
and budgets. Native/FULL/runtime/installed qualification remains **NOT_RUN**;
independent review and parent acceptance are separate.
