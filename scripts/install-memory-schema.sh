#!/usr/bin/env bash
set -euo pipefail
# Run only after a backup and validation on a restored copy of the database.
cd "$(dirname "$0")/.."
[[ "${HOMEOS_ACK_BACKUP:-}" == "yes" ]] || {
  echo 'Refusing migration: take a verified backup first; set HOMEOS_ACK_BACKUP=yes to proceed.' >&2; exit 2;
}
for name in 001_home_memory.sql 002_visual_memory.sql 003_visual_analysis.sql 004_staged_visual_worker.sql 005_visual_review.sql; do
  echo "Applying additive memory migration: $name"
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U homeos -d homeos < "services/memory/schema/$name"
done
printf 'Memory schema applied; no legacy operational records were deleted.\n'
