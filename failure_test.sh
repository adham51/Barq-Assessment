#!/usr/bin/env bash
set -euo pipefail

# stops app-01, prints real responses the whole time, brings it back, proves round robin
# usage: ./failure_test.sh [url]

URL="${1:-http://127.0.0.1:8080}"
TARGET="app-01"

echo "stopping $TARGET"
docker stop "$TARGET" > /dev/null

echo "hitting $URL/instance 10x while it's down"
ERRORS=0
for i in $(seq 1 10); do
  if RESP=$(curl -sf "$URL/instance" 2>/dev/null); then
    echo "$RESP"
  else
    echo "NO RESPONSE"
    ERRORS=$((ERRORS+1))
  fi
done
echo "failed requests while down: $ERRORS/10"

echo "starting $TARGET back up"
docker start "$TARGET" > /dev/null

echo "waiting for it to report healthy (still hitting /instance so we're not just sitting idle)"
for i in $(seq 1 15); do
  STATUS=$(docker inspect -f '{{.State.Health.Status}}' "$TARGET" 2>/dev/null || echo unknown)
  RESP=$(curl -sf "$URL/instance" 2>/dev/null || echo "NO RESPONSE")
  echo "$RESP"
  [ "$STATUS" = "healthy" ] && break
  sleep 1
done

echo "hitting $URL/instance 20x, printing raw responses to prove round robin"
SEEN=""
for i in $(seq 1 20); do
  RESP=$(curl -sf "$URL/instance" 2>/dev/null || echo "NO RESPONSE")
  echo "$RESP"
  SEEN="$SEEN $RESP"
done

if echo "$SEEN" | grep -q "app-01" && echo "$SEEN" | grep -q "app-02"; then
  echo "PASS: both backends serving again"
  exit 0
else
  echo "FAIL: app-01 didn't come back into rotation"
  exit 1
fi
