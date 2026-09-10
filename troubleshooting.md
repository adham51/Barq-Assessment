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

## Entry 1: Healthcheck error and instance ID mismatch — 2026-09-10 11:40

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
NAME       IMAGE                                                                                        COMMAND                  SERVICE    CREATED         STATUS                     PORTS
app-01     barq-assessment-app-01                                                                       "python -m app.server"   app-01     5 minutes ago   Up 5 minutes (unhealthy)   8080/tcp
app-02     barq-assessment-app-02                                                                       "python -m app.server"   app-02     5 minutes ago   Up 5 minutes (unhealthy)   8080/tcp
nginx      nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236    "/docker-entrypoint.…"   nginx      5 minutes ago   Up 5 minutes               127.0.0.1:8080->81/tcp
postgres   postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685   "docker-entrypoint.s…"   postgres   5 minutes ago   Up 5 minutes (healthy)     5432/tcp
redis      redis:7.4-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf     "docker-entrypoint.s…"   redis      5 minutes ago   Up 5 minutes (healthy)     6379/tcp

Container logs revealed repeated 404 failures and duplicate instance identifiers:
app-01 | {"timestamp": "2026-09-10T11:42:54.074Z", "level": "WARN", "service": "barq-api", "instance_id": "app-01", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.525}
app-02 | {"timestamp": "2026-09-10T11:42:54.074Z", "level": "WARN", "service": "barq-api", "instance_id": "app-01", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.099}

**Failed attempt and what changed your thinking**: 
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
