#!/usr/bin/env bash
set -euo pipefail
# Only the isolated homeos-sandbox Docker project is eligible.
# Never use this script to migrate the live "homeos" Compose project.
cd "$(dirname "$0")/.."
if [[ ! -f .env.smoke ]]; then
  echo "Missing .env.smoke. Copy .env.example and set a SANDBOX password first." >&2
  exit 2
fi
COMPOSE=(docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml)
PROJECT=$("${COMPOSE[@]}" config --format json | python3 -c   'import json,sys; print(json.load(sys.stdin)["name"])')
if [[ "$PROJECT" != "homeos-sandbox" ]]; then
  echo "Refusing to run: expected the isolated homeos-sandbox project." >&2
  exit 3
fi
for name in \
  001_home_memory.sql \
  002_visual_memory.sql \
  003_visual_analysis.sql \
  004_staged_visual_worker.sql \
  005_visual_review.sql \
  005_multimodal_worker.sql; do
  echo "Sandbox only: applying ${name}"
  "${COMPOSE[@]}" exec -T db psql -U homeos -d homeos -v ON_ERROR_STOP=1 \
    < "services/memory/schema/${name}"
done
echo "Done. Only homeos-sandbox database schema was updated."
