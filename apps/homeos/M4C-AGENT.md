# M4C — Tool-using conversational JARVIS

## This is a reasoning runtime, not the old intent classifier

`apps/homeos/app/agent_runtime.py` implements a genuine multi-turn Chat Completions **tool-calling loop**. Each model step may choose a registered function, inspect the real structured result, select additional functions, ask the owner a clarification question or write a grounded natural English/Hindi/Hinglish response. The model **does not** compose SQL or call arbitrary endpoints. All tools run in the current FastAPI request against the current household/member. The original deterministic JARVIS remains available, with its actual mode displayed as **Deterministic fallback**.

`agent_tools.py` supplies exactly these functions:

| Tool | Source | Write permission |
|---|---|---|
| find_entities | Household-scoped rooms, assets, staff names | None |
| get_room | Registered room/floor/zone/assets | None |
| get_asset | Operational asset status, next_service, confirmed graph location | None |
| get_asset_history | Confirmed/superseded assertions + provenance | None |
| get_room_tasks | Outstanding recorded tasks for a room | None |
| eligible_staff_for_room | Existing maid staff scope | None |
| read_plan | Existing Home Manager proposal and task state | None |
| propose_cleaning | **Existing Home Manager** planning service | Creates unassigned PROPOSED draft only |
| revise_cleaning | Existing Home Manager, reassesses scope | Revises an unconfirmed draft only |

A cleaning proposal requires successful `get_room`, `get_room_tasks` and `eligible_staff_for_room` results **from the same turn**, including the selected assignee in the eligible list. A revised draft requires `read_plan` and, for a new room, a fresh room/scope check. The owner must still click **Confirm & assign** in the existing Home Manager UI; no assignment tool is exposed to the model. Approval remains bound to deterministic household, member, and scope rules.

## Defaults and activation

**Disabled by default** to avoid transmitting private home conversation and selected registered facts to a third party:

```dotenv
HOMEOS_JARVIS_AGENT_ENABLED=false
HOMEOS_JARVIS_AGENT_API_KEY=
HOMEOS_JARVIS_AGENT_MODEL=gpt-4.1-mini
```

The older `HOMEOS_CHAT_EXTERNAL_ENABLED` option remains a separate **read-intent classifier**. It is *not* the M4C agent. For M4C, explicitly enable `HOMEOS_JARVIS_AGENT_ENABLED=true` in a **synthetic, restored test environment only** after reviewing provider privacy/retention and authorizing external processing; set a valid server-only `HOMEOS_JARVIS_AGENT_API_KEY` there. Never send credentials to the browser or commit them. If M4C is disabled, replies are marked `JARVIS_DETERMINISTIC_FALLBACK`. If enabled but the provider/key fails, JARVIS returns `JARVIS_AGENT_UNAVAILABLE` and does **not** trigger the legacy assignment-by-phrase route.

The user can inspect the **Tools and sources** disclosure under an agent answer. Server-side evidence traces live in `agent_runs` (additive Alembic revision **0006**), scoped by household, owner member and message; the trace endpoint is owner-only. Tool text, notes and chat history are explicitly untrusted. Citations like `[T2]` are accepted only when they correspond to successfully executed tool calls from that turn. **A valid citation alone does not cryptographically prove the model's interpretation is correct.** Staff calendar availability, live object presence, actual physical inventory quantities, and any unrecorded facts remain UNKNOWN.

Limits: **9 model rounds**, **8 total tool calls**, up to **3 calls per assistant batch**, a **28-second total** deadline, **7,500 reported tokens** maximum, **650 reply tokens** per model call, bounded history (six prior message pairs), tool-output size caps, and graceful provider errors. A returned proposal may persist even if a later provider call fails; the error explicitly asks the owner to inspect Home Manager. Separate privacy reviews are required for family chats. HomeOS still has **spoofable `X-Member-Id` demo authentication**; do not expose this beyond localhost or connect sensitive home cameras/media.

## Evidence, and what is NOT evidence

`scripts/verify-reasoning-agent-ci.py` uses a **SCRIPTED model** that emits authentic OpenAI-style tool-call structures. The FastAPI routes, typed tool dispatch, authorization, real PostgreSQL household records, Home Memory Graph, Home Manager mutations, existing owner visual review, history, and audit traces are real in an isolated CI database. Tests exercise:

1. “Prepare Guest Bedroom for guests” → search room → get room assets → outstanding task → scope-qualified maid → PROPOSED draft; guest preferences and staff schedule remain unknown.
2. “Actually use Kitchen instead” → read existing plan → inspect new room/scope → revise same unconfirmed plan; no task is created until separate explicit owner confirmation; duplicate confirmation does not create a second task.
3. Electric-kettle location and history → a new **synthetic** owner-approved visual observation changes its graph location → next model turn re-fetches and reports updated location/evidence rather than stale chat.
4. Duplicate fan names → clarification; unregistered toaster and untracked towel quantities → no fabricated answers; staff denied owner-only tools and traces.
5. Forged write tool on a read question → denied; provider outage → explicit unavailable response and **no legacy task assignment**.
6. Additive migration 0006, existing backend suite, frontend production build, and Compose validation.

**Not yet exercised:** A real provider making tool choices or generating replies; OpenAI vision recognizing actual household photographs (existing photo tests use scripted detections); browser click-through; deployment or restored-backup migration on the user's Mac. Even with a valid credential, real-provider evaluation must start with a fully synthetic household after explicit authorization. Do **not** apply this branch to the running household or delete Docker volumes. The UI's successful production build is not browser validation.

## Next after review

First merge reviewed PR; rehearse migrations 0001–0006 on a restored database copy and run actual synthetic provider conversations/browser flows after authorization. Before sensitive or staff-facing multi-user access, implement real authentication, CSRF protection, least-privilege identity and consent retention. Later improvements: typed entity references between agent turns, richer inventory quantity ledger, robust plan idempotency under concurrent sessions, durable async video analysis, proactive staff follow-ups and cross-service evaluations.
