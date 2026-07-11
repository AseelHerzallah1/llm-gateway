# Database migrations (Alembic)

Apply migrations after PostgreSQL is running:

```powershell
# Start database
docker compose up db -d

# Apply all pending migrations
alembic upgrade head

# Check current migration version
alembic current

# Roll back one migration (if needed)
alembic downgrade -1
```

## Tables in migration `0001`

| Table | Purpose |
|-------|---------|
| `users` | Admin accounts (email + password hash) |
| `projects` | Client projects with API key hash |

`requests` and `cache_entries` tables are added in later phases.
