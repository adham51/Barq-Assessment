# Troubleshooting journal

Keep chronological entries. Copy this block for each meaningful investigation.

## Entry / date / time
- Symptom:
- Hypothesis:
- Command or test:
- Actual output:
- Failed attempt and what changed your thinking:
- Root cause:
- Fix:
- Retest evidence:
- Related commit:
- Remaining uncertainty:

Do not fabricate a failed attempt just to fill the template. Record actual attempts.

## Entry 1: Healthcheck error and instance ID mismatch — 2026-09-10 1:30 (egypt time)

- **Symptom**:
  Ran docker compose up. Containers started, but both app-01 and app-02 logged repeated GET /healthz HTTP/1.1 404 warnings every 5 seconds. Additionally, docker compose ps showed both application containers marked as (unhealthy).

- **Hypothesis**:
  Error 404 made me think requested resource or path doesn't exist leading to unhealthy status so decided to look at each container alone for clearer problem isolation.

- **Command or test**:
  ```bash
  docker compose -p barq-assessment logs --no-color
  docker compose -p barq-assessment ps -a
  docker compose logs app-01 --tail=20
  docker compose logs app-02 --tail=20
  ```

- **Actual output**:
  ps -a showed containers running in an unhealthy state:
  ```text
  NAME       IMAGE                                                                                        COMMAND                  SERVICE    CREATED         STATUS                     PORTS
  app-01     barq-assessment-app-01                                                                       "python -m app.server"   app-01     5 minutes ago   Up 5 minutes (unhealthy)   8080/tcp
  app-02     barq-assessment-app-02                                                                       "python -m app.server"   app-02     5 minutes ago   Up 5 minutes (unhealthy)   8080/tcp
  nginx      nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236    "/docker-entrypoint.…"   nginx      5 minutes ago   Up 5 minutes               127.0.0.1:8080->81/tcp
  postgres   postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685   "docker-entrypoint.s…"   postgres   5 minutes ago   Up 5 minutes (healthy)     5432/tcp
  redis      redis:7.4-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf     "docker-entrypoint.s…"   redis      5 minutes ago   Up 5 minutes (healthy)     6379/tcp

  ```
  Container logs revealed repeated 404 failures and duplicate instance identifiers:
  ```text
  app-01 | {"timestamp": "2026-09-10T11:42:54.074Z", "level": "WARN", "service": "barq-api", "instance_id": "app-01", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.525}
  app-02 | {"timestamp": "2026-09-10T11:42:54.074Z", "level": "WARN", "service": "barq-api", "instance_id": "app-01", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.099}

  ```
- **Failed attempt and what changed your thinking**:
  Initially suspected that the Python applications were crashing or failing to start due to network/database issues. However, the logs confirmed that the server was actively handling HTTP traffic, just returning 404 on /healthz. Checking server.py confirmed that the application route was defined as /health, not /healthz. While examining app-02 logs, also noticed that instance_id was reporting as "app-01". Checking docker-compose.yml revealed app-02 was hardcoded to INSTANCE_ID: "app-01".

- **Root cause**:
  1. Healthcheck probes /healthz but Flask only implements /health
  2. app-02 INSTANCE_ID set to "app-01" instead of "app-02" in app-02 service

- **Fix**:
  ```yaml
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

  app-02:
    environment:
      INSTANCE_ID: "app-02"
  ```

- **Retest evidence**:
  ```bash
  docker compose down
  docker compose -p barq-assessment up --build -d
  docker compose -p barq-assessment ps
  docker compose logs app-01 --tail=20
  docker compose logs app-02 --tail=20
  ```

- **Related commit**:
  `Fix: healthcheck path and app-02 instance ID`

- **Remaining uncertainty**:
  None. Both issues resolved and verified via docker compose ps health status and container logs.

## Entry 2: NGINX and Flask connectivity - 2026-09-10 6:05 pm

- **Symptom**: The original host request failed because Compose mapped host port `8080`
  to NGINX port `81`, while NGINX listened on port `80`.

- **Hypothesis**: The public request was reaching the wrong NGINX container port.

- **Command or test**:
  ```bash
  curl -i http://127.0.0.1:8080/
  docker port nginx
  docker exec nginx nginx -T
  ```

- **Initial evidence**:
  ```text
  curl -i http://127.0.0.1:8080/
  curl: (56) Recv failure: Connection reset by peer
  ```
  This meant the TCP connection was closed before `curl` received an HTTP response. It
  did not mean that Flask had returned an application error. I checked the published
  port and loaded NGINX configuration to identify where the connection stopped:
  ```text
  docker port nginx
  81/tcp -> 127.0.0.1:8080
  nginx: listen 80;
  ```
  The host port was forwarded to container port `81`, but NGINX listened on `80`, so the
  request was sent to the wrong container port and did not reach the configured NGINX
  server.

- **Actual output**: After correcting the mapping to `8080:80`, the request returned
  `HTTP/1.1 502 Bad Gateway`.

- **Investigation**: After changing the mapping to `8080:80`, the request returned:
  ```text
  HTTP/1.1 502 Bad Gateway
  ```
  This proved the request now reached NGINX. NGINX logged:
  ```text
  connect() failed (111: Connection refused) while connecting to upstream
  upstream: "http://172.19.0.2:8080/health"
  ```
  A direct request from the NGINX container produced:
  ```text
  curl: (7) Failed to connect to app-01 port 8080 after 12 ms: Could not connect to server
  ```
  Meanwhile, the app logs showed local `/health` requests returning `200`. This separated
  the two issues: NGINX was now receiving traffic, but Flask was not accepting connections
  through the Docker network.

