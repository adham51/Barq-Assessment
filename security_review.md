# Security and production-readiness review

Record at least 8 concrete risks or improvements relevant to your final solution.
This is a review requirement, not the number of hidden faults.

For each finding:
- Risk and evidence:
- Impact:
- Implemented fix / commit:
- Production follow-up:
- How to verify:

Cover secrets, ports, container user, image selection, networks, persistence/backup,
logging/monitoring and availability. Separate completed work from planned improvements.


# Security Review

## Implemented Security Improvements

### 1. Container User Escalation

- **Risk and evidence:** The Python app container was running as `root` (found in the Dockerfile) and lacked privilege escalation protection. If the app is compromised, the attacker gains root access inside the container.
- **Impact:** High. Attackers could potentially break out of the container or modify internal system files.
- **Implemented fix / commit:** Created an unprivileged user `app` (UID 10001), added `USER app` to the Dockerfile, and enforced `user: "10001:10001"` with `security_opt: [no-new-privileges:true]` in `docker-compose.yml`.
- **Production follow-up:** Regularly scan the base image for vulnerabilities to reduce the risk of container escape through kernel or runtime vulnerabilities.
- **How to verify:** Run `docker compose exec app-01 id` and confirm it returns `uid=10001`.

### 2. Database and Cache Port Exposure

- **Risk and evidence:** PostgreSQL and Redis ports (`15432` and `16379`) were published directly to the host machine in `docker-compose.yml`.
- **Impact:** High. Anyone with access to the host machine's network could attempt to connect to the database or cache directly, bypassing the API.
- **Implemented fix / commit:** Removed the `ports` mappings for PostgreSQL and Redis. Only NGINX binds to a host port (`8080`).
- **Production follow-up:** Implement a host firewall (e.g., `ufw` or cloud security groups) to ensure only necessary public ports such as 80/443 are exposed.
- **How to verify:** Run `docker compose ps` and confirm that PostgreSQL and Redis have no published host ports.

### 3. Network Segmentation (NGINX Over-Privileged)

- **Risk and evidence:** NGINX was attached to both the `frontend` and `backend` networks, giving the reverse proxy direct network-level access to the database and cache.
- **Impact:** Medium. If NGINX is compromised, the attacker would have a direct network route to internal data stores.
- **Implemented fix / commit:** Removed NGINX from the `backend` network. NGINX can now communicate only with the application containers through the `frontend` network.
- **Production follow-up:** Use network policies or firewall controls to further restrict service-to-service communication and consider a WAF to filter malicious HTTP traffic before it reaches the application.
- **How to verify:** Run `docker compose exec nginx getent hosts postgres` and confirm that the database service cannot be resolved from the NGINX container.

### 4. Ephemeral Database Storage (Data Loss)

- **Risk and evidence:** PostgreSQL data was being mounted to a `tmpfs` (RAM), meaning all database records would be permanently lost when the container was removed or the temporary filesystem was lost.
- **Impact:** Critical. Complete loss of transactional data could occur without persistent storage.
- **Implemented fix / commit:** Removed `tmpfs` and mapped the `postgres-data` named volume directly to `/var/lib/postgresql/data`.
- **Production follow-up:** Set up automated `pg_dump` backups and store encrypted backup copies in external durable storage such as AWS S3, with retention and restore testing.
- **How to verify:** Create a record via the API, recreate the PostgreSQL container while keeping the named volume, and fetch the record again to confirm that it persists.

### 5. Secrets in Configuration / `.env` Handling

- **Risk and evidence:** Database credentials and connection strings are required by the application and are provided through environment variables. Storing actual secrets in `docker-compose.yml`, source code, or committed `.env` files could expose credentials through version control.
- **Impact:** High. Exposed database or Redis credentials could allow unauthorized access to application data and internal services.
- **Implemented fix / commit:** Moved sensitive values such as `POSTGRES_PASSWORD`, `DATABASE_URL`, and `REDIS_URL` to a local `.env` file referenced by Docker Compose. The `.env` file is excluded from version control, while a safe `.env.example` contains only placeholder values.
- **Production follow-up:** Use a dedicated secrets manager such as AWS Secrets Manager or HashiCorp Vault instead of storing secrets in local environment files. Rotate credentials regularly and avoid exposing secrets in logs or container images.
- **How to verify:** Run `git status` and `git check-ignore .env` to confirm the real `.env` file is ignored, and inspect the repository to ensure no actual credentials are committed.

### 6. DevSecOps Shift-Left Checks in CI

