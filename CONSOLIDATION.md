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
4. Restore a copy of the backup to a **separate test database** and run Alembic `0004` and memory migrations `001` through `005` there. Validate virtual-house entity counts and household UUID. No user data is copied to GitHub.
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
- Owner-reviewed visual reconciliation is implemented but not yet validated against your running household database or real media volume.
- Production authentication, staff/device permissions, and autonomous workflows.

## M3E owner visual review deployment

The owner-only **Visual review** panel is visible in HomeOS after visual analysis creates evidence-backed PENDING observations. The API reads media from the `memory_media` volume mounted **read-only** and requires a local owner identity. Approval of a new asset or its location updates the original `assets` table and the graph in one database transaction, while preserving evidence, review records, and history. A rejection or `VERIFY_ONLY` review cannot mutate operational assets. The owner must explicitly enter the verified asset name and choose a mapped location; the model's label is not automatically trusted.

Migration `005_visual_review.sql` is **additive**. Apply it only after backing up the current database and validating a restored copy. Enable `HOMEOS_MEMORY_ENABLED=true` only after all the memory migrations have been applied. The private evidence preview requires the `memory_media` volume; it is not a public download endpoint.

**Security warning:** The existing `X-Member-Id` demo identity is not production authentication. Even though review handlers check `owner` role, a caller can impersonate that identity if the service is exposed. **Do not expose HomeOS externally or use real sensitive household recordings until production authentication and consent controls exist.**

## M3F — Owner photo inspection from the HomeOS UI

The owner can now use **Inspect a room** on the JARVIS operational dashboard. Pick a synchronized room/area and upload a JPEG/PNG/WebP photo (max 15 MiB). The upload is sent to the local FastAPI gateway and held in the private `memory_media` volume. **Uploading does not invoke an AI provider.** The owner must separately opt in with the consent checkbox and click **Analyze with AI** before a photo or its transformed version is sent to the configured OpenAI vision provider. The model's findings remain **PENDING** until reviewed in the existing Visual review panel.

Before testing in a **restored database** (not your live database):
1. Apply M2C migrations and Home Memory SQL migrations 001–005. Synchronize the house hierarchy in Home Memory before selecting a location.
2. Set `HOMEOS_MEMORY_ENABLED=true`, `HOMEOS_HOUSEHOLD_ID` to the **existing** household UUID, and a long, non-empty `HOMEOS_API_TOKEN` in your local `.env`.
3. Start the private memory service with the `memory` Compose profile in addition to the HomeOS API/web containers. The API connects to `http://memory:8001` over the Compose network, forwarding `HOMEOS_API_TOKEN` through its server-only `HOMEOS_MEMORY_SERVICE_TOKEN` environment setting; **do not expose this token to the Next.js app**.
4. Upload a non-sensitive test image. Check that HomeOS says **privately uploaded, not sent to AI**.
5. Only after explicitly approving external disclosure, configure `HOMEOS_VISION_API_KEY`, check the provider's data-handling terms, and test **Analyze with AI**. Inspect proposed objects in **Visual review** and approve a correction to update the graph.

The upload/analysis API currently uses synchronous requests. A provider timeout may require a later retry of the same saved session/media; do not re-upload blindly. Invalid media, interrupted uploads and orphaned sessions need future cleanup and quotas. This release is **not** production-safe for sensitive household media: `X-Member-Id` remains an insecure, spoofable demo identity. Keep services bound to localhost and do not expose to the internet or other users until real owner authentication, CSRF protections, quotas and consent retention are implemented.

This code and CI have **not** changed your running Mac containers or database.
