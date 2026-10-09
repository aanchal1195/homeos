# HomeOS — JARVIS & Home Memory

HomeOS is a private, local-first household-management prototype with a digital house, JARVIS chat, operations tracking, and an evidence-backed memory graph.

## Monorepo structure

- [`apps/homeos/app/`](apps/homeos/app/) — original M2C FastAPI operational backend and JARVIS, including M3D memory bridge
- [`apps/homeos/apps/web/`](apps/homeos/apps/web/) — original Next.js HomeOS dashboard, virtual house and Home Memory panel
- [`apps/homeos/migrations/`](apps/homeos/migrations/) — versioned M2C Alembic migrations (0001–0004)
- [`services/memory/`](services/memory/) — M3A–M3C knowledge graph, visual media, analysis workers, and owner-controlled M2C import
- [`compose.yaml`](compose.yaml) — unified Docker configuration preserving the original `homeos` Compose project and volumes
- [`CONSOLIDATION.md`](CONSOLIDATION.md) — backup-first migration and deployment instructions

## Important before running

**This repository has NOT been deployed to your running Mac.** The code is tested in isolated CI databases. The existing containers, PostgreSQL data, named volumes, and household setup have not been modified by these GitHub changes.

If you already have HomeOS running, **read [CONSOLIDATION.md](CONSOLIDATION.md) first**. Do not run `docker compose down -v`, erase volumes, or swap PostgreSQL passwords. Test migration against a restored backup before applying it to live data.

The single-machine demo uses `X-Member-Id` for owner/staff selection, which is **not secure production authentication**. Keep ports loopback-only. Photo/video inference can disclose household media to a model provider and must be opt-in.

## Local development on a fresh, disposable environment

```bash
cp .env.example .env
# Edit .env: choose a secure POSTGRES_PASSWORD; leave memory disabled initially.
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build -d db redis api web
```

The original app is available at `http://localhost:3000`; FastAPI docs at `http://localhost:8000/docs`. The memory service can later be started with `--profile memory` after the graph tables are installed and the existing household UUID is configured.

## Validation

GitHub Actions runs the M2C SQLite API suite, fresh SQLite Alembic migration, Next.js production build, Compose volume/config checks, and a full PostgreSQL M2C-to-Memory Graph integration test. The separate memory workflow tests the graph API, observations, and visual analysis.

**Known gaps:** integration against your specific running data, secure OIDC/user roles, resilient production job orchestration, and approved observation-to-authoritative-state reconciliation.
