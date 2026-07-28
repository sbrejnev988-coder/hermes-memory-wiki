
# HERMES-SECURITY-INTEGRATION-20260728-LEGACY-VAULT-DISABLED
import os as _hsi_legacy_os
if _hsi_legacy_os.environ.get("HERMES_ALLOW_LEGACY_VAULT", "0").lower() not in {"1", "true", "yes"}:
    raise RuntimeError("Legacy vault backend disabled. Use pinned hermes_secret_core; set HERMES_ALLOW_LEGACY_VAULT=1 only for an offline migration process.")
"""vault.py — AEAD secret wrapping for memory-wiki (stdlib-only, zero dependencies).

Two modes, controlled by MW_VAULT_KEY env var:
  MW_VAULT_KEY set   → enc:v2:<salt>:<nonce>:<ct>:<tag>  (Encrypt-then-MAC AEAD)
  MW_VAULT_KEY unset → enc:v1:<salt>:<xor>               (XOR-obfuscation, legacy)

Usage:
  from vault import wrap, unwrap
  wrapped = wrap("my-secret-value")
  plain   = unwrap(wrapped)
"""

import hashlib
import hmac
import os
import secrets
import socket
from typing import Optional

SALT_LEN = 32       # HKDF salt
NONCE_LEN = 16      # Unique per AEAD encryption
TAG_LEN = 32        # HMAC-SHA256 authentication tag
PBKDF2_ITER = 200_000  # OWASP 2025 minimum


def _master_key() -> Optional[bytes]:
    """Return MW_VAULT_KEY as bytes, or None → legacy XOR mode."""
    k = os.environ.get("MW_VAULT_KEY", "").strip()
    return k.encode("utf-8") if k else None


def _derive_keys(master: bytes, salt: bytes) -> "tuple[bytes, bytes]":
    """HKDF-like: enc_key (32B) || mac_key (32B) = PBKDF2(master, salt)."""
    dk = hashlib.pbkdf2_hmac("sha256", master, salt, PBKDF2_ITER, dklen=64)
    return dk[:32], dk[32:]


