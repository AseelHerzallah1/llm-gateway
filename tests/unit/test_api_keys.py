"""Unit tests for API key hashing and verification."""

from __future__ import annotations

import pytest

from app.auth.api_keys import (
    generate_api_key,
    hash_api_key,
    is_legacy_sha256_hash,
    is_valid_api_key_format,
    legacy_sha256_hash,
    prepare_stored_api_key,
    verify_api_key,
)


@pytest.mark.unit
def test_generate_api_key_format() -> None:
    api_key = generate_api_key()
    assert api_key.startswith("gw-sk-")
    assert is_valid_api_key_format(api_key)


@pytest.mark.unit
def test_bcrypt_hash_and_verify() -> None:
    api_key = generate_api_key()
    lookup, stored_hash = prepare_stored_api_key(api_key)

    assert len(lookup) == 12
    assert stored_hash.startswith("$2")
    assert verify_api_key(api_key, stored_hash)
    assert not verify_api_key(api_key + "x", stored_hash)


@pytest.mark.unit
def test_legacy_sha256_verify() -> None:
    api_key = generate_api_key()
    legacy = legacy_sha256_hash(api_key)

    assert is_legacy_sha256_hash(legacy)
    assert verify_api_key(api_key, legacy)
    assert not verify_api_key("gw-sk-wrong-key", legacy)


@pytest.mark.unit
def test_invalid_api_key_format() -> None:
    assert not is_valid_api_key_format("")
    assert not is_valid_api_key_format("sk-openai-key")
    assert not is_valid_api_key_format("gw-sk-short")
