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

<a id="decision-1"></a>
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
<a id="decision-2"></a>
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

<a id="decision-3"></a>
## 3. PostgreSQL backup format, compression, retention, and scheduling

* **Choice:** Plain SQL `pg_dump` piped into `gzip` (`.sql.gz`), UTC timestamps for unified timing, last 7 backups kept, same script runs manually or from a daily `cron` job.

* **Why:** Piping into `gzip` skips an intermediate dump file in the container. UTC timestamps stay unambiguous regardless of host time zone. Keeping 7 limits disk growth. One script for both manual and scheduled runs, `cron` only decides *when*, not a separate implementation.

* **Alternative:** `pg_dump -Fc` (custom format), smaller, pairs with `pg_restore` for selective/parallel restores.

* **Trade-off:** Custom format buys restore flexibility this project doesn't need. Plain SQL + gzip is human-readable and simpler to explain. Only 7 backups means anything older is gone unless copied off-host.

* **Assumption / Limit:** Dataset is tiny, so plain-SQL size/speed isn't an issue here, maybe an issue for a large production DB. Cron needs the host's cron daemon running; does nothing if the machine is off at the scheduled time.

* **Evidence / commit:** Created a record, backed it up, deleted it from the database, restored from the backup, confirmed it came back (README "Backup / Restore" section).

    Commit: `<commit-hash>`

* **Production improvement:** Prefer `pg_dump -Fc` or WAL archiving for larger data, store backups off-host, use a monitored scheduler instead of bare cron.

---

<a id="decision-4"></a>
## 4. DevSecOps shift-left security checks in CI

* **Choice:** Add shift-left security checks to GitHub Actions on every push and pull request.

* **What I added compared with the task:** The required CI flow is implemented in `validate`: checkout, syntax and Compose checks, build, startup, readiness wait, and `validate.py`. I also added Gitleaks, SonarCloud SAST, Trivy SCA, CycloneDX SBOM generation, container scanning, and SARIF uploads.

* **Why:** Early checks catch secrets, code issues, dependency vulnerabilities, and image risks before release.

* **Alternative:** Run scans manually or only scan the final image.

* **Trade-off:** CI takes longer, and Trivy currently reports HIGH/CRITICAL findings without failing the build.

* **Assumption / Limit:** DAST, image signing, and centralized ASPM/DefectDojo tracking are future work.

* **Evidence / commit:** `.github/workflows/CI.yml`; commits `51148e5` and `a050182`.

* **Production improvement:** Add DAST, enforce severity gates, pin Actions to commit SHAs, and send findings to DefectDojo with owners and SLAs.

---

<a id="decision-5"></a>
## 5. Health-check tooling — use what's already in the image, not extra packages

* **Choice:** Each service's healthcheck uses a tool already present in its base image: `python -c "import urllib.request..."` for the Flask app (no `curl`/`wget` in that image), `pg_isready` for Postgres, `redis-cli ping` for Redis, `wget --spider` against NGINX's own root (not `/health`, so it tests NGINX itself, not a backend).

* **Why:** The brief says to use health-check tools already installed in the image — installing `curl`/`wget` into a slim image just for a healthcheck adds packages and attack surface for no real benefit.

* **Alternative:** Install a common CLI (e.g. `curl`) in every image so all healthchecks look the same.

* **Trade-off:** Each healthcheck command looks different across services in exchange for smaller images and no unused packages.

* **Assumption / Limit:** Relies on each upstream image continuing to ship that tool; switching to a distroless variant later would break the healthcheck.

* **Evidence / commit:** `docker-compose.yml` healthcheck blocks; `docker compose ps` showing all five services healthy.

* **Production improvement:** Standardize on one HTTP-based health endpoint pattern, or move checks to the orchestrator level (e.g. k8s liveness/readiness probes) instead of image-bundled CLI tools.

---

<a id="decision-6"></a>
## 6. Restart policy (`unless-stopped`) and per-service resource limits

* **Choice:** `restart: unless-stopped` on every service, plus fixed limits: `app-01`/`app-02` 0.5 CPU / 256M each, `postgres` 1.0 CPU / 512M, `redis` 0.5 CPU / 256M, `nginx` 0.5 CPU / 128M.

* **Why:** `unless-stopped` auto-recovers from a crash or reboot but, unlike `always`, doesn't fight a deliberate `docker stop` — needed so `failure_test.sh` and the video's live backend-stop actually keep `app-01` down until it's restarted on purpose. Limits are weighted by role and sized to fit the lab's stated 2 CPU / 4GB capacity: Postgres gets the most (it's the actual data engine), the two app instances split an equal moderate share, Redis is memory- not CPU-bound, NGINX (just a proxy) gets the least.

* **Alternative:** `restart: always` (fights manual stops) or `on-failure` (no restart after a clean stop or reboot). Resources: no limits, or numbers from a real load test instead of estimates.

* **Trade-off:** An accidental manual stop also stays down under `unless-stopped` — acceptable since a human always drives the stop here. Resource numbers are estimates, not load-tested, so may be off for real traffic.

* **Assumption / Limit:** Assumes ~2 CPU / 4GB free on the host. Validated with `docker stats` during normal use and the failure test, not formal load testing.

* **Evidence / commit:** `docker-compose.yml` `restart`/`deploy.resources.limits` blocks; `docker stats`; `failure_test.sh` proving `app-01` stays down until restarted.

* **Production improvement:** Size limits from real metrics (`docker stats`, Prometheus/cAdvisor) instead of estimates, and consider autoscaling over static limits.

---

<a id="decision-7"></a>
## 7. Bash for operational scripts and Python for validation

* **Choice:** Use Bash for `backup.sh`, `restore.sh`, and `failure_test.sh`, while keeping `validate.py` in Python.

* **Why:** We are literally running Linux and Docker commands in these scripts, such as `docker stop`, `docker start`, `docker exec`, `pg_dump`, and `psql`, so Bash is the more natural and direct choice. Python would add unnecessary complexity for these command-based tasks. `validate.py` is larger because it parses responses, inspects Docker JSON, checks networks and ports, and manages several validation results.

* **Alternative:** Write all four scripts in Python.

* **Trade-off:** Bash is easy to follow in Linux/WSL and cron, while Python is better suited to the more structured validation logic.

* **Evidence / commit:** `backup.sh`, `restore.sh`, `failure_test.sh`, and `validate.py`; commit `eea8092`.

* **Production improvement:** Use a managed backup scheduler or a tested Python/backup utility with encryption, off-host storage, monitoring, and restore alerts.
