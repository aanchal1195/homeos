#!/usr/bin/env bash
# Existing Postgres database only. Additive memory tables; no Docker volume deletion.
set -euo pipefail
MEMORY_SOURCE="${1:-${HOMEOS_MEMORY_SOURCE_PATH:-../homeos-github/services/memory}}"
SCHEMA_DIR="$MEMORY_SOURCE/schema"
if [[ ! -f "$SCHEMA_DIR/001_home_memory.sql" ]]; then
  echo "Missing memory schema: $SCHEMA_DIR" >&2; exit 2
fi
mkdir -p backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="backups/homeos-before-m3d-$STAMP.dump"
echo "Backing up existing HomeOS database to $BACKUP"
docker compose -f compose.yaml -f compose.m3d.yaml exec -T db pg_dump -U homeos -d homeos -Fc > "$BACKUP"
if [[ ! -s "$BACKUP" ]]; then echo 'Backup empty: aborting' >&2; exit 3; fi
for filename in 001_home_memory.sql 002_visual_memory.sql 003_visual_analysis.sql 004_staged_visual_worker.sql; do
  echo "Applying additive schema: $filename"
  docker compose -f compose.yaml -f compose.m3d.yaml exec -T db \
    psql -U homeos -d homeos -v ON_ERROR_STOP=1 < "$SCHEMA_DIR/$filename"
done
echo 'Memory schema installed. Existing HomeOS records have NOT been replaced.'
