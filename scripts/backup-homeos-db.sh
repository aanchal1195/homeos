#!/usr/bin/env bash
set -euo pipefail
# From repository root. Uses existing Compose project 'homeos'.
# Never remove pgdata/redisdata/uploads; no destructive action is executed.
cd "$(dirname "$0")/.."
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="backups/homeos-${stamp}.dump"
if [[ -e "$backup" ]]; then echo "Backup already exists: $backup" >&2; exit 2; fi
printf 'Creating PostgreSQL backup: %s\n' "$backup"
docker compose exec -T db pg_dump -U homeos -d homeos -Fc > "$backup" || { rm -f "$backup"; exit 3; }
if [[ ! -s "$backup" ]]; then echo "Backup empty, aborting" >&2; rm -f "$backup"; exit 4; fi
printf 'Verify with: pg_restore --list %s\n' "$backup"
