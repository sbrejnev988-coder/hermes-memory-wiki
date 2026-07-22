#!/usr/bin/env python3
"""memory-wiki vault_aead — ChaCha20Poly1305 AEAD vault (stdlib-only)."""
from __future__ import annotations
import hashlib, hmac, os, struct, time
from pathlib import Path

_KEYS: dict[str, bytes] = {}
_CURRENT_KEY_ID: str = ""

def vault_init(key_path: str | None = None) -> None:
    global _KEYS, _CURRENT_KEY_ID
    env_key = os.environ.get("VAULT_MASTER_KEY") or os.environ.get("MEMORY_WIKI_VAULT_KEY")
    if env_key:
        _KEYS["env"] = hashlib.sha256(env_key.encode()).digest()
        _CURRENT_KEY_ID = "env"
        return
    if key_path and Path(key_path).exists():
        raw = Path(key_path).read_bytes()
        _KEYS[hashlib.blake2b(raw, digest_size=8).hexdigest()] = hashlib.sha256(raw).digest()
        _CURRENT_KEY_ID = hashlib.blake2b(raw, digest_size=8).hexdigest()
        return
    _KEYS, _CURRENT_KEY_ID = {}, ""

def vault_is_available() -> bool: return bool(_KEYS) and bool(_CURRENT_KEY_ID)

def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    constants = b"expand 32-byte k"
    state = list(struct.unpack("<4I", constants[:16]))
    state.extend(struct.unpack("<8I", key[:32]))
    state.append(counter & 0xFFFFFFFF)
    state.extend(struct.unpack("<3I", nonce[:12]))
    def _rotl(v,c): return ((v<<c)|(v>>(32-c)))&0xFFFFFFFF
    def _qr(a,b,c,d):
        a=(a+b)&0xFFFFFFFF; d^=a; d=_rotl(d,16)
        c=(c+d)&0xFFFFFFFF; b^=c; b=_rotl(b,12)
        a=(a+b)&0xFFFFFFFF; d^=a; d=_rotl(d,8)
        c=(c+d)&0xFFFFFFFF; b^=c; b=_rotl(b,7)
        return a,b,c,d
    w=list(state)
    for _ in range(10):
        w[0],w[4],w[8],w[12]=_qr(w[0],w[4],w[8],w[12])
        w[1],w[5],w[9],w[13]=_qr(w[1],w[5],w[9],w[13])
        w[2],w[6],w[10],w[14]=_qr(w[2],w[6],w[10],w[14])
        w[3],w[7],w[11],w[15]=_qr(w[3],w[7],w[11],w[15])
        w[0],w[5],w[10],w[15]=_qr(w[0],w[5],w[10],w[15])
        w[1],w[6],w[11],w[12]=_qr(w[1],w[6],w[11],w[12])
        w[2],w[7],w[8],w[13]=_qr(w[2],w[7],w[8],w[13])
        w[3],w[4],w[9],w[14]=_qr(w[3],w[4],w[9],w[14])
    return b''.join(struct.pack("<I",(w[i]+state[i])&0xFFFFFFFF) for i in range(16))

def _chacha20_encrypt(key, counter, nonce, plaintext):
    r=bytearray()
    for i in range(0,len(plaintext),64):
        b=_chacha20_block(key,counter+i//64,nonce);c=plaintext[i:i+64]
        r.extend(x^y for x,y in zip(c,b[:len(c)]))
    return bytes(r)

def _poly1305_mac(msg, key):
    r=int.from_bytes(key[:16],"little")&0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s=int.from_bytes(key[16:],"little");acc=0;p=(1<<130)-5
    for i in range(0,len(msg),16):
        n=int.from_bytes(msg[i:i+16]+b"\x01","little");acc=((acc+n)*r)%p
    return int.to_bytes((acc+s)&((1<<128)-1),16,"little")

def _aead_encrypt(key, nonce, plaintext, aad=b""):
    pk=_chacha20_block(key,0,nonce)[:32];ct=_chacha20_encrypt(key,1,nonce,plaintext)
    mi=bytearray(aad)
    if len(aad)%16: mi.extend(b"\x00"*(16-len(aad)%16))
    mi.extend(ct)
    if len(ct)%16: mi.extend(b"\x00"*(16-len(ct)%16))
    mi.extend(struct.pack("<Q",len(aad)));mi.extend(struct.pack("<Q",len(ct)))
    return ct+_poly1305_mac(bytes(mi),pk)

def _aead_decrypt(key, nonce, ct_tag, aad=b""):
    if len(ct_tag)<16: raise ValueError("Ciphertext too short")
    ct,tag=ct_tag[:-16],ct_tag[-16:]
    pk=_chacha20_block(key,0,nonce)[:32]
    mi=bytearray(aad)
    if len(aad)%16: mi.extend(b"\x00"*(16-len(aad)%16))
    mi.extend(ct)
    if len(ct)%16: mi.extend(b"\x00"*(16-len(ct)%16))
    mi.extend(struct.pack("<Q",len(aad)));mi.extend(struct.pack("<Q",len(ct)))
    if not hmac.compare_digest(tag,_poly1305_mac(bytes(mi),pk)):
        raise ValueError("Authentication tag mismatch")
    return _chacha20_encrypt(key,1,nonce,ct)

def vault_wrap_v3(value: str) -> str:
    if not value or not vault_is_available():
        raise RuntimeError("Vault unavailable")
    k=_KEYS[_CURRENT_KEY_ID];s=os.urandom(32)
    n=hashlib.sha256(s+b"mw-vault-v3").digest()[:12]
    aad=b"mw-vault-v3"+_CURRENT_KEY_ID.encode()+s
    ct=_aead_encrypt(k,n,value.encode(),aad)
    return f"enc:v3:{_CURRENT_KEY_ID}:{s.hex()}:{ct.hex()}"

def vault_unwrap_v3(stored: str) -> str:
    if not stored or not stored.startswith("enc:v3:"):
        raise ValueError(f"Not a v3 value")
    _,_,kid,sh,cth=stored.split(":")
    s=bytes.fromhex(sh);ct=bytes.fromhex(cth)
    k=_KEYS.get(kid) or (_KEYS.get(_CURRENT_KEY_ID) if kid=="env" else None)
    if not k: raise ValueError(f"Unknown key_id '{kid}'")
    n=hashlib.sha256(s+b"mw-vault-v3").digest()[:12]
    aad=b"mw-vault-v3"+kid.encode()+s
    return _aead_decrypt(k,n,ct,aad).decode()

if __name__ == "__main__":
    os.environ["VAULT_MASTER_KEY"]="test-key"
    vault_init()
    w=vault_wrap_v3("secret-123")
    assert vault_unwrap_v3(w)=="secret-123"
    print("vault_aead: OK")
