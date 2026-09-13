# Log analysis

Use all three supplied logs. Answer every question with commands/scripts and actual output.

1. What UTC interval is covered? How many valid, malformed and duplicate lines are in each file?
2. How many distinct client requests occurred? How did you deduplicate and avoid counting retries twice?
3. What are the final client status counts and error rate? State your denominator.
4. Which paths, time windows and backends account for the failures?
5. What are the median and p95 client latencies? State the percentile method and units.
6. Which requests retried upstream? How many succeeded after retrying?
7. Build an incident timeline using evidence from access, error AND application logs.
8. Show one correlated failed request and one successful request. Include IDs and timestamps.
9. Which errors appear to be proxy/connectivity issues versus dependency/application issues? What proves it?
10. What do the logs not prove? What would you check next in a running environment?

## Incident summary

A healthy two-instance service (24 req/min, all 200 except intentional `/missing` probes) hit
**three separate outages inside one 30-minute window**, each with a different root cause:

1. **11:05–11:09** — backend `app-02` (`172.23.0.12`) stopped accepting connections → NGINX
   returned 502 (connection refused). `app-01` absorbed the extra load and 19 retried requests
   recovered automatically.
2. **11:12–11:15** and **11:20–11:21** — the app itself returned 503 after failing to reach a
   dependency: a Redis timeout wave (11:12–15) followed by a Postgres authentication failure wave
   (11:20–21). Two different dependencies, two different error types, back to back.
3. **11:25–11:26** — `/records` got slow enough that NGINX's read timeout fired (504) before the
   app finished; the app itself completed the request about 0.7s later and logged 200.

Everything else in the window ran clean.

## Commands / scripts

Every number below comes from `scripts/log_analysis.py`, which parses the three original log
files (never modifies them) and prints the evidence for each question:

```bash
python3 scripts/log_analysis.py
```

This script folds in a correction found while comparing two earlier drafts of this analysis: one
draft bucketed all 47 `dependency_error` events into a single "Redis timeout" incident, which
turned out to be wrong — see the note under Q7.

**Spot-checks run independently (without relying on the script), to confirm the numbers weren't
just a bug reproduced twice:**

```bash
grep -o '"status":[0-9]*' logs/access.log | grep -v upstream_status | sort | uniq -c
```
Gives `200:620, 404:10, 502:40, 503:47, 504:8` — the 502/503/504/404 counts match the Q3 table
exactly, but 200 shows 620, not 615. That's expected: this command counts raw lines and doesn't
drop the 5 duplicate `(request_id, timestamp)` lines from Q1. 620 − 615 = 5, which independently
confirms those 5 duplicates were all repeats of 200-status requests — a useful cross-check on its
own, not a discrepancy.

```bash
grep -o '"request_id":"[^"]*"' logs/access.log | sort -u | wc -l
```
Confirms the Q2 distinct-request count (720) directly from the raw file, no JSON parser needed.

Parse rules (agreed by both scripts and confirmed against the raw files):
- `access.log` / `application.log` are JSON-per-line; a line that fails `json.loads` is malformed.
- `error.log` lines are matched against the standard NGINX error-line format with a `request_id`;
  a line that doesn't match (e.g. the `[notice]` log-rotation line) is malformed.
- A line is a **duplicate** if its `(request_id, timestamp)` pair already appeared earlier in the
  same file — dropped before any counting.
- A **retry** is not a separate request: it's one `access.log` line whose `upstream` /
  `upstream_status` fields hold a comma-separated list of attempts for that one client request.

## Results

### 1. UTC interval, valid/malformed/duplicate lines

| File | Raw lines | Valid | Duplicate lines | Malformed | Interval (UTC) |
|---|---|---|---|---|---|
| access.log | 726 | 720 | 5 | 1 | 2026-08-20 11:00:00.015 → 11:29:57.578 |
| application.log | 730 | 727 | 2 | 1 | 2026-08-20 11:00:00.015 → 11:29:57.578 |
| error.log | 68 | 67 | 0 | 1 | 2026-08-20 11:05:02 → 11:26:47 |

