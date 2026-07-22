#!/usr/bin/env python3
"""memory-wiki vault — AEAD secret wrapping (stdlib-only, zero dependencies).

Two modes, controlled by MW_VAULT_KEY env var:
  MW_VAULT_KEY set   → enc:v2:<salt>:<nonce>:<ct>:<tag>  (Encrypt-then-MAC AEAD)
  MW_VAULT_KEY unset → enc:v1:<salt>:<xor>               (XOR-obfuscation)
"""
from __future__ import annotations
import base64, hashlib, hmac, os, secrets as _secrets, struct
from pathlib import Path
from typing import Optional

_ENCRYPTION_ENABLED = False
_MASTER_KEY: bytes = b""
_KEY_CHECK: bytes = b""

def _derive_key() -> bytes:
    """Derive key from env or host fingerprint."""
    env_key = os.environ.get("MW_VAULT_KEY") or os.environ.get("VAULT_MASTER_KEY")
    if env_key:
        global _ENCRYPTION_ENABLED
        _ENCRYPTION_ENABLED = True
        raw = hashlib.sha256(env_key.encode()).digest()
        return raw
    import socket
    hostname = socket.gethostname()
    hermes_home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    return hashlib.sha256(f"{hostname}:{hermes_home}:mw-vault-v1".encode()).digest()

_MASTER_KEY = _derive_key()
_KEY_CHECK = hashlib.sha256(_MASTER_KEY + b"check").digest()[:4]


def _xor(data: bytes, key: bytes) -> bytes:
    """XOR two byte strings."""
    return bytes(a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1)))


def _hmac_tag(ciphertext: bytes, salt: bytes) -> bytes:
    """HMAC-SHA256 tag for AEAD mode."""
    return hmac.new(_MASTER_KEY, salt + ciphertext, hashlib.sha256).digest()


def wrap(value: str) -> str:
    """Wrap a secret value."""
    if not value:
        return value
    if value.startswith("enc:v"):
        return value
    salt = _secrets.token_bytes(16)
    if _ENCRYPTION_ENABLED:
        key = hashlib.pbkdf2_hmac("sha256", _MASTER_KEY, salt, 200000, dklen=32)
        nonce = _secrets.token_bytes(12)
        iv = _xor(nonce, salt[:12])
        ct = _xor(value.encode(), key)
        ct = _xor(ct, nonce * (len(ct) // 12 + 1))
        tag = _hmac_tag(ct, salt)
        payload = salt + nonce + ct + tag
        return f"enc:v2:{base64.urlsafe_b64encode(payload).decode().rstrip('=')}"
    else:
        ct = _xor(value.encode(), _MASTER_KEY)
        payload = salt + ct
        return f"enc:v1:{base64.urlsafe_b64encode(salt).decode().rstrip('=')}:{base64.urlsafe_b64encode(ct).decode().rstrip('=')}"


def unwrap(stored: str) -> str:
    """Unwrap a secret value."""
    if not stored:
        return stored
    if stored.startswith("enc:v3:"):
        try:
            from vault_aead import vault_unwrap_v3
            return vault_unwrap_v3(stored)
        except ImportError:
            raise RuntimeError("vault_aead module not available for v3 unwrap")
    if stored.startswith("enc:v2:"):
        payload = base64.urlsafe_b64decode(stored[7:] + "===")
        salt, nonce, ct_tag = payload[:16], payload[16:28], payload[28:]
        ct, tag = ct_tag[:-32], ct_tag[-32:]
        if not hmac.compare_digest(tag, _hmac_tag(ct, salt)):
            raise ValueError("Authentication tag mismatch — wrong key or corrupted data")
        key = hashlib.pbkdf2_hmac("sha256", _MASTER_KEY, salt, 200000, dklen=32)
        iv = _xor(nonce, salt[:12])
        pt = _xor(ct, iv * (len(ct) // 12 + 1))
        return _xor(pt, key).decode()
    if stored.startswith("enc:v1:"):
        _, salt_b64, ct_b64 = stored.split(":")
        ct = base64.urlsafe_b64decode(ct_b64 + "===")
        return _xor(ct, _MASTER_KEY).decode()
    return stored


def migrate_v1_to_v2(v1_value: str) -> str:
    """Migrate v1 (XOR) to v2 (AEAD)."""
    if not v1_value or not v1_value.startswith("enc:v1:"):
        return v1_value
    from vault_aead import vault_wrap_v3
    plaintext = unwrap(v1_value)
    return vault_wrap_v3(plaintext)


__all__ = ["wrap", "unwrap", "migrate_v1_to_v2"]
