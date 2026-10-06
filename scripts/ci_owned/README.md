# Source-only native CI overlay — parent handoff

Base: `438e0b57cb44470c2d47b9210941bea177d379f1`.
Official native core pin remains `NousResearch/hermes-agent@d526f14714ce8a95cafd7f3a95d1eab5b6e0b910`.
All overlay paths are new relative to the base; the old test/release workflows are unchanged.
Do not copy a live Hermes home, configuration, auth store, memory, backup or environment.
No commit, push or Actions dispatch was performed by this preparation lane.

## CI-specific bootstrap: registration is separate from source acceptance

1. Obtain independent CI-only approval of the **current** `overlay.patch` and
   `overlay-manifest.json`, including CI-NATIVE-01's launch recorder/validator.
   The older frozen seven-file overlay and its failed review are not approval of
   this revision. The current manifest lists nine CI paths, including the two
   added recorder/validator-unit files.
2. After that approval only, parent may publish **only those exact reviewed CI
   paths** on **default main**, based on the verified public base. This is
   CI-only registration: no unaccepted whole-plugin implementation, no rejected
   source composition, no release/tag/wheel approval, and **no force push**.
   Do not edit general installation/release guides as part of this overlay.
3. Verify **workflow registration** by reading back the exact workflow on default
   main and its registered workflow identity/status. Read back all CI file bytes
   against the approved manifest. `workflow_dispatch` needs the workflow file on
   the default branch; creating it only on a source branch is not bootstrap.
   Preserve manual-only `workflow_dispatch`; do not add push/PR triggers.
4. Independently accept the full Memory Wiki source composition. It must include
   the same reviewed CI runner/test bytes, while preserving full ordinary test
   discovery and all six recovery assertions. Freeze/publish it on a source branch
   as an exact literal lowercase 40-hex commit, named **`source_sha`**. Do not use
   a candidate, current HEAD, release tag or default-branch fallback as acceptance.
   Historical strict-xfail requirement tests remain source blockers; the gate must
   not weaken xfail/skip handling or exclude tests to manufacture green.
5. Select an explicitly trusted **trusted workflow ref** containing the registered,
   reviewed workflow. Parent alone may dispatch that workflow from this chosen
   ref, supplying the independently accepted exact `source_sha` as input.
   **Workflow ref and source_sha are distinct identities/roles**: the former
   selects workflow code, the latter selects plugin/runner source to checkout.
   Never infer one from the other. Record both immutable resolutions and run ID.
6. Inspect complete current-run Windows/Linux matrix evidence bound to the exact
   source digest and core: launches, bindings, coverage decision, actual native
   origins/MRO, phase reports, complete JUnit and recovery observations. Any missing,
   unbound, abnormal or failed child/lane blocks acceptance. Only then may a future
   release tag be bound to that same proven source commit, through a separate
   parent-controlled release gate. Registration or passing validator units alone
   does not authorize release, installation, strict-security or live-profile changes.

## What runs and what the recorder proves

- Hosted Windows/Linux, Python 3.11–3.14, separate FULL/recovery jobs: sixteen
  native lanes, maximum two simultaneous jobs. Jobs have a 45-minute timeout;
  child budgets remain 1800 seconds FULL / 600 seconds recovery.
- FULL still uses `pytest.main(['-q', 'tests', ...])`, without `-k`, exclusions or
  restoration of rejected bytes. Source acceptance belongs to the parent.
- Recovery explicitly runs the retained six tests in `tests/ci_owned/recovery_cases.py`,
  byte-exact and without skips. Failures are real source blockers, not permission
  to weaken journal secrecy, references, history or transaction assertions.
- The old nine `contract_cases.py` units and the new `binding_cases.py` cases are
  stdlib preparation units. Their synthetic identity/role/failure dictionaries and
  publication-fault callbacks are **not native E2E evidence** or SDK replacements.
- Genuine native exports and `MemoryProvider` are imported from the pinned public
  core. Base origin/hash, source origin/hash and per-process plugin MRO remain
  mandatory. No native SDK/auth/trust module is replaced or mocked.
