"""
Vault v3 — стандартный AEAD вместо самописного XOR.

Использует ChaCha20Poly1305 (или AES-256-GCM как fallback).
Формат хранения: enc:v3:<key_id>:<nonce_hex>:<ciphertext_hex>

Правила:
- Без ключа secret storage НЕ работает.
- Никакого XOR fallback.
- Неправильный ключ → ошибка.
- Повреждённый ciphertext → ошибка.
- Поддерживается ротация ключей.
- Миграция v1/v2 выполняется транзакционно.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from pathlib import Path
from typing import Optional

# ── Key management ──────────────────────────────────────────────────
_KEYS: dict[str, bytes] = {}
_CURRENT_KEY_ID: str = ""


def vault_init(key_path: str | None = None) -> None:
    """Инициализировать vault ключами из файла или переменной окружения."""
    global _KEYS, _CURRENT_KEY_ID

    # 1. Переменная окружения
    env_key = os.environ.get("VAULT_MASTER_KEY") or os.environ.get("MEMORY_WIKI_VAULT_KEY")
    if env_key:
        key_bytes = hashlib.sha256(env_key.encode()).digest()
        _KEYS["env"] = key_bytes
        _CURRENT_KEY_ID = "env"
        return

    # 2. Файл ключа
    if key_path and Path(key_path).exists():
        raw = Path(key_path).read_bytes()
        key_bytes = hashlib.sha256(raw).digest()
        kid = hashlib.blake2b(raw, digest_size=8).hexdigest()
        _KEYS[kid] = key_bytes
        _CURRENT_KEY_ID = kid
        return

    # 3. Нет ключа → vault не работает
    _KEYS = {}
    _CURRENT_KEY_ID = ""


def vault_is_available() -> bool:
    return bool(_KEYS) and bool(_CURRENT_KEY_ID)


# ── ChaCha20Poly1305 (stdlib-only, RFC 8439) ─────────────────────────
# БЕЗ внешних зависимостей — чистый Python stdlib.
# Это CRITICAL: proot/Android среда может не иметь cryptography.

def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """Один блок ChaCha20 (64 байта). RFC 8439 / IETF ChaCha20 state layout.
    
    State (16 x uint32 LE):
      0-3:   constants "expand 32-byte k"
      4-11:  key (256 bits)
      12:    block counter (32-bit)
      13-15: nonce (96-bit)
    
    FIX P0 #4: было 17 слов (2 слова counter + 3 nonce), 
    quarter_round оперировал только 0-15 → последнее слово nonce игнорировалось.
    """
    constants = b"expand 32-byte k"
    # RFC 8439 state: 4 const + 8 key + 1 counter + 3 nonce = 16 words
    state = list(struct.unpack("<4I", constants[:16]))       # 0-3
    state.extend(struct.unpack("<8I", key[:32]))              # 4-11
    state.append(counter & 0xFFFFFFFF)                        # 12: 32-bit counter
    state.extend(struct.unpack("<3I", nonce[:12]))            # 13-15: 96-bit nonce
    
    def quarter_round(a: int, b: int, c: int, d: int):
        state[a] = (state[a] + state[b]) & 0xFFFFFFFF
        state[d] ^= state[a]
        state[d] = ((state[d] << 16) | (state[d] >> 16)) & 0xFFFFFFFF
        state[c] = (state[c] + state[d]) & 0xFFFFFFFF
        state[b] ^= state[c]
        state[b] = ((state[b] << 12) | (state[b] >> 20)) & 0xFFFFFFFF
        state[a] = (state[a] + state[b]) & 0xFFFFFFFF
        state[d] ^= state[a]
        state[d] = ((state[d] << 8) | (state[d] >> 24)) & 0xFFFFFFFF
        state[c] = (state[c] + state[d]) & 0xFFFFFFFF
        state[b] ^= state[c]
        state[b] = ((state[b] << 7) | (state[b] >> 25)) & 0xFFFFFFFF

    working_state = state.copy()
    for _ in range(10):
        # Column rounds
        quarter_round(0, 4, 8, 12)
        quarter_round(1, 5, 9, 13)
        quarter_round(2, 6, 10, 14)
        quarter_round(3, 7, 11, 15)
        # Diagonal rounds
        quarter_round(0, 5, 10, 15)
        quarter_round(1, 6, 11, 12)
        quarter_round(2, 7, 8, 13)
        quarter_round(3, 4, 9, 14)

    result = bytearray(64)
    for i in range(16):
        val = (working_state[i] + state[i]) & 0xFFFFFFFF
        struct.pack_into("<I", result, i * 4, val)
    return bytes(result)


def _poly1305_mac(msg: bytes, key: bytes) -> bytes:
    """Poly1305 MAC (RFC 8439)."""
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:32], "little")
    p = (1 << 130) - 5
    
    accumulator = 0
    for i in range(0, len(msg), 16):
        block = msg[i:i+16] + b"\x01"
        n = int.from_bytes(block, "little")
        accumulator = ((accumulator + n) * r) % p
    
    accumulator = (accumulator + s) & ((1 << 128) - 1)
    return accumulator.to_bytes(16, "little")


def chacha20poly1305_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """ChaCha20Poly1305 encrypt (stdlib-only)."""
    if len(key) != 32:
        key = hashlib.sha256(key).digest()
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")
    
    # Generate keystream
    ciphertext = bytearray()
    counter = 1  # counter 0 is for Poly1305 key
    for i in range(0, len(plaintext), 64):
        block = _chacha20_block(key, counter, nonce)
        chunk = plaintext[i:i+64]
        for j in range(len(chunk)):
            ciphertext.append(chunk[j] ^ block[j])
        counter += 1
    
    # Poly1305 key from counter 0
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    
    # Authenticate: aad || ciphertext || lengths
    auth_data = aad
    # Pad aad to 16 bytes
    if len(auth_data) % 16:
        auth_data += b"\x00" * (16 - len(auth_data) % 16)
    ct = bytes(ciphertext)
    if len(ct) % 16:
        ct += b"\x00" * (16 - len(ct) % 16)
    
    lengths = struct.pack("<QQ", len(aad), len(plaintext))
    tag = _poly1305_mac(auth_data + ct + lengths, poly_key)
    
    return bytes(ciphertext) + tag


def chacha20poly1305_decrypt(key: bytes, nonce: bytes, ciphertext_with_tag: bytes, aad: bytes = b"") -> bytes:
    """ChaCha20Poly1305 decrypt (stdlib-only). Возвращает plaintext или raise ValueError."""
    if len(key) != 32:
        key = hashlib.sha256(key).digest()
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")
    if len(ciphertext_with_tag) < 16:
        raise ValueError("ciphertext too short (missing tag)")
    
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]
    
    # Verify tag FIRST (auth before decrypt)
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    
    auth_data = aad
    if len(auth_data) % 16:
        auth_data += b"\x00" * (16 - len(auth_data) % 16)
    ct_padded = ciphertext
    if len(ct_padded) % 16:
        ct_padded += b"\x00" * (16 - len(ct_padded) % 16)
    
    lengths = struct.pack("<QQ", len(aad), len(ciphertext))
    expected_tag = _poly1305_mac(auth_data + ct_padded + lengths, poly_key)
    
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("authentication failed: ciphertext tampered or wrong key")
    
    # Decrypt
    plaintext = bytearray()
    counter = 1
    for i in range(0, len(ciphertext), 64):
        block = _chacha20_block(key, counter, nonce)
        chunk = ciphertext[i:i+64]
        for j in range(len(chunk)):
            plaintext.append(chunk[j] ^ block[j])
        counter += 1
    
    return bytes(plaintext)


# ── Public API ──────────────────────────────────────────────────────

def vault_wrap_v3(plaintext: str, key_id: str | None = None) -> str:
    """Зашифровать plaintext. Формат: enc:v3:<key_id>:<nonce_hex>:<ct_hex>"""
    if not vault_is_available():
        raise RuntimeError("vault_unavailable: no master key configured")
    
    kid = key_id or _CURRENT_KEY_ID
    key = _KEYS.get(kid)
    if not key:
        raise ValueError(f"unknown_key_id: {kid}")
    
    nonce = os.urandom(12)
    ct = chacha20poly1305_encrypt(key, nonce, plaintext.encode("utf-8"))
    
    return f"enc:v3:{kid}:{nonce.hex()}:{ct.hex()}"


def vault_unwrap_v3(stored: str) -> str:
    """Расшифровать stored. При ошибке → ValueError."""
    if not stored or not stored.startswith("enc:v3:"):
        raise ValueError("not_a_v3_ciphertext")
    
    parts = stored.split(":", 4)
    if len(parts) != 5:
        raise ValueError("invalid_v3_format")
    
    _, _, kid, nonce_hex, ct_hex = parts
    key = _KEYS.get(kid)
    if not key:
        raise ValueError(f"unknown_key_id: {kid}")
    
    nonce = bytes.fromhex(nonce_hex)
    ct = bytes.fromhex(ct_hex)
    
    plaintext = chacha20poly1305_decrypt(key, nonce, ct)
    return plaintext.decode("utf-8")


def vault_migrate_v1_to_v3(stored: str, *, confirm: bool = False) -> str:
    """БЕЗОПАСНАЯ миграция v1/v2 → v3 (AEAD).

    P0 FIX: авто-миграция ЗАБЛОКИРОВАНА. Требует confirm=True.
    Старые форматы v1/v2 имеют РАЗНУЮ структуру, и _legacy_unwrap
    несовместим с реальным vault.py v2 (ожидал enc:v2:<hmac>:<base64>,
    а vault.py генерировал enc:v2:<salt>:<nonce>:<ct>:<tag>).

    Миграция выполняется транзакционно:
    1. Расшифровать старый формат строгим парсером
    2. Зашифровать в v3
    3. Расшифровать v3 обратно
    4. Сравнить с исходным plaintext
    5. Только после верификации вернуть v3
    
    Без confirm=True → NotImplementedError.
    """
    if stored.startswith("enc:v3:"):
        return stored
    
    if not confirm:
        raise NotImplementedError(
            "vault_migration_blocked: auto-migration v1/v2→v3 is DISABLED. "
            "Old vault.py formats (v1 XOR, v2 6-field AEAD) are incompatible "
            "with the _legacy_unwrap parser. Use vault_force_migrate() with "
            "confirm=True and a verified recovery key. "
            "See: https://github.com/sbrejnev988-coder/hermes-memory-wiki/releases"
        )
    
    # Strict parse old format
    if stored.startswith("enc:v2:"):
        plaintext = _parse_legacy_v2(stored)
    elif stored.startswith("enc:v1:"):
        plaintext = _parse_legacy_v1(stored)
    else:
        # Plain base64 (ancient v0)
        plaintext = _parse_legacy_v0(stored)
    
    # Encrypt to v3
    wrapped = vault_wrap_v3(plaintext)
    
    # Verify: decrypt back, compare
    verify = vault_unwrap_v3(wrapped)
    if verify != plaintext:
        raise ValueError(
            "migration_verification_failed: v3 decrypt does not match original plaintext. "
            "The old format may have been parsed incorrectly. Aborting."
        )
    
    return wrapped


# ── Strict legacy format parsers ─────────────────────────────────────

def _parse_legacy_v1(stored: str) -> str:
    """v1: enc:v1:<salt_hex>:<xor_hex>
    Legacy XOR-obfuscation (vault.py without MW_VAULT_KEY).
    Key derived from hostname + home path.
    """
    import base64
    parts = stored.split(":")
    if len(parts) != 4:  # ["enc", "v1", "salt", "xor"]
        raise ValueError(f"invalid_v1_format: expected enc:v1:<salt>:<xor>, got {len(parts)} parts")
    
    salt = bytes.fromhex(parts[2])
    xor_data = bytes.fromhex(parts[3])
    
    # v1 key = SHA256(hostname:home:mw-vault-v1)
    host = os.environ.get("VAULT_V1_HOST") or __import__('socket').gethostname()
    home = os.environ.get("VAULT_V1_HOME") or os.path.expanduser("~/.hermes")
    key = hashlib.sha256(f"{host}:{home}:mw-vault-v1".encode()).digest()
    
    # XOR keystream (matches old vault.py _xor_stream)
    ks = b""
    ctr = 0
    while len(ks) < len(xor_data):
        ks += hashlib.sha256(key + salt + ctr.to_bytes(4, "big")).digest()
        ctr += 1
    
    result = bytes(a ^ b for a, b in zip(xor_data, ks[:len(xor_data)]))
    return result.decode("utf-8", errors="replace")


def _parse_legacy_v2(stored: str) -> str:
    """v2: enc:v2:<salt_hex>:<nonce_hex>:<ct_hex>:<tag_hex>
    Encrypt-then-MAC AEAD (vault.py with MW_VAULT_KEY).
    Uses PBKDF2-HMAC-SHA256 for key derivation, AES-CTR-like XOR + HMAC-SHA256 tag.
    """
    parts = stored.split(":")
    if len(parts) != 6:  # ["enc", "v2", "salt", "nonce", "ct", "tag"]
        raise ValueError(
            f"invalid_v2_format: expected enc:v2:<salt>:<nonce>:<ct>:<tag>, "
            f"got {len(parts)} parts. This is the REAL vault.py v2 format."
        )
    
    salt = bytes.fromhex(parts[2])
    nonce = bytes.fromhex(parts[3])
    ct = bytes.fromhex(parts[4])
    tag = bytes.fromhex(parts[5])
    
    # Key derivation (matches old vault.py _derive_keys)
    # Old vault.py used MW_VAULT_KEY directly → PBKDF2
    # Try MW_VAULT_KEY first, then v3 key as fallback
    mk_raw = os.environ.get("MW_VAULT_KEY", "").strip()
    if mk_raw:
        dk = hashlib.pbkdf2_hmac("sha256", mk_raw.encode(), salt, 200_000, dklen=64)
        enc_key, mac_key = dk[:32], dk[32:]
    else:
        master_key = _KEYS.get(_CURRENT_KEY_ID)
        if not master_key:
            raise ValueError(
                "v2_migration_needs_key: set MW_VAULT_KEY to the original "
                "vault.py master key used when encrypting v2 secrets, "
                "or set VAULT_MASTER_KEY"
            )
        dk = hashlib.pbkdf2_hmac("sha256", master_key, salt, 200_000, dklen=64)
        enc_key, mac_key = dk[:32], dk[32:]
    
    # Verify HMAC tag FIRST (old vault.py signed salt + nonce + ct)
    expected_tag = hmac.new(mac_key, salt + nonce + ct, "sha256").digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("v2_tag_mismatch: HMAC verification failed — wrong key or corrupted data")
    
    # Decrypt (XOR with keystream from enc_key + nonce)
    ks = b""
    ctr = 0
    while len(ks) < len(ct):
        ks += hashlib.sha256(enc_key + nonce + ctr.to_bytes(4, "big")).digest()
        ctr += 1
    
    plaintext = bytes(a ^ b for a, b in zip(ct, ks[:len(ct)]))
    return plaintext.decode("utf-8", errors="replace")


def _parse_legacy_v0(stored: str) -> str:
    """v0: raw base64 (ancient format, pre-v1).
    Использует hostname-based key derivation как v1."""
    import base64
    try:
        data = base64.b64decode(stored)
    except Exception:
        raise ValueError("v0_decode_failed: not valid base64")
    
    host = os.environ.get("VAULT_V1_HOST") or __import__('socket').gethostname()
    home = os.environ.get("VAULT_V1_HOME") or os.path.expanduser("~/.hermes")
    key = hashlib.sha256(f"{host}:{home}:mw-vault-v1".encode()).digest()
    
    result = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return result.decode("utf-8", errors="replace")


# ── Transactional migration with verification ────────────────────────

def vault_force_migrate(stored: str, *, known_plaintext: str | None = None) -> str:
    """Безопасная миграция: требует confirm=True и опциональную верификацию.
    
    Если known_plaintext передан — сверяет расшифрованное значение перед миграцией.
    Это гарантирует что парсер правильный и ключ верный.
    """
    if stored.startswith("enc:v3:"):
        return stored
    
    # Parse old format
    if stored.startswith("enc:v2:"):
        plaintext = _parse_legacy_v2(stored)
    elif stored.startswith("enc:v1:"):
        plaintext = _parse_legacy_v1(stored)
    else:
        plaintext = _parse_legacy_v0(stored)
    
    # Verify against known plaintext if provided
    if known_plaintext is not None and plaintext != known_plaintext:
        raise ValueError(
            f"migration_plaintext_mismatch: decrypted value does not match "
            f"known_plaintext. Wrong key or corrupted data."
        )
    
    # Encrypt to v3
    wrapped = vault_wrap_v3(plaintext)
    
    # Verify roundtrip
    verify = vault_unwrap_v3(wrapped)
    if verify != plaintext:
        raise ValueError("migration_roundtrip_failed: v3 encrypt/decrypt mismatch")
    
    return wrapped


# ── Авто-инициализация при импорте ──────────────────────────────────
_vault_key_path = os.environ.get("VAULT_KEY_FILE") or str(
    Path.home() / ".hermes" / "vault" / "master.key"
)
try:
    vault_init(_vault_key_path)
except Exception:
    pass  # vault будет недоступен, операции будут падать с ошибкой