All three logs cover the same 30-minute incident window. The malformed lines are:
`access.log`/`application.log` — one truncated JSON line each, cut off mid-object (grepped
directly, confirmed they never close their braces); `error.log` — a `[notice]` log-rotation line
at 11:30:00 with no `request_id`, correctly excluded rather than miscounted as a request error.

### 2. Distinct client requests and deduplication

**720 distinct client requests** — `request_id`s `lab-000001` through `lab-000720`, sequential
with no gaps, which independently confirms the count.

- Deduplicate by `request_id` in `access.log` only, after dropping the 5 lines that are exact
  `(request_id, timestamp)` repeats of an earlier line (NGINX emitted the same event twice).
- A retry is **already** one access.log line (comma-separated `upstream`/`upstream_status`), so
  splitting those fields into an attempt list — instead of treating each upstream hop as its own
  request — is what keeps retries from being double-counted.
- `application.log` is not used to count requests: 40 requests never reached any app instance and
  would be undercounted there. `error.log` isn't used either: some requests produce zero error
  lines, others produce one per retry attempt. Both are used only for correlation (Q7–Q9).

### 3. Final client status counts and error rate

**Denominator = 720** (all valid, deduplicated `access.log` requests).

| Status | Count |
|---|---|
| 200 | 615 |
| 404 | 10 |
| 502 | 40 |
| 503 | 47 |
| 504 | 8 |

Errors (≥400) = 105 → **error rate = 105/720 = 14.58%**.

The 10 `404`s are all deliberate probes to `/missing` (spaced every ~3 minutes throughout the
whole window, not clustered in an incident) — not an incident symptom. Excluding them: **95
genuine failures / 720 = 13.19%**.

### 4. Failures by path, time window, backend

By path:

| Path | Failures | Breakdown |
|---|---|---|
| /records | 26 | 502:10, 503:8, 504:8 |
| /counter | 26 | 502:10, 503:16 |
| /ready | 23 | 503:23 |
| /missing | 10 | 404:10 (expected probe traffic) |
| /health | 10 | 502:10 |
| / | 10 | 502:10 |

By minute:

| Window | Rate | Status |
|---|---|---|
| 11:05–11:09 | 8–9/min | 502 |
| 11:12–11:15 | 8/min | 503 (redis) |
| 11:20–11:21 | 8/min | 503 (postgres) |
| 11:25–11:26 | 4–5/min | 504 |

By backend (first-attempted upstream per failed request). Instance mapping (`172.23.0.11` =
`app-01`, `172.23.0.12` = `app-02`) is derived from correlated 200s in application.log and holds
for all 720 requests:

| Upstream | Failed attempts | Breakdown |
|---|---|---|
| 172.23.0.12:8080 (app-02) | 73 | 404:5, 502:40, 503:24, 504:4 |
| 172.23.0.11:8080 (app-01) | 32 | 404:5, 503:23, 504:4 |

All 40 pure 502s were first-attempted at `.12` only — a node-specific failure. The 503s and 504s
split roughly evenly across both instances, confirming those were dependency/shared-resource
problems rather than one bad node.

### 5. Client latencies

n = 720, from `request_time` (seconds, converted to ms). Method: **nearest-rank percentile** —
sort ascending, take the value at rank `ceil(p/100 × n)`.

| | n | median | p95 | p99 | min | max |
|---|---|---|---|---|---|---|
| all requests | 720 | 54 ms | 2001 ms | 2025 ms | 3 ms | 2025 ms |
| 200-only | 615 | 55 ms | 93 ms | — | — | — |
| ≥400-only | 105 | 41 ms | 2025 ms | — | — | — |

Healthy traffic is fast (median 54ms, p95 93ms for 200s). The overall p95/p99 is dragged up
entirely by the failure tail: every 503 waits out a ~2s Redis timeout and every 504 waits out
NGINX's ~2s read timeout before giving up — the latency tail is failure behavior, not normal load.

### 6. Retried-upstream requests

**19 requests** show more than one upstream attempt in `access.log`. **All 19 succeeded on
retry** (final status 200), all inside the 11:05–11:09 window. Every retry followed the same
pattern: first attempt to `172.23.0.12:8080` (app-02) → 502, second attempt to
`172.23.0.11:8080` (app-01) → 200.

