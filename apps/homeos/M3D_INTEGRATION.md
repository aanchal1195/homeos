> **Unified-repository users:** Use [CONSOLIDATION.md](../../../CONSOLIDATION.md) and the **root** `compose.yaml`. The separate-checkout instructions below are retained only for users of the older standalone M2C ZIP. Do not apply both deployment approaches.

# M3D — Integrating the existing M2C HomeOS with Home Memory Graph

**Status: backend+UI integration candidate, not deployed to the user's running Docker containers.** The original standalone Next.js/FastAPI app remains intact, and M3D adds a graph projection, graph-backed JARVIS whereabouts lookup, and a Home Memory panel. Live PostgreSQL integration remains to be verified on a disposable copy before production use. The local SQLite backend suite passes.

## Architecture

- Original M2C property, floor/space, room, zone and asset records **remain authoritative**.
- `memory_legacy_links` maps each existing record to a stable graph entity UUID; repeated owner syncs update linked graph projections, do not duplicate objects and do not delete operational records.
- Confirmed `PART_OF` and `LOCATED_IN` edges carry a SYSTEM source reference; asset movement closes the previous edge and creates a new evidence-linked assertion/event. Vision observations **never** auto-update verified facts.
- JARVIS whereabouts queries use the household-scoped memory graph for owners. They distinguish unknown/unregistered assets from confirmed locations. Existing deterministic staff/task authorization and chat behavior are preserved.
- `POST /api/memory/sync` and `GET /api/memory/overview` are demo **owner-only** endpoints, proxied through the existing Next.js `/api/*` rewrites. The browser never receives the memory worker/API tokens.
- The independent GitHub M3A–M3C memory service can run alongside the M2C API on the **same** PostgreSQL database; unlike an isolated service DB, this lets its visualization and M3D projection refer to the same graph facts.

## Safety before installation

1. **Do not run `docker compose down -v`.** Preserve the running Postgres, Redis and uploads volumes. This project keeps the `name: homeos` Compose project name.
2. Store a PostgreSQL backup outside the containers. The script below creates `backups/homeos-before-m3d-*.dump` before applying graph SQL.
3. Use a separate test copy of the database for first migration/validation. No migration or Docker action has been executed on your Mac by ChatGPT.
4. This is still an insecure local demo identity scheme (`X-Member-Id`). Do **not** expose HomeOS to the public internet, share staff links or connect real household cameras until authentication is upgraded.

## Installation from the current ZIP and GitHub

You need the merged memory service checked out locally (GitHub `aanchal1195/homeos`). Assuming the extracted M2C application is in the current directory:

```bash
# Example: clone alongside the M2C folder. Skip if you have a recent clone.
git clone https://github.com/aanchal1195/homeos.git ../homeos-github

# In the existing M2C .env, set the cloned service path (absolute path also works):
HOMEOS_MEMORY_SOURCE_PATH=../homeos-github/services/memory
HOMEOS_MEMORY_ENABLED=false
# Set HOMEOS_HOUSEHOLD_ID to the UUID returned by /api/setup-state under the owner demo identity.
# Generate independent HOMEOS_API_TOKEN and HOMEOS_WORKER_TOKEN secrets.
```

First, **back up and apply additive graph migrations** (use a test database first). The original API Alembic migration `0004_memory_links.py` executes when its container is rebuilt. The memory tables are installed by:

```bash
./scripts/install-memory-schema.sh ../homeos-github/services/memory
```

Next enable projection by setting `HOMEOS_MEMORY_ENABLED=true` in your `.env` and rebuild the original API and Web containers **without deleting volumes**:

```bash
docker compose -f compose.yaml -f compose.m3d.yaml up -d --build api web
```

In the HomeOS owner UI, select **Sync virtual house** under Home Memory. Inspect the resulting floor, room and asset counts; repeat Sync and verify that new entity count is zero. Then ask JARVIS `Where is the refrigerator?` / `Fridge kahan hai?`. If no fridge is registered, JARVIS must explicitly say so.

The separate memory service is optional for the initial projection and lookup; start it later with:

```bash
docker compose -f compose.yaml -f compose.m3d.yaml --profile memory up -d --build memory
```

Visit `http://localhost:8001/docs` to use visual ingestion and inspection APIs (with its server-side bearer token). The Next.js M3D panel currently covers graph browsing and synchronization; **photo/video inspection UI, observation reconciliation and durable workflow orchestration are follow-up work**.

## Known limitations and follow-ups

- The initial bridge is a manual owner-controlled projection; it does not automatically refresh on each M2C edit. Resync after adding/moving assets.
- Current HomeOS dashboard remains a local demo with no production sessions/RBAC; graph writes must be owner-only.
- Graph schema `001`–`004` must be installed and the env flag enabled before querying memory. Bad/missing migrations will cause PostgreSQL errors, not silent fallback.
- The current integration has not been exercised against the user's PostgreSQL dataset; validate first on a restored copy.
- A real photo/video-to-verification-to-graph-update UI requires M3D follow-up PRs.
