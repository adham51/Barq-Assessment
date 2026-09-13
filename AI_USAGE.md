# AI usage disclosure

Write None if no AI was used. Otherwise record each use:

- Tool/model:
- Purpose:
- Files or decisions affected:
- What you changed or rejected:
- How you independently verified it:
- Related commit:

You may use AI and external resources. You must understand and demonstrate the work.

### 1- **Tool/model:** Big Pickle / OpenCode (free)
* **Purpose:** Initial drafts for backup/restore scripts and debugging validation logic.
* **Files affected:** `backup.sh`, `restore.sh`, `validate.py`
* **What I changed/rejected:**
  1. Rejected the overly complex `pg_dump -Fc` approach with unnecessary env vars — used plain SQL instead.
  2. Added UTC timestamps, `gzip` compression, and a 7-day retention rotation (`find ... -mtime +7 -delete`) myself; set up a cronjob to automate it.
  3. Removed a fake network check in `validate.py` that always returned `PASS` even when `app-02` or `redis` were disconnected from their network — replaced with a real membership check.
  4. Removed the hardcoded port `8080` — made it parse the port from `--url` so switching to `8090` live doesn't break validation.
  5. Removed a fragile localhost socket port scan (misses Docker-remapped ports like `15432:5432`) — replaced with parsing `NetworkSettings.Ports` via `docker inspect`.
  6. Fixed app discovery matching any `app-*` container (would catch stray containers) — filtered by `com.docker.compose.project` label instead.
  7. Removed ~100 lines of unrequested checks (e.g. Docker daemon reachability) to keep the script scoped to the assignment.
* **Verified:** Ran full end-to-end backup/restore cycles confirming timestamps, compression, and data survival. Manually tested `validate.py` against port `8090`, network disconnections, and fake containers to confirm it fails exactly when it should.

### 2- **Tool/model:** Claude (Free version)
* **Purpose:** Initial draft of `failure_test.sh` to test load balancing, failure handling, and round-robin recovery.
* **Files affected:** `failure_test.sh`
* **What I changed/rejected:**
  1. Rejected the initial version, which sat idle/silent while the downed backend was recovering and hid the errors.
  2. Added a continuous loop that actively hits `/instance` during downtime and recovery, printing raw responses live instead of hiding them.
* **Verified:** Ran `./failure_test.sh` locally; output below shows dropped requests during downtime and the exact moment `app-01` came back online and started serving round robin again.

  ```text
  stopping app-01
  hitting http://127.0.0.1:8080/instance 10x while it's down
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  NO RESPONSE
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  NO RESPONSE
  NO RESPONSE
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  NO RESPONSE
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  NO RESPONSE
  NO RESPONSE
  failed requests while down: 6/10
  starting app-01 back up
  waiting for it to report healthy (still hitting /instance so we're not just sitting idle)

  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  hitting http://127.0.0.1:8080/instance 20x, printing raw responses to prove round robin
  {"instance_id":"app-01","service":"barq-api","status":"ok","version":"2.0.0"}
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  {"instance_id":"app-01","service":"barq-api","status":"ok","version":"2.0.0"}

  PASS: both backends serving again
  ```

### 3- **Tool/model:** VS Code Copilot chat (free plan)
* **Purpose:** Documentation formatting and structural cleanup.
* **Files affected:** `troubleshooting.md`, `decisions.md`, `AI_USAGE.md`
* **What I changed/rejected:**
  1. Used it only to reformat my raw notes into markdown — rejected its attempts to suggest code.
  2. Threw out the clunky markdown tables it generated in favor of simpler formatting.
* **Verified:** Read through all generated documentation to confirm the technical explanations and decisions matched exactly how I did the work.

### 4- **Tool/model:** Claude Code (Sonnet 5)
* **Purpose:** Write a script to parse `logs/access.log`, `logs/error.log`, `logs/application.log` and answer the questions in `log_analysis.md`.
* **Files affected:** `scripts/log_analysis.py` (since removed), `log_analysis.md`
* **What I changed/rejected:**
  1. Had it separate malformed and duplicate lines from valid ones instead of just skipping bad lines silently.
  2. Made it treat a comma-separated `upstream`/`upstream_status` field as one retried request, not multiple requests, so retries aren't double-counted.
  3. Rejected trusting its malformed-line exclusions blindly — checked the exact excluded lines myself with `grep` to confirm they were genuinely truncated/unparseable.
* **Verified:** Ran the script myself and manually cross-checked several counts against the raw log files (malformed lines, and two specific request/response pairs read directly from the JSON).
* **Related commit:** (pending)

### 5- **Tool/model:** OpenCode
* **Purpose:** Ran the same log-analysis task through OpenCode as a second, independent pass (`opencode_loganalysis.py`, `log_analysis2.md`), then compared it line-by-line against my own earlier draft (#4) to produce a corrected `log_analysis.md`.
* **Files affected:** `log_analysis.md` (new)
* **What I changed/rejected:**
  1. My draft (#4) lumped all 47 `dependency_error` events into one "Redis timeout" incident. OpenCode's breakdown showed it's actually two unrelated failures: 31 Redis `TimeoutError`s (11:12–11:15) and 16 Postgres `InvalidPassword`s (11:20–11:21), which never overlap in time — confirmed myself with `grep -o '"dependency": ...' logs/application.log | sort | uniq -c`.
  2. My draft's Q1 wrongly implied the truncated line in `access.log` (11:12:48) and the truncated line in `application.log` (11:17:00) were the same request. They're at different timestamps in different files — unrelated truncations. Rejected that claim; neither draft repeats it now.
  3. My draft's error-rate number (14.58%) didn't separate the 10 expected `/missing` 404 probes from real failures. OpenCode's version adds the adjusted rate excluding them (95/720 = 13.19%), which is the more honest failure rate.
  4. My draft referred to backends only by raw IP (`172.23.0.11`/`.12`). OpenCode mapped them to instance names (`app-01`/`app-02`) by correlating with `application.log` — I re-derived that mapping myself before trusting it, rather than accepting it as given.
  5. My draft gave only overall latency percentiles. OpenCode split them by status (200-only vs. ≥400-only), proving the elevated p95/p99 comes entirely from failed requests, not general slowness — a stronger, more specific claim than my draft made.
  6. My draft's Q6 never noticed that only read-only endpoints (`/ready`, `/instance`) got retried, while `/counter`/`/records` never did. OpenCode's retry breakdown by path surfaced that pattern.
  7. My draft asserted (without a concrete example) that some 504s had a late, successful app response. OpenCode's Q8 supplied an actual correlated example (`lab-000606`) proving it instead of leaving it as an unproven claim.
* **Verified:** Checked every headline number in `log_analysis.md` (line/duplicate/malformed counts, status counts, latency percentiles, retry counts, the redis/postgres split, the instance mapping, correlated request IDs) against the raw log files myself with `grep`/`python3` one-liners — not taken from either draft's output on faith. Two of these spot-checks are kept as commands in `log_analysis.md` itself: `grep -o '"status":[0-9]*' logs/access.log | ...` and `grep -o '"request_id":"[^"]*"' logs/access.log | sort -u | wc -l`.
* **Related commit:** (pending)