Retried paths: `/ready` (10) and `/instance` (9) only — read-only probe endpoints. `/counter` and
`/records` (which mutate/read heavier state) were never retried and kept their 502, suggesting the
proxy only retries safe (idempotent, read-only) routes.

Example:
```
rid=lab-000124 11:05:07.620Z /ready    attempts=[172.23.0.12:8080, 172.23.0.11:8080] statuses=[502,200] final=200
rid=lab-000130 11:05:22.620Z /instance attempts=[172.23.0.12:8080, 172.23.0.11:8080] statuses=[502,200] final=200
```

Retry rate = 19/720 = 2.64% of all requests — small compared to the 40 pure-502 failures, since
most 502s during this window were returned straight to the client without a retry.

### 7. Incident timeline

| Time (UTC) | access.log | error.log | application.log |
|---|---|---|---|
| 11:00–11:04 | 24 req/min, all 200 (404 probes at :00, :03) | silent | even app-01/app-02 split, healthy |
| 11:05–11:09 | 40×502 (8–9/min), 19 retried → 200 | 59× `connect() failed (111)` to `.12`, ~12/min | zero events for app-02; app-01 absorbs the load |
| 11:10–11:11 | all 200 | silent | both instances healthy again |
| 11:12–11:15 | 8×503/min | silent (TCP fine) | 31× `dependency_error` (`redis`, `TimeoutError`) |
| 11:16–11:19 | only 404 probes | silent | healthy |
| 11:20–11:21 | 8×503/min | silent | 16× `dependency_error` (`postgres`, `InvalidPassword`) |
| 11:22–11:24 | healthy | silent | healthy |
| 11:25–11:26 | 8×504 on `/records` | 8× `upstream timed out (110)` | app **does** log 200 (duration_ms ~2700) shortly after NGINX gave up |
| 11:27–11:29 | all 200 (404 probe at :29) | silent | healthy |
| 11:30 | — | log-rotation notice | — |

**Correction found while cross-checking the two draft scripts:** an earlier pass treated all 47
`dependency_error` events as one Redis-timeout incident. Splitting by `dependency` field shows
that's wrong — it's two distinct failures back to back:

```
grep -o '"dependency": "[a-z]*", "error_type": "[A-Za-z]*"' logs/application.log | sort | uniq -c
     16 "dependency": "postgres", "error_type": "InvalidPassword"
     31 "dependency": "redis", "error_type": "TimeoutError"
```

and by minute, they don't overlap at all — redis errors are 11:12–11:15 only, postgres errors are
11:20–11:21 only. A Postgres *authentication* failure is a materially different problem (bad/
rotated credentials, not a slow dependency) from a Redis timeout, so treating the whole 11:12–21
span as "one Redis incident" would have pointed troubleshooting in the wrong direction.

### 8. Correlated examples

**Failed — proxy/connectivity (502, never reached the app):**
```
access.log:      2026-08-20T11:05:02.503Z rid=lab-000122 GET /health -> [172.23.0.12:8080] status=502 request_time=0.003s
error.log:       11:05:02 connect() failed (111: Connection refused), request_id=lab-000122, upstream=http://172.23.0.12:8080/health
application.log: no entry for lab-000122 (request never reached an app instance)
```

**Failed — dependency/application (503, app reached and answered):**
```
access.log:      2026-08-20T11:12:09.525Z rid=lab-000292 GET /ready -> [172.23.0.12:8080] status=503 request_time=2.025s
application.log: event=http_request instance=app-02 status=503 duration_ms=2025.0
                 event=dependency_error dependency=redis error_type=TimeoutError instance=app-02
```

**Failed — proxy timeout with late app success (504, app finished anyway):**
```
access.log:      2026-08-20T11:25:14.501Z rid=lab-000606 GET /records -> [172.23.0.12:8080] status=504 request_time=2.001s
error.log:       11:25:14 upstream timed out (110: Operation timed out), request_id=lab-000606
application.log: 2026-08-20T11:25:15.200Z status=200 duration_ms=2700.0 instance=app-02 (finished ~0.7s after NGINX gave up)
```

