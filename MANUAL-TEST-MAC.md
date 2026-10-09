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
cp .env.smoke.example .env.smoke
```

Edit `.env.smoke` locally: replace the placeholder with a **new disposable** `POSTGRES_PASSWORD` (different from the live HomeOS password). Leave
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

## M5 — First guided floor-plan, photo and walkthrough test (new onboarding UI)

This feature is part of the **Setup Wizard**, before the manual Property and
Floors steps. It does not require you to turn on Home Memory merely to
upload evidence, and you may upload before registering any room. Images and
videos remain private until a separate explicit AI-analysis consent.

If you previously downloaded HomeOS as a GitHub ZIP because macOS Git/Xcode
tools were unavailable, do **not** delete your old sandbox data or `.env.smoke`.
After M5 is merged, you can refresh only the source:

```bash
cd ~
curl -fL https://github.com/aanchal1195/homeos/archive/refs/heads/main.zip -o homeos-latest.zip
unzip -q homeos-latest.zip
mv homeos-main homeos-sandbox-v5-source
cp ~/homeos-sandbox-source/.env.smoke ~/homeos-sandbox-v5-source/.env.smoke
cd ~/homeos-sandbox-v5-source
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml config --quiet
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --build api web
```

This reuses only the existing **homeos-sandbox** project and its test
volumes, not the original `homeos` project. Rebuilding includes ffmpeg to
validate short videos, and may use additional memory on Docker Desktop.
Open **http://localhost:3300** and check the guided setup panel above the
manual form.

To validate the form **without an API key**: choose `Floor plan photo`
(optional), `Room photographs` or `Room walkthrough video`; upload synthetic
media. The upload must show `UPLOADED` and an explicit `not sent to AI`
message. `Decide the next useful step` runs the local coverage policy.
AI analysis buttons must remain unavailable without a separate provider key.

To authorize a **synthetic test** of model-driven recognition and next-step
planning, read `apps/homeos/M5-VISUAL-ONBOARDING.md`, then set:

```dotenv
HOMEOS_GUIDED_SETUP_AI_ENABLED=true
HOMEOS_GUIDED_SETUP_API_KEY=<your own OpenAI API key>
HOMEOS_GUIDED_SETUP_MODEL=gpt-4.1-mini
```

Restart the sandbox API:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --force-recreate api
```

For each private image/video, explicitly tick consent and click **Analyze
this evidence with AI**; review, rename, reject or approve individual
suggestions. To let the separate planner choose the next question using
floor/room names and coverage metadata, explicitly tick its consent and click
**Decide the next useful step**. The model cannot auto-register or assign
work. Real provider calls and browser walkthroughs have **not** been
validated by ChatGPT; report incorrect detections and clear failures.

## iPhone native photo uploads and activating guided AI (sandbox only)

The guided setup upload now supports iPhone **HEIC/HEIF**, ordinary
**JPEG/PNG/WebP**, and MP4/MOV/WebM walkthroughs. It validates **decoded image
bytes** rather than trusting Safari's reported MIME or the filename. Thus
a genuine JPEG incorrectly reported as PNG, or HEIC reported as JPEG, is
accepted. Original files remain private and unchanged; HEIC previews are
converted to JPEG for browser compatibility. Each image must still be within
15 MiB / 40 million pixels. ProRAW DNG, animated Live Photo bundles and
arbitrary image/video formats are not supported; export DNG to JPEG first.

If you received an error saying “Image encoding does not match file type”
in your previous localhost:3300 app, the fix only arrives after rebuilding
the **sandbox API and web** from an updated source ZIP.

**Simplest secure option:** after downloading/rebuilding the updated source,
run `bash scripts/enable-guided-ai-sandbox.sh` from its root in your Mac
Terminal. The script verifies the Compose project is exactly
`homeos-sandbox`, silently prompts for your key without recording it in
Terminal history, sets the opt-in in your private `.env.smoke`, and
recreates **only the sandbox API**. It cannot be run on the real homeos
project.

Alternatively, edit the file manually as described below.

To turn on **guided AI** in your sandbox, use a valid OpenAI Platform API key
(this is separate from a ChatGPT subscription). Edit the private
`.env.smoke` on your Mac, without exposing the key in this chat:

```dotenv
HOMEOS_GUIDED_SETUP_AI_ENABLED=true
HOMEOS_GUIDED_SETUP_API_KEY=<paste your own key locally here>
HOMEOS_GUIDED_SETUP_MODEL=gpt-4.1-mini
```

After saving it, run `chmod 600 .env.smoke`, and apply changes to **only
the sandbox**:

```bash
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml config --quiet
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --build api web
```

Refresh http://localhost:3300. The guided panel should report the AI
provider as configured. **Uploading** an image still does not contact OpenAI.
The owner must separately tick the checkbox for each image and click
**Analyze this evidence with AI**; next-step reasoning has another consent
checkbox. Begin with a synthetic/non-sensitive image. No API key or Docker
configuration change is automatically applied by merging GitHub code.
