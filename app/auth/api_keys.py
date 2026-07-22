"""API key generation and hashing."""

from __future__ import annotations

import hashlib
import secrets

import bcrypt

API_KEY_PREFIX = "gw-sk-"
API_KEY_LOOKUP_LENGTH = 12
BCRYPT_ROUNDS = 12


def generate_api_key() -> str:
    """Create a new project API key. Show to the user once — only the hash is stored."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def api_key_lookup_prefix(api_key: str) -> str:
    """Return a short lookup segment stored in PostgreSQL for indexed auth."""
    secret = api_key.removeprefix(API_KEY_PREFIX)
    return secret[:API_KEY_LOOKUP_LENGTH]


def hash_api_key(api_key: str) -> str:
    """Hash an API key with bcrypt for storage."""
    hashed = bcrypt.hashpw(
        api_key.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    )
    return hashed.decode("utf-8")


def prepare_stored_api_key(api_key: str) -> tuple[str, str]:
    """Return (lookup_prefix, bcrypt_hash) for persisting a new key."""
    return api_key_lookup_prefix(api_key), hash_api_key(api_key)


def is_legacy_sha256_hash(stored_hash: str) -> bool:
    """Detect pre-Phase-8 SHA-256 hex digests."""
    return (
        len(stored_hash) == 64
        and all(char in "0123456789abcdef" for char in stored_hash.lower())
    )


def legacy_sha256_hash(api_key: str) -> str:
    """Previous storage format — kept for backward compatibility during migration."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Verify an incoming key against a stored bcrypt or legacy SHA-256 hash."""
    if is_legacy_sha256_hash(stored_hash):
        return legacy_sha256_hash(api_key) == stored_hash

    try:
        return bcrypt.checkpw(api_key.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


def is_valid_api_key_format(api_key: str) -> bool:
    """Basic format check before hitting the database."""
    return api_key.startswith(API_KEY_PREFIX) and len(api_key) > len(API_KEY_PREFIX) + 8