**Success (200, all logs agree):**
```
access.log:      2026-08-20T11:00:02.532Z rid=lab-000002 GET /health -> [172.23.0.12:8080] status=200 request_time=0.032s
application.log: 2026-08-20T11:00:02.532Z instance=app-02 status=200 duration_ms=32.0
```

The 504 example matters: the app-side status is not always the client-facing status, so any join
between logs has to be done on `request_id`, never inferred from status code alone.

### 9. Proxy/connectivity vs. dependency/application errors

| Class | Client status | Evidence | Count |
|---|---|---|---|
| Proxy/connectivity | 502 | `error.log` `connect() failed (111)`; zero matching `application.log` events; all targeted `.12` | 40 |
| Proxy timeout | 504 | `error.log` `upstream timed out (110)`; app logs 200 *after* NGINX already gave up | 8 |
| Dependency/application | 503 | app `http_request` status 503 + a `dependency_error` event, same request_id; **zero** matching `error.log` entries | 47 |

The two classes are cleanly separable by which log is silent:
- **502/504 (48 total):** NGINX's own error.log has a `connect()`/`timed out` line at the exact
  same second and request_id; 40 of these never produced any application.log event at all
  (never reached an instance), the other 8 (504s) got an app event only after NGINX had already
  aborted.
- **503 (47 total):** `error.log` is silent for every one of them — the TCP connection from NGINX
  to the app succeeded — while `application.log` shows the app returning 503 on its own, paired
  with a `dependency_error` event: 31 Redis `TimeoutError`s and 16 Postgres `InvalidPassword`s.
  These are two different dependency failures, not one, and neither leaves any error.log trace.

### 10. What the logs don't prove / next steps

These are edge (NGINX) and application logs for one 30-minute window. They do **not** show:
- **Why** `app-02` stopped accepting connections at 11:05 — no container/orchestrator events,
  restart records, or OS/resource metrics are present.
- **Why** Postgres rejected credentials at 11:20 (rotated/expired password? config drift?) or what
  was slow on the Redis side at 11:12 — there are no DB/Redis server-side logs, so the 503 root
  cause is only visible as an app-side label, not its true origin.
- The actual NGINX config in force at the time (retry policy, read-timeout value) — behavior is
  *inferred* from the incident (looks like a ~2s read timeout, retries only on `/ready`/`/instance`)
  and should be checked against the live `nginx.conf`.
- Whether the late 200 during the 504 window (app finished `/records` ~0.7s after NGINX gave up)
  wrote any user-visible state the client never saw confirmed.
- That `172.23.0.11`/`.12` really are `app-01`/`app-02` today — the mapping here is inferred from
  correlated 200s in synthetic lab data and should be reconfirmed with `docker inspect` or the
  `/instance` endpoint in a running environment.

**Next checks in a live environment:** container restart/health events for `app-02` around 11:05;
Postgres auth/connection logs and Redis `INFO`/slowlog around 11:12–11:21; current
`proxy_read_timeout` and retry (`proxy_next_upstream`) settings in `nginx.conf`; and per-backend,
per-status dashboards so this kind of three-incident window is visible without grepping raw logs.

## Timeline and correlated examples

See Q7 and Q8 above.

## Conclusions and limits

Three unrelated incidents inside 30 minutes, each with an unambiguous signature: 502 ↔
`connect() failed` to app-02 with no app-log trace; 503 ↔ a `dependency_error` event with no
error-log trace (redis timeout, then separately postgres auth failure); 504 ↔ `upstream timed
out` with a late app 200. Overall error rate 14.58% (13.19% excluding the expected `/missing`
probes), all of it inside these three windows — outside them the system was clean.

**Limits:** the one truncated line in each of access.log/application.log is simply dropped —
there's no way to recover which request it belonged to from the file alone; all figures describe
this stored window only and shouldn't be read as steady-state error rates; and the IP→instance
mapping, while internally consistent across all 720 requests, is inferred rather than confirmed
against infrastructure records.
