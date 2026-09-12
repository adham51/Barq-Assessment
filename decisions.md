# Technical decisions

Record at least 5 decisions. Include assumptions and limits.

## Decision
- Choice:
- Why:
- Alternative:
- Trade-off:
- Evidence / commit:
- Production improvement:

Cover your base image, health checks, networks, timeouts/retries, restart/resource settings,
storage and any other meaningful choices.

### 1- Redis AOF Persistance

* **Choice:** Use Redis **AOF (Append Only File)** persistence with a named `redis-data` volume.

* **Why:** The `/counter` feature is **stateful**, so the counter value should survive a Redis restart or container recreation. AOF records write operations and therefore provides more frequent persistence for frequently changing state than periodic RDB snapshots.

* **Alternative:** RDB snapshots, where Redis periodically saves snapshots of the current dataset to disk.

* **Trade-off:** AOF provides better durability for the frequently changing `/counter` state, but introduces more disk I/O and storage overhead than periodic RDB snapshots.


| Metric                   | AOF                              | RDB                                  |
| ------------------------ | -------------------------------- | ------------------------------------ |
| Persistence method       | Records write operations         | Periodic dataset snapshots           |
| Recent data-loss risk    | Lower RPO, depending on fsync policy | Potentially higher between snapshots - more data loss |
| Frequent counter updates | Better fit                       | Less suitable                        |
| Disk/I/O overhead        | Higher                           | Lower                                |
| Recovery                 | Replays AOF operations           | Loads latest snapshot                |
| Our choice               | **Selected**                     | Alternative                          |



* **Assumption / Limit:** The `/counter` value is treated as application state that should survive Redis restarts/recreation. AOF persistence does **not** replace proper backups, replication, or a durable primary database for business-critical data.

* **Evidence / commit:** Verified by restarting/recreating the Redis container while keeping the `redis-data` volume and confirming that the counter value persists. 

    Commit: `5e5cc4ec872122af6a87446014e988b2d1d74b67`

* **Production improvement:** Configure an explicit AOF `fsync` policy based on the required durability, monitor Redis disk usage and persistence health, and evaluate moving business-critical counter state to PostgreSQL or another durable datastore if the application grows.

  `fsync` forces the OS to write buffered data to disk. With Redis AOF:
    - `appendfsync always` — writes to disk after **every write**; safest, but slowest.
    - `appendfsync everysec` — writes roughly **every second**; good balance.
    - `appendfsync no` — lets the OS decide when to write; fastest, but potentially more data loss.

---
 ## 2. NGINX max_fails=0 and proxy_next_upstream off

* **Choice:** Left `max_fails=0` and `proxy_next_upstream off` in place rather than enabling automatic failover.

* **Why:** Makes per-backend failures directly observable and attributable in logs/tests, matching the assessment's explicit ask to show "continued traffic and errors" during an outage.

* **Alternative:** `max_fails=2 fail_timeout=5s` per server, plus `proxy_next_upstream error timeout http_502 http_503`, would let NGINX silently retry failed requests on the healthy backend.

* **Trade-off:** Current setup sacrifices client-facing availability during a backend outage in exchange for clearer failure visibility.

* **Assumption / Limit:** The assessment intentionally requires backend failures and continued traffic/errors to remain observable during the outage. This configuration is therefore suitable for the assessment but is not optimized for production availability.

* **Evidence / commit:** `failure_test.sh` run showing 7/10 failed during downtime, recovered to PASS afterward.

    Commit: `<commit-hash>`

* **Production improvement:** Enable passive health checks + `proxy_next_upstream` retry for real HA; current setup is intentionally "observable," not "resilient."  


---

## 3. PostgreSQL backup format, compression, retention, and scheduling

* **Choice:** Plain SQL `pg_dump` piped into `gzip` (`.sql.gz`), UTC timestamps for unified timing, last 7 backups kept, same script runs manually or from a daily `cron` job.

* **Why:** Piping into `gzip` skips an intermediate dump file in the container. UTC timestamps stay unambiguous regardless of host time zone. Keeping 7 limits disk growth. One script for both manual and scheduled runs, `cron` only decides *when*, not a separate implementation.

* **Alternative:** `pg_dump -Fc` (custom format), smaller, pairs with `pg_restore` for selective/parallel restores.

* **Trade-off:** Custom format buys restore flexibility this project doesn't need. Plain SQL + gzip is human-readable and simpler to explain. Only 7 backups means anything older is gone unless copied off-host.

* **Assumption / Limit:** Dataset is tiny, so plain-SQL size/speed isn't an issue here, maybe an issue for a large production DB. Cron needs the host's cron daemon running; does nothing if the machine is off at the scheduled time.

* **Evidence / commit:** Created a record, backed it up, deleted it from the database, restored from the backup, confirmed it came back (README "Backup / Restore" section).

    Commit: `<commit-hash>`

* **Production improvement:** Prefer `pg_dump -Fc` or WAL archiving for larger data, store backups off-host, use a monitored scheduler instead of bare cron.
