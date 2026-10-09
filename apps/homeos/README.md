# M3D integration candidate

The original M2C application now includes an optional Home Memory integration. Before any Docker changes, read **[M3D_INTEGRATION.md](M3D_INTEGRATION.md)**. The original operational PostgreSQL tables and volumes must be preserved.

---

# HomeOS JARVIS — M2C Contextual JARVIS

This increment makes JARVIS context-aware and grounded in the configured HomeOS digital twin.

## What is new

- `HouseholdContextService`-style grounding assembled from the live database on every conversational turn.
- Context includes property, floors/spaces, rooms, zones, assets, staff, active tasks, open issues, viewer role, and recent conversation history.
- Grounded household Q&A such as:
  - `How many rooms do we have?`
  - `Kitne bathrooms hain?`
  - `What do we have on First Floor?`
  - `What assets are in Kitchen?`
  - `What is pending?`
  - `Any open issues?`
- Contextual follow-up support for recent household topics.
- No invention of rooms/assets that are not present in the digital twin.
- Existing deterministic authorization remains in place for task creation and other writes.
- New `GET /api/context` endpoint for inspecting the context available to JARVIS.
- Health mode/version updated to M2C / 0.4.0.

## Run locally

```bash
cp .env.example .env
docker compose down
docker compose up --build -d
docker compose ps
```

Do **not** use `docker compose down -v` unless you intentionally want to remove PostgreSQL data.

Open:

- HomeOS: http://localhost:3000
- FastAPI docs: http://localhost:8000/docs

## Tests

```bash
pytest -q
```

Current backend suite: **6 passed**.

## Important boundary

M2C uses database-grounded deterministic contextual logic. It does not yet connect a production LLM. The next increment can add an LLM response layer on top of this context assembler while keeping all state-changing actions behind deterministic authorization and tool execution.
