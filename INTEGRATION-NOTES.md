# Memory Wiki secret-broker integration 2.1

- `secret_index` хранит только безопасные metadata и внутренний `vault_ref`.
- Public query не возвращает `value`, `vault_ref` или произвольные metadata.
- `secret_index.value` для новых и мигрированных строк очищается.
- Secret write/migration отсутствуют в `get_tool_schemas()` и доступны локальной CLI.
- `_add_secret()` требует `_trusted_local_write=True`; scrub использует отдельный metadata-only trusted path.
- `metadata_json.allowed_executors` и locator задают fail-closed policy.
- Journal checkpoint всегда исключает secret values.
- Scrub fingerprints являются HMAC, а не обычным SHA-256.
- Ciphertext находится в `~/.hermes/vault/vault.sqlite3`.
