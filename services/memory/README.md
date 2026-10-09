# HomeOS — M3A Home Memory Graph Foundation

This is a **standalone first increment** in `aanchal1195/homeos`. The earlier running HomeOS dashboard/M2C code exists only in local ZIP builds and is **not part of this GitHub repository**. Do not overwrite your running local HomeOS application with this service.

## What works

- Tenant-isolated entity registry, canonical names and aliases.
- Typed relations (`PART_OF`, `LOCATED_IN`, etc.), traversal and current-location resolution.
- Evidence-backed location updates with temporal assertions, supersession, audit events and idempotency keys.
- Read-only query endpoint for simple room counts and location lookup.
- Observation ingestion/review: photo/video observations stay non-authoritative even when accepted.
- Integration tests backed by PostgreSQL (run in GitHub Actions).

## Local development (separate service)

Generate your own secrets; do not commit `.env`:

```bash
cd services/memory
python3 -c 'import uuid; print(uuid.uuid4())'   # use as HOMEOS_HOUSEHOLD_ID
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'  # token
cat > .env <<'EOF'
POSTGRES_PASSWORD=replace_me_with_a_secure_local_password
HOMEOS_API_TOKEN=replace_me_with_a_random_token
HOMEOS_HOUSEHOLD_ID=replace_me_with_a_uuid
EOF
docker compose --env-file .env up --build -d
curl http://127.0.0.1:8001/health
```

The schema file in `schema/` is applied only when the database volume is **first initialized**. For existing PostgreSQL databases, run the SQL migration using a reviewed backup and a migration process; do not destroy database volumes.

All `/api/v1/memory/*` endpoints require `Authorization: Bearer <HOMEOS_API_TOKEN>`. Open `http://localhost:8001/docs` for API contracts.

Example:
```bash
curl -H "Authorization: Bearer $HOMEOS_API_TOKEN" \
  'http://localhost:8001/api/v1/memory/entities/search?q=fridge'
```

## Architectural limitations (explicit)

- This is an owner-only, single-household **bootstrap token**. Production OIDC authentication, per-user ACLs, and graph-level policy enforcement remain prerequisites for staff access and public deployment.
- Query endpoint is deterministic and supports only limited read-only intents. It is not a general LLM planner and must not execute arbitrary SQL.
- No existing HomeOS database backfill yet; migrate only after the local schema is inspected.
- No video/photo model, file upload, embeddings, inventory ledger, autonomous execution, or 3D map yet.
- Graph edge ontology validation and containment uniqueness require further hardening before arbitrary agent writes. Trust the owner API token only.
- Avoid reusing the local API token for other services.

## M3B interface

Visual processing should create `memory_evidence` and `memory_observations`, recording frame timestamps, media references, model metadata, and confidence. An observation is a proposal: accepting it **does not** automatically change the authoritative graph. Apply verified changes through an explicitly authorized domain workflow.

## Test

```bash
pip install -r requirements.txt
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema/001_home_memory.sql
pytest -q tests
```

Use a dedicated test database. The integration tests create persistent uniquely named test entities.

## Optional staged analysis worker

`M3C-staged-worker.md` documents the complementary queued worker workflow. Set a `HOMEOS_WORKER_TOKEN` different from `HOMEOS_API_TOKEN` before calling its endpoints; when unset, the worker endpoints reject requests. Apply `schema/004_staged_visual_worker.sql` after schema 003 on existing databases (back up first).
