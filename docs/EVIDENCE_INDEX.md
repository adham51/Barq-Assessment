# Evidence and submission index

- Repository URL: https://github.com/adham51/Barq-Assessment
- Final commit: `1be1707` (`fixed .env.example so CI doesn't fail and changed readiness check to match port 8090`)
- Matching CI run: https://github.com/adham51/Barq-Assessment/actions/runs/34793993734
- Continuous video URL: https://drive.google.com/file/d/1IoK2CbDiC3nL18Iu73jk0m9wLL9FPU9N/view?usp=sharing
  - Note: video is ~22 minutes, 4 minutes over the brief's 12-18 minute target. Reason: commands
    were typed live on camera, not pasted, per the "no cuts/speed-up" requirement, introduction was a bit long - my apologies.
- Challenge receipt ID: `8bf2ac11497540fabdde09bff3283a07` 
- Starting video commit: `bc52058` ("Update architecture diagram and README for final 3-instance apps")
- Later documentation-only commits:
  - `c39be87` — edited validation script in CI to use port 8090 and 3 instances instead of 2
  - `1be1707` — fixed `.env.example` so CI doesn't fail; changed readiness check to match port 8090
  - (plus this pending commit: README DevSecOps section, CI outcome screenshot, this evidence index)


## Requirement -> file/output -> commit -> video timestamp

| Requirement | Video timestamp |
|---|---|
| Starting repo state, clean git status | 1:40 |
| Architecture diagram overview | 3:50 |
| Build/start, service health, endpoint tests (`/`, `/health`, `/ready`, `/records`, `/counter`) | 4:00 |
| Persistence record created | 6:15 |
| Both backends served via NGINX (`/instance`) | 6:36 |
| Backend stopped, continued traffic/errors, recovery | 7:23 |
| Record survives app + Postgres recreation | 8:20 |
| Validation + failure test run | 8:37 |
| One historical-log finding demonstrated | 9:40 |
| `video_challenge.sh` run once, fault diagnosed & fixed | 11:55 |
| Port 8080 → 8090 live | 14:55 |
| Third instance added live, all three respond | 16:00 |
| `git status`/`git diff` shown, commit on screen, push | 16:00–21:00 |
| Revalidation on 8090/3 instances (done in CI, not live — forgot to re-run validate.py live) | n/a (post-video, in CI) |
