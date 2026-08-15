# Used to conceal LLM access
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet

secret_key = "Mgx@FunctionSea"
key_prefix = "mgxkey-"
_KNOWN_WEAK_MASK_KEYS = {
    secret_key,
    "replace-with-a-long-random-mask-key",
    "dev-secret-change-me",
}


def _is_production_env() -> bool:
    value = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return value in {"prod", "production"}


def validate_mask_crypto_config() -> None:
    """Reject public, missing, or undersized encryption keys in production."""
    configured = (os.getenv("MASK_KEY") or "").strip()
    is_weak = (
        len(configured) < 32
        or configured.lower() in {value.lower() for value in _KNOWN_WEAK_MASK_KEYS}
        or "replace-with" in configured.lower()
    )
    if is_weak:
        message = "MASK_KEY must be a stable, non-placeholder secret of at least 32 characters before production use"
        if _is_production_env():
            raise RuntimeError(message)
        logging.getLogger(__name__).warning(message)


def _resolve_mask_key() -> str:
    configured = (os.getenv("MASK_KEY") or "").strip()
    if _is_production_env():
        validate_mask_crypto_config()
        return configured
    return configured or secret_key


def _derive_fernet_key(key_material: str) -> bytes:
    """Derive a valid Fernet key from arbitrary string using SHA-256 and urlsafe base64."""
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)


def _get_fernet(key_str: str) -> Fernet:
    key = _derive_fernet_key(key_str)
    return Fernet(key)


def encrypt_text(plain: str) -> str:
    pwd = _resolve_mask_key()
    f = _get_fernet(pwd)
    return key_prefix + f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(token: str) -> str:
    pwd = _resolve_mask_key()
    f = _get_fernet(pwd)
    token = token.removeprefix(key_prefix)
    return f.decrypt(token.encode("utf-8")).decode("utf-8")
