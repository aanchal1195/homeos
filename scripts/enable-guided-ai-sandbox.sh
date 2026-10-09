#!/usr/bin/env bash
# Enable external guided image/video analysis ONLY for the isolated sandbox.
# This script never reads or changes the original "homeos" Docker project.
# The key is read from an interactive terminal without echo or shell history.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f ".env.smoke" ]]; then
  echo "Missing .env.smoke. Copy .env.smoke.example and set a sandbox-only POSTGRES_PASSWORD first." >&2
  exit 2
fi
if ! docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml config |
  grep -qx "name: homeos-sandbox"; then
  echo "REFUSING: This must target the isolated homeos-sandbox Compose project." >&2
  exit 3
fi
if [[ ! -t 0 ]]; then
  echo "Run this from your own Mac Terminal to enter the key privately." >&2
  exit 4
fi
printf 'This sends selected household images or video frames to OpenAI ONLY after your per-file consent.\n'
printf 'Use synthetic images first. Do not share your key in chat.\n'
IFS= read -r -s -p 'Paste your OpenAI Platform API key (input hidden): ' key
printf '\n'
if [[ ${#key} -lt 12 || "$key" == *[[:space:]]* ]]; then
  echo "No valid-looking API key supplied; sandbox config unchanged." >&2
  exit 5
fi
umask 077
tmp="$(mktemp ./.env.smoke.tmp.XXXXXXXX)"
trap 'rm -f "$tmp"; unset key' EXIT
awk '!/^HOMEOS_GUIDED_SETUP_(AI_ENABLED|API_KEY)=/' .env.smoke > "$tmp"
printf '\nHOMEOS_GUIDED_SETUP_AI_ENABLED=true\nHOMEOS_GUIDED_SETUP_API_KEY=%s\n' "$key" >> "$tmp"
chmod 600 "$tmp"
mv "$tmp" .env.smoke
unset key
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml config --quiet
docker compose --env-file .env.smoke -f compose.yaml -f compose.smoke.yaml up -d --force-recreate api
echo "Only homeos-sandbox API recreated. Guided AI is configured; upload still needs explicit per-file consent."