- The CI `.pth` and small stdlib Popen recorder exist only in a disposable hosted
  dependency venv/process. Each supported launch gets a unique nonce, owner/run
  identity, explicit role, command digest and an observed creation PID/exit code.
  The child binds its actual PID (or explicit Windows-venv launcher relation),
  native base and final plugin classes to that same nonce. This is evidence
  instrumentation, not the rejected local controller, FD or Job implementation.
- The primary is explicitly plugin-bearing. Ordinary same-interpreter Python
  descendants are `plugin_capable`: they must finish cleanly, and any observed
  plugin execution requires their own valid MRO record. A finished parent cannot
  cover a missing, startup-only, unbound or failed child. The aggregate rereads
  actual uploaded launch/binding inventory instead of trusting a green boolean.
- `-S` (including combined flags), foreign interpreters, shell launches and
  unrecognized/raw process-launch APIs are durably recorded and fail closed.
  Direct fork/spawn/CreateProcess shapes outside the recorder are not silently
  covered by a `.pth`. Supporting a new shape requires a separately reviewed
  evidence path, not an automatic exemption or a skipped historical assertion.
- There is **no default killed-worker exemption**. A reviewed synthetic non-plugin
  worker may use `recorder.expect_nonplugin(command, reason)` for one exact launch:
  this scopes the lifecycle expectation and binds command plus worker-file bytes.
  Acceptance of an unfinished receipt additionally needs pre-execution actual
  native-base evidence, an armed plugin-execution denial guard, no plugin classes
  or violations, and a parent-observed nonzero exit other than bootstrap code 86.
  No exception is preconfigured for existing FULL tests; parent must explicitly
  approve/test any such expectation in source. Unfinished generic/plugin workers
  stay blocked. A bootstrap/finalization failure always blocks, even in that scope.
- Failure state is atomically replaced/flushed before abnormal bootstrap exit.
  If storage itself fails, absent/corrupt inventory cannot become positive proof.
  Neither natural-exit nor descendant-cleanup/Windows Job guarantees are invented.
- The allowlisted child environment uses synthetic HOME/HERMES_HOME, AppData/XDG
  and TEMP paths, without ambient credentials. Python audit hooks allow loopback
  fixtures and deny external DNS/networking. This is not an OS network sandbox.
  Security policy0 remains synthetic-test-only, not live strict-security proof.

## No skip counted as pass; artifact boundary

Receipts preserve setup/call/teardown and complete JUnit accounting. A lane with
skips is not accepted individually. Aggregate coverage still requires all sixteen
lanes, identical source bytes, equal OS collection, zero failed/incomplete/unbound
lanes, and an actual complete pass on at least one OS per node per Python version.
All six recovery assertions must pass on both OSes. Universal skips, xfail/XPASS,
collection/setup/teardown errors, timeout and missing receipts cannot become green.

Uploads name individual safe receipt/log/JUnit/origin/launch/binding/coverage and
recovery-observation files, including failures. They never upload whole workspaces,
source trees, synthetic databases/homes, private auth/configuration or backups.
Cache sharing, OIDC, secret expressions and persisted checkout credentials remain absent.

## Preparation and pin decision boundary

Local validation is limited to isolated stdlib units, AST/compile, frozen public
source metadata and patch readback/replay. Never run local FULL/recovery, install
native dependencies, or set GITHUB_ACTIONS/RUNNER_ENVIRONMENT to bypass admission.
Those variables are policy checks, not tamper-resistant hosted identity.

The existing release workflow's `5307e93252ac655cd13fadbd561c0995142138c6`
minimum-SDK pin is not d526/current-core proof. Owner's newly clean current core
checkout `8b66a51036c1e20920a17cdd049fdf55c968d683` was not imported by this lane.
**Parent decision required:** retain and prove d526 as this gate's target, and
separately retain/prove the release minimum compatibility; or approve an explicit
new core-pin/compatibility revision with fresh independent review and hosted
native evidence. This overlay does not silently repin, copy current core, drop
minimum compatibility or claim current-runtime proof.

Hosted native import closure and full Windows/Linux process-shape coverage remain
unverified until parent acceptance/dispatch. A conservative refusal may expose an
existing launch shape needing explicit reviewed evidence; do not auto-exclude its
test or call this gate green from unit success. No exhausted local controller,
FD or Job budget was reset. Installation/live profiles remain outside this lane.
