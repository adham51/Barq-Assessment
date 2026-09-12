#!/usr/bin/env bash
set -euo pipefail

# backs up the postgres database into ./backups/, gzip'd, keeps last 7
# run it by hand for an instant backup, or from cron for scheduled ones

mkdir -p backups
TS="$(date -u +%Y-%m-%d_%H-%M-%S)" # time in utc 3shan teb2a standardized 
OUT="backups/barq_tasks_${TS}.sql.gz"

if ! docker inspect -f '{{.State.Running}}' postgres 2>/dev/null | grep -q true; then
  echo "postgres container isn't running" >&2
  exit 1
fi

# dump straight out of the container and compress using gzip to save space
docker exec postgres pg_dump -U barq_app -d barq_tasks | gzip > "$OUT"

if [ ! -s "$OUT" ]; then
  echo "backup file is empty, something went wrong" >&2
  rm -f "$OUT"
  exit 1
fi

echo "backed up to $OUT ($(du -h "$OUT" | cut -f1))"

# keep only the 7 most recent backups to not spam files/save space
ls -1t backups/barq_tasks_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f --
