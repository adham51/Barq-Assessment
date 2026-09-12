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
  * **For `backup.sh` and `restore.sh`:** 
    * The AI initially provided overly complex scripts that relied on unnecessary environment variables and the `pg_dump -Fc` format. 
    * I disregarded much of this and wrote simpler logic using plain SQL. 
    * I added UTC timestamps to the filenames, implemented `gzip` compression to save space, and added a 7-day retention rotation (`find ... -mtime +7 -delete`) to ensure strict resource efficiency. I also set up a cronjob to automate this process.
  * **For `validate.py`:** I told the AI to fix several clear flaws in its validation logic:
    * **Fake Network Checks:** The AI originally wrote a network check that always returned `PASS`. For example, if `app-02` was disconnected from the frontend network (Scenario A), or if `redis` was disconnected from the backend network (Scenario B), the script still passed. I told the AI to remove this fake check and rely entirely on strict network isolation checks that actually verify membership.
    * **Hardcoded Ports:** The AI hardcoded the validation port to `8080`. I asked it to dynamically parse the target port from the `--url` argument instead, so that when I switch the port to `8090` live during the video demonstration, the validator checks the correct port without failing.
    * **Fragile Port Scanning:** The AI tried to check for exposed ports (like 5432 for Postgres) using a basic localhost socket check. I pointed out this wouldn't catch ports mapped to different numbers by Docker (e.g., `15432:5432`). I told it to parse `NetworkSettings.Ports` via `docker inspect` for strict accuracy.
    * **App Discovery:** The AI was just looking for any container starting with `app-`, which would accidentally include stray containers from old projects. I told it to filter using the `com.docker.compose.project` label.
    * **Over-engineering:** I had the AI remove about 100 lines of unrequested checks (like checking if the Docker daemon was reachable) to keep the script focused only on the assignment's requirements.
* **Verified:** Executed full end-to-end backup/restore cycles confirming the UTC timestamps, compression, and data survival. I manually tested `validate.py` against edge cases (like testing port `8090`, testing network disconnections, and introducing fake external containers) to ensure it fails exactly when it should.


### 2- **Tool/model:** Claude (Free version)
- **Purpose:** Generating the initial draft of the `failure_test.sh` script to test load balancing, failure handling, and round-robin recovery.
- **Files or decisions affected:** `failure_test.sh`
- **What you changed or rejected:** I rejected Claude's initial approach, which stayed idle/silent while waiting for the tested backend app to come back online and didn't properly show the errors. I introduced the idea of a continuous loop that actively hits the `/instance` endpoint during the downtime and recovery phases, logging the raw outputs as they happen instead of hiding them. 
- **How you independently verified it:** I executed `./failure_test.sh` locally and analyzed the terminal output. Unlike the previous version which didn't print anything during the waiting phase, my version successfully demonstrated the traffic routing, dropped requests, and the exact moment `app-01` came back online. 

  **Sample output from my version proving it works:**
  ```text
  adham@DESKTOP-1RF0NOI:/mnt/d/HomeLab & Personal Projects/BARQ-ACADEMY-TASK/barq-academy$ ./failure_test.sh
  stopping app-01
  hitting [http://127.0.0.1:8080/instance](http://127.0.0.1:8080/instance) 10x while it's down
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
  hitting [http://127.0.0.1:8080/instance](http://127.0.0.1:8080/instance) 20x, printing raw responses to prove round robin
  {"instance_id":"app-01","service":"barq-api","status":"ok","version":"2.0.0"}
  {"instance_id":"app-02","service":"barq-api","status":"ok","version":"2.0.0"}
  {"instance_id":"app-01","service":"barq-api","status":"ok","version":"2.0.0"}

  PASS: both backends serving again


### 2- **Tool/model:** VS Code Copilot chat (free plan)

* **Purpose:** Documentation formatting and structural cleanup.
* **Files affected:** `troubleshooting.md`, `decisions.md`, `AI_USAGE.md`
* **What I changed/rejected:** I strictly used it to format my raw notes into readable markdown. I ignored its attempts to suggest code and threw out the clunky markdown tables it generated, opting for simpler documentation. 
* **Verified:** Read through all the generated documentation to ensure the technical explanations and engineering decisions were entirely how I did it on my own.
