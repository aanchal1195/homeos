# M3D — Integrating the existing M2C virtual house

The previous M2C HomeOS application (JARVIS, virtual house, tasks and staff) is a **separate local Docker application**. Its source was supplied in a conversation ZIP; it is **not yet committed to this GitHub repository**. This PR adds the graph-side import endpoint so its existing digital twin can be reflected in Home Memory without replacing operational tables.

## Integration model

M2C's existing PostgreSQL tables `properties`, `floors`, `rooms`, `zones`, and `assets` are **authoritative**. They must be present in the **same PostgreSQL database** as the memory tables from migrations 001–004. The M2C app must apply its additive Alembic revision `0004_memory_links` to create a stable map between legacy string IDs and graph UUIDs.

Importing is explicit and owner-token guarded:

```bash
curl -X POST http://127.0.0.1:8001/api/v1/memory/import/m2c \
  -H "Authorization: Bearer $HOMEOS_API_TOKEN"
```

The memory service's `HOMEOS_HOUSEHOLD_ID` **must equal** the existing M2C household UUID. An absent or mismatched household produces an explicit error.

### What the import changes

- Creates mapped `HOME`, `FLOOR`/`SPACE`, `ROOM`, `ZONE`, and `ASSET` entities.
- Stores stable `memory_legacy_links` references, avoiding duplicates on repeated imports.
- Projects spatial relationships (`PART_OF`, `LOCATED_IN`) with SYSTEM provenance.
- Adds historical location events when the operational source moves an item.
- If an independently verified owner location conflicts with the legacy record, **does not overwrite it**; proposes a pending observation instead.
- Never imports staff secrets or asserts that unseen objects are absent; it never deletes legacy rows.

### Important boundaries

The repo currently provides a FastAPI memory service, not the running M2C UI. The companion M2C integration package (prepared separately) adds an owner-only Home Memory panel and graph-backed JARVIS whereabouts queries. Do not merge or deploy an application package without checking its contents and keeping the existing database volumes.

This is a local single-household bearer-token prototype and **not** production OIDC/RBAC. Do not expose the import endpoint publicly. Existing PostgreSQL backups must be taken before applying any migrations. Do **not** delete database volumes.

### Validation

CI uses a temporary PostgreSQL instance and builds a minimal M2C fixture to exercise initial projection, repeat-import idempotency, owner-location conflict detection, and household auth. It does not operate on your Mac or live household database.
