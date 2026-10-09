# Manual HomeOS testing on your Mac — without risking the running house

**You can test the current app locally with synthetic data.** The separate
`homeos-sandbox` Docker Compose project uses its own `pgdata`, `redisdata`,
`uploads` and `memory_media` volumes and binds the web/API/memory services to
`127.0.0.1:3300`, `127.0.0.1:8800` and `127.0.0.1:8801` respectively.
It does **not** reuse your running `homeos` volumes or ports 3000/8000/8001.

## 1. Build a fresh synthetic test stack

Requirements: Docker Desktop running, Docker Compose **v2.24+** (for the Compose
`!override` tag), Git, and Python 3 on your Mac.

```bash
docker compose version
git clone https://github.com/aanchal1195/homeos.git homeos-sandbox-source
cd homeos-sandbox-source
cp .env.example .env.smoke
```

Edit `.env.smoke` locally: set a **new disposable** `POSTGRES_PASSWORD`
(different from the live HomeOS password). Leave
`HOMEOS_MEMORY_ENABLED=false`, `HOMEOS_JARVIS_AGENT_ENABLED=false`,
`HOMEOS_CHAT_EXTERNAL_ENABLED=false`, and model API keys empty initially.
**Never** commit or paste the `.env.smoke` file or its secrets.

Validate the isolated project *before* starting it:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml config --quiet
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --build db redis api web
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml ps
```

Open **http://127.0.0.1:3300**. Create a *fake* household and add example rooms,
assets and staff scopes. Test the virtual house, tasks and deterministic JARVIS
first. The header still uses demo `X-Member-Id` identities, **not secure login**.

## 2. Enable genuine model-driven JARVIS (synthetic household only)

Only after you explicitly agree to transmit the synthetic chat prompts and
selected household tool results to the external model, set in **`.env.smoke`**:

```dotenv
HOMEOS_JARVIS_AGENT_ENABLED=true
HOMEOS_JARVIS_AGENT_API_KEY=<YOUR_OWN_SERVER_SIDE_OPENAI_API_KEY>
HOMEOS_JARVIS_AGENT_MODEL=gpt-4.1-mini
```

Replace the angle-bracket placeholder with a local API credential. ChatGPT Plus
is not an OpenAI API credential or API billing entitlement. Do not send keys in
ChatGPT or put them in Git. Then restart **only the sandbox API**:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --force-recreate api
```

Refresh **http://127.0.0.1:3300**; the banner should now say the agent is
**configured** (not guaranteed online). Ask open-ended, multi-tool questions:
“Help me prepare the Guest Bedroom for guests; what's already pending and
who can clean it?”; “What is the latest service status of the water purifier?
Where was its location last recorded and how do you know?”; “Actually change
that cleaning draft to the Kitchen.” The UI shows **Reasoning agent** or
**Agent unavailable** on each answer and exposes tool sources under the answer.
A proposed plan **must not** assign staff until the owner clicks **Confirm &
assign**. If the provider cannot respond, no autonomous assignment occurs.

Without the API key, you can still manually test UI and deterministic fallbacks,
but you **cannot** validate real LLM tool-selection quality.

## 3. Optional: Home Memory Graph and private photo upload (synthetic only)

Create the fake household in the UI first. Find the local owner member ID and
household UUID from the **sandbox API**:

```bash
OWNER_ID=$(curl -fsS http://127.0.0.1:8800/api/demo-members | python3 -c \
 'import json,sys; print(next(x["id"] for x in json.load(sys.stdin) if x["role"]=="owner"))')
HOUSE_ID=$(curl -fsS -H "X-Member-Id: $OWNER_ID" \
 http://127.0.0.1:8800/api/setup-state | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["household"]["id"])')
echo "Sandbox household UUID: $HOUSE_ID"
```

Set `HOMEOS_HOUSEHOLD_ID` to **that** UUID in `.env.smoke`, set a new nonempty
`HOMEOS_API_TOKEN`, and enable `HOMEOS_MEMORY_ENABLED=true` (leave
`HOMEOS_WORKER_TOKEN` empty unless testing the *separate staged* worker API).
Then apply only the **sandbox** memory migrations:

```bash
bash scripts/install-memory-schema-sandbox.sh
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml --profile memory up -d --build api memory web
```

Check **http://127.0.0.1:8801/health**. Under Home Memory, use **Sync virtual
house**, then select a registered room under **Inspect a room**. A private
JPEG/PNG/WebP upload does **not** invoke the external vision provider.
Only explicitly pressing **Analyze with AI** after consent can send the photo.
You will need `HOMEOS_VISION_API_KEY` for real recognition (test a non-sensitive
synthetic image first); the CI detections so far were scripted. The existing
Visual review panel handles corrected/rejected findings; approved assets should
then appear in the memory and agent tools.

The optional M3D multimodal **staged video worker** is an independent pipeline,
not the default photo-inspection UI. Its optional Compose overlay is
`services/memory/compose.vision.yaml`; do not activate it for basic UI testing.

## 4. Preserve the real deployment

A **fresh sandbox requires no backup of the live house because it never opens
the live volumes**. Testing the new code *against your actual household data* is
a separate operation: first capture and verify a PostgreSQL backup, restore it
to an isolated database, compare entity/task counts, rehearse Alembic 0001–0006
and memory SQL 001–005, and only then plan any upgrade to the running stack.

Never run `docker compose down -v`. Never use the root migration installer
(`scripts/install-memory-schema.sh`) for this sandbox because it intentionally
targets the **live** `homeos` project. The sandbox-only installer verifies the
project name first.

To stop test containers *without deleting volumes*:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml down
```

**Not yet verified on your Mac**: build performance, real-browser operation,
real LLM response accuracy, real-photo vision accuracy, or migration against
your household backup. You perform the manual test when ready; merging GitHub
PRs does not automatically update any running Docker application.
