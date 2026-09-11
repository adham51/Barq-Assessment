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

    Commit: `<commit-hash>`

* **Production improvement:** Configure an explicit AOF `fsync` policy based on the required durability, monitor Redis disk usage and persistence health, and evaluate moving business-critical counter state to PostgreSQL or another durable datastore if the application grows.

  `fsync` forces the OS to write buffered data to disk. With Redis AOF:
    - `appendfsync always` — writes to disk after **every write**; safest, but slowest.
    - `appendfsync everysec` — writes roughly **every second**; good balance.
    - `appendfsync no` — lets the OS decide when to write; fastest, but potentially more data loss.

