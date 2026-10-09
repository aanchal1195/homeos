# M5 — Adaptive Visual Home Discovery

## Product behavior

The HomeOS Setup Wizard now starts with **JARVIS · Guided home discovery**,
before the existing manual steps. It accepts floor-plan photos (optional),
room photographs and short room walkthrough videos **before the property,
floor or room hierarchy has been created**. Owners can tag a claimed floor/room
or associate evidence with an existing room, and continue collecting more
evidence over multiple visits.

JARVIS tracks private uploads, room coverage and unresolved findings. It
recommends one next action: request a floor-plan photo, analyze unprocessed
evidence, clarify floor/room names, review outstanding suggestions, capture a
room, capture a second angle, or review setup before launching. The **local
coverage policy** functions without any external provider. The separate
AI-guided planner (enabled only by user consent per request) may choose among
bounded next-step actions by examining household configuration, coverage and
pending decisions. It does not perform owner approvals. This is an adaptive
planner, **not an unrestricted autonomous home-mapping agent**.

### Media and analysis

- JPEG/PNG/WebP floor plans and room photos: **15 MiB max**, encoding verified
  with Pillow, maximum 40 million pixels.
- MP4/MOV/WebM walkthroughs: **35 MiB max**, **90 seconds max**, ffprobe
  validation and at most three downscaled ffmpeg frames sent to the provider.
- Media is streamed to a private file under the existing **uploads** volume,
  with UUID-only storage paths and owner-only, uncached preview endpoints.
- **Upload never invokes an AI provider.** Each analysis requires a separate
  affirmative disclosure checkbox, opt-in `HOMEOS_GUIDED_SETUP_AI_ENABLED`,
  and server-side `HOMEOS_GUIDED_SETUP_API_KEY`. The standalone planner's
  separate consent sends only room names and coverage metadata.
- Provider labels are untrusted. The bounded JSON response yields only
  `FLOOR`, `ROOM`, or `ASSET` proposals, unresolved questions, and a next
  photo suggestion. Videos do not supply a fabricated floor plan. No faces,
  hidden objects, unknown quantities, dimensions or room connections may be
  claimed as verified.
- Every proposal requires explicit owner acceptance or rejection. Accept
  creates/reuses a room/floor/asset in the existing operational tables;
  rejecting it changes **no authoritative household fact**. Applying a room
  requires an approved floor. Applying an asset requires an approved room.
  A same-named asset already recorded in another room blocks duplicate
  registration and requires clarification or an approved relocation.
- An accepted asset's location is projected to the Home Memory Graph inside
  the same transaction when Home Memory is enabled, with an **OWNER** evidence
  assertion linked to the original private media. If Home Memory is enabled
  later, explicit `Sync virtual house` backfills these owner-review records,
  idempotently, only while the asset remains in the approved room; it does not
  revive stale locations.

### Important limitations

- A photographed plan can contain incorrect or illegible labels. The model
  must surface uncertainty; the owner confirms actual floor/room names.
- A walkthrough is a sample of visible frames, not complete continuous
  scene understanding, tracking of people or a reliable room-topology graph.
- Physical quantities are unknown without owner counts or a dedicated
  quantity ledger; a photo cannot prove inventory completeness.
- The app does **not** autonomously register objects, move assets, assign staff
  or close setup. The owner approves each proposed fact.
- No live image/video provider invocation has been run here. CI uses a
  scripted vision result over synthetic media. Browser interaction on the
  user's Mac and any restored household database remain **unverified**.
- Local identity uses spoofable `X-Member-Id`; keep the app bound to
  localhost, avoid sensitive household recordings, and introduce actual
  authentication/CSRF controls before genuine multi-user deployment.

## Synthetic sandbox testing

When this code has been merged, refresh the source used by the
`homeos-sandbox` project (do **not** update your original `homeos` project).
Since some Macs do not have Git installed, a ZIP of GitHub `main` is fine.
Preserve the private `.env.smoke` only in the sandbox directory; never
publish it.

To activate private uploading and local guidance, no external model is needed.
Rebuild the **sandbox API and web** from the updated source:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --build api web
```

Open **http://127.0.0.1:3300** and initialize a synthetic household. The
Guided home discovery panel appears above manual setup. Upload one fake
floor-plan photo or room image/video; verify `UPLOADED` status and that no
provider is contacted. Local **Decide the next useful step** should request
analysis or further coverage without requiring a key.

For an authorized **synthetic** remote AI evaluation, explicitly consent to
sending test image/video frames and selected room metadata, then set:

```dotenv
HOMEOS_GUIDED_SETUP_AI_ENABLED=true
HOMEOS_GUIDED_SETUP_API_KEY=<server-only API key>
HOMEOS_GUIDED_SETUP_MODEL=gpt-4.1-mini
```

Recreate only the sandbox API container. Confirm detections appear as
`PENDING`, reject at least one false detection, edit/approve one label and
check the virtual house. After the property, floor and room are confirmed,
you may finish setup using the existing **Launch JARVIS** button. For memory
retrieval after the owner's approvals, activate Home Memory separately, apply
its SQL migrations to the **sandbox database only**, then run **Sync virtual
house**.

**Do not** apply Alembic 0007 or run the new API against the current real
household database without a verified restored-copy migration rehearsal.
Never run `docker compose down -v`. There is no requirement to move the
current live Docker volumes into the sandbox.

## Verified CI evidence

- Backend SQLite regressions: upload authorization and MIME checking,
  floor-plan schema proposal, explicit analysis consent, corrected room/floor
  acceptance, owner rejection, no duplicate decisions, bounded next-step
  recommendation, and **real ffmpeg MP4 frame decoding**.
- Disposable PostgreSQL application + Memory Graph integration:
  private upload, scripted proposals, explicit owner review, rejected false
  positive remaining unregistered, owner evidence-backed location assertion,
  existing grounded JARVIS retrieval, late memory activation and repeated
  synchronization without duplicate owner assertions.
- Frontend production compilation and Docker Compose isolation checks.

**Not verified:** Actual AI recognition, provider planner quality, browser
click-through, Mac local rebuild, actual household migrations, production
authentication, or unattended background video processing.
