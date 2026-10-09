# M3D — Unified HomeOS repository

The original M2C HomeOS Next.js/FastAPI source is now tracked in `apps/homeos/`. The M3A–M3C memory service remains in `services/memory/`. Root `compose.yaml` consolidates both into the same **existing** Docker Compose project, `homeos`.

## Non-negotiable safeguards

- This commit **does not modify** the Docker containers running on your Mac, your database, or any Docker volumes.
- The root Compose file deliberately preserves project name `homeos`, service names `db`, `redis`, `api`, `web`, and named volumes `pgdata`, `redisdata`, `uploads` as used in the M2C ZIP. The new `memory_media` volume holds private image/video evidence.
- Do **not** use `docker compose down -v` or remove/recreate `pgdata`.
- The user-facing authentication uses an insecure demo `X-Member-Id` header. Do not expose the system or private media externally.
- Always test an actual PostgreSQL restore in a disposable environment before upgrading the existing database.

## Suggested migration sequence (manual; NOT performed by ChatGPT)

1. Inspect the current Docker project, volumes and password. From your existing HomeOS folder, run `docker compose ps` and `docker volume ls` to confirm the project is named `homeos`.
2. Take a **verified** PostgreSQL backup while the original project is still running. `scripts/backup-homeos-db.sh` provides a compatible command when the new root Compose is configured. Do not treat non-empty dump bytes as proof of a successful restore.
3. Clone/pull this unified GitHub repository in a separate folder. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` to the **current** database password, not a new one. Leave `HOMEOS_MEMORY_ENABLED=false` initially.
4. Restore a copy of the backup to a **separate test database** and run Alembic `0004` and memory migrations `001` through `004` there. Validate virtual-house entity counts and household UUID. No user data is copied to GitHub.
5. Only after the restored-copy test passes, update the original `homeos` deployment in place. The root Compose reuses the named volumes. Starting the API automatically executes `alembic upgrade head` — do not run it against live data without backup and preflight checks.
6. Apply the memory migrations with the included `scripts/install-memory-schema.sh` (requires `HOMEOS_ACK_BACKUP=yes`), or use your standard reviewed migration process.
7. Set `HOMEOS_MEMORY_ENABLED=true` and rebuild the API/web services. Use the **existing owner identity** to select `Sync virtual house` under Home Memory; repeat and verify it creates zero duplicate entities.
8. Ask JARVIS a registered-location question and verify graph provenance. A missing refrigerator must return “not registered” rather than a generic assumed kitchen location.
9. Optionally configure owner/worker tokens and the existing household UUID to run `docker compose --profile memory up -d --build memory`. Configure vision API keys only after explicit privacy consent.

## Existing M2C migration fix

The original M2C `0001_initial.py` used `Base.metadata.create_all()` from the latest models, which caused duplicate-column failures in `0002` on a fresh database. The checked-in revision now creates the historical MVP schema explicitly, and the SQLite auto-create hook can be disabled for Alembic migration tests with `HOMEOS_AUTO_CREATE_SQLITE=false`. Migration `0003` uses batch operations to support clean SQLite tests. Existing records are not deleted; these historical revisions are unchanged in already migrated databases.

## What is not validated yet

- End-to-end behavior against **your running** PostgreSQL data, Docker versions, and browser.
- Live vision-provider calls with real household photographs.
- Automatic visual-observation reconciliation into verified graph facts.
- Production authentication, staff/device permissions, and autonomous workflows.
