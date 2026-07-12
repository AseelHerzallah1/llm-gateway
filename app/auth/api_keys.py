"""API key generation and hashing."""

import hashlib
import secrets


API_KEY_PREFIX = "gw-sk-"


def generate_api_key() -> str:
    """Create a new project API key. Show to the user once — only the hash is stored."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """SHA-256 hex digest for database lookup (documented in docs/API.md)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def is_valid_api_key_format(api_key: str) -> bool:
    """Basic format check before hitting the database."""
    return api_key.startswith(API_KEY_PREFIX) and len(api_key) > len(API_KEY_PREFIX) + 8
