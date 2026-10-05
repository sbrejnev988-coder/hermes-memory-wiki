# Bounded fixture singleton review fix

- F01: capture the exact previous singleton before constructing the helper provider; restore only if the current singleton is that provider. An absent sentinel differs from `None`; a newer external singleton is untouched. Nested contexts restore LIFO before owner finalizers.
- S01: refusal is not release. Keep owned handles and previous-singleton metadata on worker refusal or close error; drop only successfully closed handles and restore the singleton only after a safe retry succeeds. Borrowed connections remain borrowed.
- Native Worker objects are never started. Close-error injection uses a real `sqlite3.Connection` subclass, not a provider, SDK, or SQL substitute. No GC is an oracle.
- S03: add a standalone same-item partial-init finalizer oracle; keep the historical ordered two-test oracle unchanged.
- Two RED/GREEN cycles only: 2/4 helper-context failures, then 6/8 ownership-retry failures. The final focused gate passes the original 27 plus 12 new cases; the partial-init oracle also passes as one independently selected item.
- Preserve identity through nested resource helpers because deleting a pointer early prevents the later owner finalizer from recognizing its resource. Keep refusal metadata because destructive cleanup cannot be retried after ownership has been discarded.
- These focused isolated runs do not approve full-suite, strict-mode, portable CI, future merged S02, publication, or live-worker behavior. Fresh independent review is still required.