- **Failed attempt and what changed your thinking**: The initial port mapping did not
  produce an HTTP response. Correcting it changed the result to a clear NGINX `502`, which
  showed that the request was reaching NGINX and that the remaining failure was upstream.

- **Root cause**: Flask listened on `127.0.0.1`, which is reachable only inside the app
  container. NGINX connects through the Docker network.

- **Fix**:
  ```yaml
  # docker-compose.yml
  APP_HOST: "0.0.0.0"
  ports:
    - "127.0.0.1:${PUBLIC_PORT:-8080}:80"
  ```
  ```nginx
  # nginx/nginx.conf
  server app-01:8080 max_fails=0;
  server app-02:8080 max_fails=0;
  ```

**Retest evidence**:

 ### 1. Container Health & Port Mapping Verification
  docker compose ps  

  Showed healthy containers and correct port mappings  


### 2. Internal Container-to-Container Routing (Nginx to App )
  $ docker compose -p barq-assessment exec nginx curl -i http://app-01:8080/health
  HTTP/1.1 200 OK (X-Instance-ID: app-01)

  $ docker compose -p barq-assessment exec nginx curl -i http://app-02:8080/health  

  HTTP/1.1 200 OK (X-Instance-ID: app-02)

  ### 3. External Host test

  curl -i http://127.0.0.1:8080/health: HTTP/1.1 200 OK  
  curl -i http://127.0.0.1:8080/: HTTP/1.1 200 OK


  ### 4. Upstream Round-Robin Load Balancing Distribution
  for i in $(seq 1 20);  
  do curl -s http://127.0.0.1:8080/instance  
  done

    {"instance_id":"app-01","service":"barq-api","status":"ok""version":"2.0.0"}
    {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
    {"instance_id":"app-01","service":"barq-api","status":"ok","version":"2.0.0"}
    {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}

  The public requests succeeded through NGINX, and the direct request from inside the
  NGINX container succeeded through the Docker network to `app-01`.

- **Related commit**: Proposed message: `Fix NGINX and Flask connectivity`.

- **Remaining uncertainty**: This retest confirms the NGINX-to-Flask request path only.
  Now I'll check any port misconfigurations in DB and ensure security

## Entry 3: Database and Redis ports - 2026-09-10 7:40 pm

- **Symptom**: `/ready`, `/records`, and `/counter` returned `503`, although PostgreSQL
  and Redis containers were running.

- **Hypothesis**: The application was using ports different from the ports exposed by
  the PostgreSQL and Redis services.

- **Command or test**:
  ```bash
  curl -i http://127.0.0.1:8080/health
  curl -i http://127.0.0.1:8080/ready
  curl -i http://127.0.0.1:8080/records
  curl -i http://127.0.0.1:8080/counter
  ```

- **Investigation**:

  Before the fix, the API tests showed:
  ```bash
  curl -i http://127.0.0.1:8080/health
  # HTTP/1.1 200 OK

  curl -i http://127.0.0.1:8080/ready
  # HTTP/1.1 503 SERVICE UNAVAILABLE
  # postgres=unavailable, redis=unavailable

  curl -i http://127.0.0.1:8080/records
  # HTTP/1.1 503 SERVICE UNAVAILABLE
  # {"error":"postgres_unavailable"}

  curl -i http://127.0.0.1:8080/counter
  # HTTP/1.1 503 SERVICE UNAVAILABLE
  # {"error":"redis_unavailable"}
  ```

- **Actual output**: `/health` returned `200`, but the dependency endpoints returned
  `503` for PostgreSQL and Redis. PostgreSQL on `5432` and Redis on `6379` were reachable.

- **Failed attempt and what changed your thinking**: The initial endpoint tests failed
  even though both containers were running. Testing the service ports separately showed
  that the configured ports were wrong, rather than the services being stopped.

- **Root cause**: `config/app.env` used `5433` for PostgreSQL and `6380` for Redis,
  while the services listened on `5432` and `6379` inside the Docker network.

- **Fix**: Changed the URLs in `config/app.env` to use `postgres:5432` and `redis:6379`.
  Rebuilt the two app containers with:
  ```bash
  docker compose -p barq-assessment up --build -d app-01 app-02
  ```

- **Retest evidence**:
  ```text
  curl -i http://127.0.0.1:8080/ready
  HTTP/1.1 200 OK
  {"dependencies":{"postgres":"ready","redis":"ready"},"status":"ready"}

  curl -i http://127.0.0.1:8080/records
  HTTP/1.1 200 OK
  {"records":[...]}

  curl -i -H 'Content-Type: application/json' \
    -d '{"title":"Database connectivity proof"}' \
    http://127.0.0.1:8080/records
  HTTP/1.1 201 CREATED
  {"record":{"id":3,"title":"Database connectivity proof"}}

  curl -i http://127.0.0.1:8080/counter
  HTTP/1.1 200 OK
  {"counter":1}
  ```

- **Related commit**: `Fix: database and Redis connectivity`.

- **Remaining uncertainty**: Security issues, Database persistence, backup and restore scripts
