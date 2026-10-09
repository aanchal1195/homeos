# HomeOS — Home Memory Service

Standalone HomeOS memory and visual-evidence service. The earlier local dashboard remains separate.

## Current capabilities

- Tenant-isolated entity registry, aliases and typed graph relations.
- Evidence-backed location history with supersession and idempotency.
- Private bounded image/video ingestion and guided inspection coverage.
- M3C staged visual-analysis jobs with bounded image/video frame preparation.
- Separate owner and worker tokens.
- Structured findings become **PENDING observations**; they do not directly change confirmed graph assertions.
- PostgreSQL-backed integration tests in GitHub Actions.

See `M3B.md` and `M3C.md` for the visual pipeline contracts and limitations.

## Local development

Generate three values and keep them out of Git:

```bash
cd services/memory
python3 -c 'import uuid; print(uuid.uuid4())'
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Create `.env`:

```text
POSTGRES_PASSWORD=replace_me
HOMEOS_API_TOKEN=replace_owner_token
HOMEOS_WORKER_TOKEN=replace_worker_token
HOMEOS_HOUSEHOLD_ID=replace_with_uuid
```

Start:

```bash
docker compose --env-file .env up --build -d
curl http://127.0.0.1:8001/health
```

For an **existing database**, apply SQL migrations in order using a reviewed backup and migration process. Do not delete database volumes as a migration strategy.

## Security limitations

This still uses bootstrap bearer tokens, not production OIDC/RBAC. Real household media should not be exposed publicly. Before deployment add user-scoped identity, consent/retention policy, malware scanning, rate limits, audit-authorized media access and key rotation.

The worker token must be different from the owner token. Visual findings are untrusted proposals even when supplied by a model and require downstream review/authorization before tasks, repairs, purchases or graph mutations.

## Tests

CI applies:
- `001_home_memory.sql`
- `002_visual_memory.sql`
- `003_visual_analysis.sql`

and runs the PostgreSQL integration suite.
