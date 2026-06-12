import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _get_aes_key() -> bytes:
    settings = get_settings()
    if not settings.encryption_key:
        raise ValueError(
            "ENCRYPTION_KEY no configurada. "
            'Generar con: python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"'
        )
    key = base64.b64decode(settings.encryption_key)
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY debe ser 32 bytes en base64")
    return key


def encrypt_value(plaintext: str) -> str:
    """Cifra un valor sensible (SSN, credenciales). Retorna base64(nonce + ciphertext)."""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def hash_for_audit(value: str) -> str:
    """Hash irreversible para audit log sin exponer el valor."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
