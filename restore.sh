#!/usr/bin/env bash
set -euo pipefail

# restores a .sql.gz backup into the running postgres container
# usage: ./restore.sh backups/some_file.sql.gz --clean

if [ $# -lt 1 ]; then
  echo "usage: $0 <backup-file.sql.gz> [--clean]"
  exit 1
fi

# $1 is the first argument passed to the script after ./restore.sh mel 2a5r file name
FILE="$1"

# make sure the backup file exists and isn't empty
if [ ! -s "$FILE" ]; then
  echo "no such file (or it's empty): $FILE" >&2
  exit 1
fi

# make sure the postgres container is running before trying to restore
if ! docker inspect -f '{{.State.Running}}' postgres 2>/dev/null | grep -q true; then
  echo "postgres container isn't running" >&2
  exit 1
fi

# --clean dah must be took as second argument because we first drop the old database and create it again to restore backup 3la clean db
if [ "${2:-}" = "--clean" ]; then
  docker exec postgres psql -U barq_app -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='barq_tasks' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS barq_tasks;" \
    -c "CREATE DATABASE barq_tasks OWNER barq_app;"
fi

# restore is basically the reverse of the backup: .sql.gz -> gunzip -> sql -> psql -> postgres
# gunzip -c sends the decompressed sql to stdout
# docker exec -i lets psql receive the sql from the pipe
gunzip -c "$FILE" | docker exec -i postgres \
  psql -U barq_app -d barq_tasks

# check success of restore and count of rows
COUNT=$(docker exec postgres \
  psql -U barq_app -d barq_tasks -t \
  -c "SELECT COUNT(*) FROM records;" | tr -d ' ')

echo "restore done, records table has $COUNT rows"