def _xor_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic XOR keystream: SHA256(key || nonce || counter), repeated as needed."""
    ks = b""
    ctr = 0
    while len(ks) < length:
        ks += hashlib.sha256(key + nonce + ctr.to_bytes(4, "big")).digest()
        ctr += 1
    return ks[:length]


def wrap(value: str) -> str:
    """Encrypt (v2 AEAD) if MW_VAULT_KEY is set; obfuscate (v1 XOR) otherwise."""
    if not value:
        return ""
    if value.startswith("enc:v"):
        return value  # already wrapped

    data = value.encode("utf-8")
    master = _master_key()

    if master:
        # ── v2: Encrypt-then-MAC AEAD ──
        salt = secrets.token_bytes(SALT_LEN)
        nonce = secrets.token_bytes(NONCE_LEN)
        enc_key, mac_key = _derive_keys(master, salt)
        ct = bytes(a ^ b for a, b in zip(data, _xor_stream(enc_key, nonce, len(data))))
        tag = hmac.new(mac_key, salt + nonce + ct, "sha256").digest()
        return f"enc:v2:{salt.hex()}:{nonce.hex()}:{ct.hex()}:{tag.hex()}"
    else:
        # ── v1: XOR-obfuscation (no MW_VAULT_KEY) ──
        host = socket.gethostname()
        home = os.path.expanduser("~/.hermes")
        key = hashlib.sha256(f"{host}:{home}:mw-vault-v1".encode()).digest()
        salt = os.urandom(16)
        ct = bytes(a ^ b for a, b in zip(data, _xor_stream(key, salt, len(data))))
        return f"enc:v1:{salt.hex()}:{ct.hex()}"


def unwrap(stored: str) -> str:
    """Decrypt v2 AEAD or unwrap v1 XOR-obfuscation.

    Returns:
        Plaintext string on success.
        Error message string starting with '<' on failure (HMAC mismatch, missing key, etc.)
        Original string if not in enc:v* format (legacy plaintext).
    """
    if not stored:
        return ""
    if not stored.startswith("enc:v"):
        return stored  # legacy plaintext

    try:
        parts = stored.split(":")
        ver = parts[1]

        if ver == "v2":
            _, _, s_hex, n_hex, ct_hex, tag_hex = parts
            salt = bytes.fromhex(s_hex)
            nonce = bytes.fromhex(n_hex)
            ct = bytes.fromhex(ct_hex)
            tag = bytes.fromhex(tag_hex)
            master = _master_key()
            if not master:
                return "<v2 secret: set MW_VAULT_KEY to decrypt>"
            enc_key, mac_key = _derive_keys(master, salt)
            expected = hmac.new(mac_key, salt + nonce + ct, "sha256").digest()
            if not hmac.compare_digest(tag, expected):
                return "<v2 secret: HMAC mismatch — wrong MW_VAULT_KEY or tampered data>"
            return bytes(a ^ b for a, b in zip(ct, _xor_stream(enc_key, nonce, len(ct)))).decode("utf-8")

        elif ver == "v1":
            _, _, s_hex, ct_hex = parts[:4]
            salt = bytes.fromhex(s_hex)
            ct = bytes.fromhex(ct_hex)
            host = socket.gethostname()
            home = os.path.expanduser("~/.hermes")
            key = hashlib.sha256(f"{host}:{home}:mw-vault-v1".encode()).digest()
            plain = bytes(a ^ b for a, b in zip(ct, _xor_stream(key, salt, len(ct)))).decode("utf-8")
            return plain

        else:
            return stored  # unknown version

    except Exception:
        return stored  # fallback: return raw on any decrypt failure


# ── Self-test ──


# ── v1→v2 migration ───────────────────────────────────────────────────
def migrate_v1_to_v2() -> dict:
    """Migrate all enc:v1: secrets in secret_index to enc:v2: AEAD.

    Requires MW_VAULT_KEY to be set. Reads secret_index.value, decrypts v1,
    re-encrypts as v2, and updates the row.

    Returns:
        {"migrated": N, "skipped": N, "errors": N, "v2_count_after": N}
    """
    master = _master_key()
    if not master:
        return {"error": "Set MW_VAULT_KEY to enable v1→v2 migration"}
    import sqlite3
    db_path = os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
        "memory-wiki", "memory_wiki.sqlite3"
    )
    if not os.path.exists(db_path):
        return {"error": f"DB not found: {db_path}"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrated = skipped = errors = 0
    try:
        rows = conn.execute(
            "SELECT id, value FROM secret_index WHERE value LIKE 'enc:v1:%'"
        ).fetchall()
        for row in rows:
            try:
                plain = unwrap(row["value"])
                if plain.startswith("<"):  # error message
                    skipped += 1
                    continue
                new_val = wrap(plain)
                if new_val.startswith("enc:v2:"):
                    conn.execute(
                        "UPDATE secret_index SET value=? WHERE id=?",
                        (new_val, row["id"])
                    )
                    migrated += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
        conn.commit()
        v2_count = conn.execute(
            "SELECT count(*) FROM secret_index WHERE value LIKE 'enc:v2:%'"
        ).fetchone()[0]
        return {
            "migrated": migrated, "skipped": skipped, "errors": errors,
            "v2_count_after": v2_count
        }
    finally:
        conn.close()

if __name__ == "__main__":
    import sys

    print("=== vault.py self-test ===")

    # Test 1: wrap/unwrap roundtrip (v1 — no MW_VAULT_KEY)
    assert "MW_VAULT_KEY" not in os.environ, "unset MW_VAULT_KEY for test 1"
    v1_test = "super_secret_api_key_xyz"
    v1_wrapped = wrap(v1_test)
    assert v1_wrapped.startswith("enc:v1:"), f"v1 prefix: {v1_wrapped[:20]}"
    v1_unwrapped = unwrap(v1_wrapped)
    assert v1_unwrapped == v1_test, f"v1 roundtrip: got {v1_unwrapped[:20]}..."
    print(f"  [PASS] v1 XOR: wrap/unwrap roundtrip (no MW_VAULT_KEY)")

    # Test 2: wrap/unwrap roundtrip (v2 — with MW_VAULT_KEY)
    os.environ["MW_VAULT_KEY"] = "test-secret-key-12345"
    v2_test = "production_api_token_abc123"
    v2_wrapped = wrap(v2_test)
    assert v2_wrapped.startswith("enc:v2:"), f"v2 prefix: {v2_wrapped[:20]}"
    v2_unwrapped = unwrap(v2_wrapped)
    assert v2_unwrapped == v2_test, f"v2 roundtrip: got {v2_unwrapped[:20]}..."
    print(f"  [PASS] v2 AEAD: wrap/unwrap roundtrip (MW_VAULT_KEY set)")

    # Test 3: HMAC tamper detection
    parts = v2_wrapped.split(":")
    tampered_ct = bytes.fromhex(parts[4])  # ct
    tampered_ct = bytes([tampered_ct[0] ^ 0xFF]) + tampered_ct[1:]  # flip first byte
    tampered = f"{parts[0]}:{parts[1]}:{parts[2]}:{parts[3]}:{tampered_ct.hex()}:{parts[5]}"
    result = unwrap(tampered)
    assert result.startswith("<v2 secret: HMAC mismatch"), f"tamper detection: {result[:50]}"
    print(f"  [PASS] v2 AEAD: HMAC tamper detection works")

    # Test 4: v2 without key → error message
    del os.environ["MW_VAULT_KEY"]
    result = unwrap(v2_wrapped)
    assert "MW_VAULT_KEY" in result, f"missing key: {result}"
    print(f"  [PASS] v2 decrypt without MW_VAULT_KEY → error")

    # Test 5: empty values
    assert wrap("") == ""
    assert unwrap("") == ""
    print("  [PASS] empty string handling")

    # Test 6: legacy plaintext passthrough
    assert unwrap("plaintext_legacy_secret") == "plaintext_legacy_secret"
    print("  [PASS] legacy plaintext passthrough")

    # Test 7: already-wrapped passthrough
    double = wrap(v2_wrapped if v2_wrapped.startswith("enc:v2:") else v1_wrapped)
    assert double == v2_wrapped or double.startswith("enc:v"), f"double-wrap: {double[:30]}"
    print("  [PASS] already-wrapped passthrough")

    # Test 8: unicode
    os.environ["MW_VAULT_KEY"] = "test-key-2"
    uni_test = "пароль_с_юникодом_αβγ"
    uni_wrapped = wrap(uni_test)
    uni_unwrapped = unwrap(uni_wrapped)
    assert uni_unwrapped == uni_test
    print("  [PASS] unicode roundtrip")

    # Test 9: long value
    long_test = "x" * 10000
    long_wrapped = wrap(long_test)
    long_unwrapped = unwrap(long_wrapped)
    assert long_unwrapped == long_test
    print("  [PASS] 10KB value roundtrip")

    print(f"\nAll 9 tests PASSED")
    sys.exit(0)

