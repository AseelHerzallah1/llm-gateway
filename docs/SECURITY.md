# Security — LLM Gateway v1

Audit and hardening notes for Phase 8.

---

## API key storage (Task 8.1)

### Before

- Gateway keys were stored as **SHA-256 hex digests**
- Lookup was a direct equality match on `projects.api_key_hash`
- SHA-256 is fast — if the database leaked, an attacker could brute-force guesses at high speed
- Acceptable only because keys are high-entropy (`secrets.token_urlsafe(32)`), but not ideal for a security audit story

### After

- New keys are stored as **bcrypt hashes** (12 rounds)
- A short **`api_key_lookup`** prefix (first 12 chars of the secret segment) enables indexed DB lookup
- Auth flow: lookup candidates by prefix → `bcrypt.checkpw()` on each match
- **Legacy SHA-256 rows** still work when `api_key_lookup` is `NULL` (migration path)

### Why bcrypt + prefix?

| Approach | Pros | Cons |
|----------|------|------|
| SHA-256 only | Fast indexed lookup | Fast offline cracking if DB leaks |
| bcrypt only | Slow to crack | Cannot index — must scan all rows |
| **bcrypt + lookup prefix** | Indexed lookup + slow hashes | Prefix is a hint (not the full secret) |

Gateway keys are random 256-bit secrets, so the prefix alone does not reveal the key. bcrypt protects the full key if the hash column leaks.

### Files

| File | Role |
|------|------|
| `app/auth/api_keys.py` | Generate, hash, verify |
| `app/auth/dependencies.py` | Auth resolution |
| `migrations/0004_add_api_key_lookup.py` | Adds `api_key_lookup` column |

### Migration for existing dev databases

```powershell
alembic upgrade head
```

Existing SHA-256 keys continue to work until you re-seed:

```powershell
# Delete test rows in PostgreSQL, then:
python scripts/seed_test_project.py
```

New seeds store bcrypt hashes + lookup prefix.

---

## Other security properties (already in place)

| Item | Status |
|------|--------|
| Plaintext API keys never stored | Yes — hash only |
| Admin passwords bcrypt-hashed | Yes — `users.password_hash` |
| Secrets in `.env`, not git | Yes — `.gitignore` |
| Provider keys server-side only | Yes — clients use `gw-sk-...` |

---

## Out of scope (v1)

- Rate limiting per project
- Key rotation API
- Argon2 (bcrypt is sufficient for portfolio v1)
- PII tokenization (Phase 9)
