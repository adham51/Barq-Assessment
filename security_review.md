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
