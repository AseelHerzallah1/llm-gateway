"""Offline tests for API key hashing and verification."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.api_keys import (
    generate_api_key,
    hash_api_key,
    is_legacy_sha256_hash,
    legacy_sha256_hash,
    prepare_stored_api_key,
    verify_api_key,
)


def main() -> None:
    api_key = generate_api_key()
    lookup, stored_hash = prepare_stored_api_key(api_key)

    assert lookup
    assert len(lookup) == 12
    assert stored_hash.startswith("$2")
    assert verify_api_key(api_key, stored_hash)
    assert not verify_api_key(api_key + "x", stored_hash)

    legacy = legacy_sha256_hash(api_key)
    assert is_legacy_sha256_hash(legacy)
    assert verify_api_key(api_key, legacy)
    assert not verify_api_key("gw-sk-wrong-key", legacy)

    wrong_bcrypt = hash_api_key(generate_api_key())
    assert is_legacy_sha256_hash(legacy)
    assert not is_legacy_sha256_hash(wrong_bcrypt)

    print("API key hashing OK")
    print("Lookup prefix length:", len(lookup))
    print("Bcrypt hash prefix:", stored_hash[:7])


if __name__ == "__main__":
    main()