- **Risk and evidence:** Security defects can reach the shared branch if security checks are performed only after deployment. The GitHub Actions workflow runs security checks during pull requests and pushes, before the image is promoted or used as a release artifact.
- **Impact:** High. Earlier feedback reduces the time that vulnerable dependencies, leaked secrets, or insecure code remain in the branch and makes security findings part of the normal development workflow.
- **Implemented fix / commit:** Added `secret_scanning`, `sast_scan`, `sca_scan`, and `container_security` jobs in `.github/workflows/CI.yml`. Gitleaks checks for exposed secrets, SonarCloud provides SAST, Trivy scans the filesystem and image, and the workflow generates and uploads SARIF reports and an SBOM. Related commits: `51148e5` and `a050182`.
- **Production follow-up:** Add DAST against a deployed test environment and centralize findings in an ASPM platform such as DefectDojo. Define ownership, severity SLAs, deduplication rules, and an exception/expiry process. DAST and DefectDojo ingestion are planned, not implemented in this assessment.
- **How to verify:** Open the GitHub Actions run for the final commit and confirm the security jobs, SARIF uploads, and SBOM artifact. Confirm that a failed required validation job makes the workflow fail.

### 7. Dependency, Image, and Software Supply-Chain Risk

- **Risk and evidence:** Vulnerable or mutable base images and dependencies can introduce risk without a source-code change. The application and service images are pinned by digest, while Python dependencies are version-pinned in `requirements.txt`.
- **Impact:** High. A compromised registry tag or vulnerable transitive package could affect every rebuilt application container.
- **Implemented fix / commit:** Pinned the Python, PostgreSQL, Redis, and NGINX images by digest and added Trivy filesystem and container-image scans to CI. The generated SBOM records the dependency inventory. Related commits: `5e5cc4e` and `51148e5`.
- **Production follow-up:** Automate digest refreshes through a reviewed dependency-update process, fail builds on agreed HIGH/CRITICAL policy thresholds, sign images, verify provenance, and retain SBOMs for every released image.
- **How to verify:** Run `docker compose config` and confirm image digests, then inspect the Trivy SARIF reports and SBOM artifact in GitHub Actions.

### 8. Redis State Persistence

- **Risk and evidence:** Redis was configured without persistence, so the stateful `/counter` value could disappear after a container recreation even though the application relies on Redis for shared state across app instances.
- **Impact:** Medium to High. Counter state and any future cache-backed workflow could be lost during maintenance or an unplanned restart.
- **Implemented fix / commit:** Enabled Redis AOF persistence with `appendfsync everysec` and mounted a named `redis-data` volume at `/data`. This keeps Redis state outside the container lifecycle. Related commit: `5e5cc4e`.
- **Production follow-up:** Monitor AOF rewrite health and disk usage, define an acceptable recovery point objective, encrypt or restrict access to the volume, and use replication or a managed Redis service when the state becomes business-critical. Redis persistence is not a substitute for PostgreSQL backups.
- **How to verify:** Increment `/counter`, recreate only the Redis container without removing volumes, and confirm that the counter continues from its previous value. Inspect `docker volume inspect` and the Redis configuration.

### 9. PostgreSQL Backup and Restore Protection

- **Risk and evidence:** Persistent storage protects against container recreation but not corruption, accidental deletion, or host loss. A volume alone is not a backup.
- **Impact:** Critical. Without a tested backup, database records could be unrecoverable after a storage failure or destructive operator action.
- **Implemented fix / commit:** Added `backup.sh` to create compressed UTC-named `pg_dump` files with bounded retention and `restore.sh` to restore a selected dump, including an optional clean-database path. The PostgreSQL named volume is retained during normal recreation. Related commit: `eea8092`.
- **Production follow-up:** Encrypt backups, store copies outside the Docker host, restrict backup-file permissions, monitor backup freshness, and perform scheduled restore drills. The current local gzip files are assessment evidence, not a production backup strategy.
- **How to verify:** Create a record through `/records`, run `backup.sh`, remove the record or recreate the database container without `--volumes`, run `restore.sh`, and confirm the record is returned by `GET /records`.

### 10. Availability, Failure Recovery, and Resource Controls

- **Risk and evidence:** A single failed backend, unbounded resource use, or a dependency that never becomes ready can cause errors or prevent the service from recovering predictably.
- **Impact:** High. Users may receive errors during a backend outage, and resource exhaustion can affect every container on the host.
- **Implemented fix / commit:** Added health checks, restart policies, `no-new-privileges`, CPU and memory limits, and `failure_test.sh`. The failure test stops `app-01`, measures unsuccessful requests while `app-02` continues serving, starts the backend again, and checks that both identities return. Related commits: `5e5cc4e` and `eea8092`.
- **Production follow-up:** Use multiple hosts, something like an AWS-managed ALB instead of 1 nginx proxy container, configure graceful draining and automatic upstream retry where appropriate, add alerting on error rate and restart loops, and test dependency and host-level failure scenarios.
- **How to verify:** Run `./failure_test.sh`, inspect the failure/recovery counts, check container health status, and confirm the recovered app returns in repeated `/instance` requests.

