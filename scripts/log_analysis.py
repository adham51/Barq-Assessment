#!/usr/bin/env python3
# Goes through the three log files in logs/ and prints the numbers used to
# answer the questions in log_analysis.md. Doesn't change the original files.
#
# Rules I used:
# - a line that isn't valid JSON (or doesn't match the error.log format) = malformed, skipped
# - a line whose (request_id, timestamp) already showed up earlier in the same file = duplicate, skipped
# - a "retry" is one access.log line where upstream has a comma in it (two attempts, one request)

import json
import re
import statistics

access_lines = open("logs/access.log", encoding="utf-8").readlines()
app_lines = open("logs/application.log", encoding="utf-8").readlines()
error_lines = open("logs/error.log", encoding="utf-8").readlines()

# regex for error.log lines, e.g.:
# 2026/08/20 11:05:02 [error] 31#31: *122 connect() failed (111: Connection refused)
# while connecting to upstream, request_id=lab-000122, request: "GET /health HTTP/1.1",
# upstream: "http://172.23.0.12:8080/health"
error_pattern = re.compile(
    r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[\w+\] \d+#\d+: \*\d+\s+(.*?), '
    r'request_id=(lab-\d+),\s+request: "([^"]*)", upstream: "([^"]*)"'
)

print("=" * 70)
print("Q1 - reading each file and counting valid / malformed / duplicate lines")
print("=" * 70)

# access.log is JSON, one request per line. Try to parse each line; if it
# fails, it's malformed. If we've already seen the same (request_id,
# timestamp) pair, it's a duplicate line, not a second request.
access_records = []
access_malformed = []
access_duplicates = 0
seen_access = set()
for line in access_lines:
    line = line.strip()
    if line == "":
        continue
    try:
        record = json.loads(line)
    except Exception:
        access_malformed.append(line)
        continue
    key = (record["request_id"], record["timestamp"])
    if key in seen_access:
        access_duplicates += 1
        continue
    seen_access.add(key)
    access_records.append(record)

# application.log is also JSON, but each line can be either a normal
# "http_request" event or a "dependency_error" event (used later in Q7).
# Same parse/dedupe logic as access.log.
app_records = []
app_malformed = []
app_duplicates = 0
seen_app = set()
for line in app_lines:
    line = line.strip()
    if line == "":
        continue
    try:
        record = json.loads(line)
    except Exception:
        app_malformed.append(line)
        continue
    key = (record["request_id"], record["timestamp"])
    if key in seen_app:
        app_duplicates += 1
        continue
    seen_app.add(key)
    app_records.append(record)

# error.log is plain NGINX text, not JSON, so it needs the regex above
# instead of json.loads. A line that doesn't match the regex (like the
# "[notice] ... log collector rotated stream" line) is malformed.
error_records = []
error_malformed = []
error_duplicates = 0
seen_error = set()
for line in error_lines:
    line = line.strip()
    if line == "":
        continue
    match = error_pattern.match(line)
    if not match:
        error_malformed.append(line)
        continue
    date_str, message, request_id, request_line, upstream = match.groups()
    key = (request_id, date_str)
    if key in seen_error:
        error_duplicates += 1
        continue
    seen_error.add(key)
    error_records.append({
        "date": date_str,
        "message": message,
        "request_id": request_id,
        "request": request_line,
        "upstream": upstream,
    })

print("access.log:      valid=%d  malformed=%d  duplicates=%d" % (len(access_records), len(access_malformed), access_duplicates))
print("  malformed line(s):", access_malformed)
print("application.log: valid=%d  malformed=%d  duplicates=%d" % (len(app_records), len(app_malformed), app_duplicates))
print("  malformed line(s):", app_malformed)
print("error.log:       valid=%d  malformed=%d  duplicates=%d" % (len(error_records), len(error_malformed), error_duplicates))
print("  malformed line(s):", error_malformed)

timestamps = [r["timestamp"] for r in access_records]
print("interval covered (access.log):", min(timestamps), "to", max(timestamps))


print()
print("=" * 70)
print("Q2 - distinct client requests")
print("=" * 70)

# A set() only keeps unique values, so this counts distinct request_ids
# straight from the already-deduplicated access_records.
request_ids = set()
for r in access_records:
    request_ids.add(r["request_id"])
print("distinct request_ids in access.log:", len(request_ids))
print("(a retry is one line with a comma in 'upstream', so it's already one request, not two)")


print()
print("=" * 70)
print("Q3 - final status counts and error rate")
print("=" * 70)

# Tally how many requests ended on each status code.
status_counts = {}
for r in access_records:
    status = r["status"]
    status_counts[status] = status_counts.get(status, 0) + 1

for status in sorted(status_counts):
    print(status, ":", status_counts[status])

# denominator = every request the client got a final answer for
total_requests = len(access_records)
error_count = 0
for status, count in status_counts.items():
    if status >= 400:
        error_count += count

print("denominator (all requests):", total_requests)
print("errors (status >= 400):", error_count)
print("error rate:", round(100 * error_count / total_requests, 2), "%")

# the 404s are all deliberate probes to /missing, not real failures, so also
# show the rate without them for a more honest picture
errors_without_404 = error_count - status_counts.get(404, 0)
print("error rate excluding the /missing 404 probes:", round(100 * errors_without_404 / total_requests, 2), "%")


print()
print("=" * 70)
print("Q4 - which paths / minutes / backends had the failures")
print("=" * 70)

failed_requests = []
for r in access_records:
    if r["status"] >= 400:
        failed_requests.append(r)

# group failures by which endpoint they hit
path_counts = {}
for r in failed_requests:
    path_counts[r["path"]] = path_counts.get(r["path"], 0) + 1
print("failures by path:", path_counts)

# group failures by minute, to see if they cluster into specific windows
errors_by_minute = {}
for r in failed_requests:
    minute = r["timestamp"][11:16]  # e.g. "11:05" out of "2026-08-20T11:05:02.503Z"
    errors_by_minute[minute] = errors_by_minute.get(minute, 0) + 1
print("failures by minute:")
for minute in sorted(errors_by_minute):
    print(" ", minute, errors_by_minute[minute])

# which upstream was tried first for each failed request (upstream can be a
# comma-separated list if NGINX retried, so take only the first attempt)
backend_counts = {}
for r in failed_requests:
    first_upstream = r["upstream"].split(",")[0].strip()
    backend_counts[first_upstream] = backend_counts.get(first_upstream, 0) + 1
print("failed requests by first-tried backend:", backend_counts)


print()
print("=" * 70)
print("Q5 - client latencies (request_time is in seconds)")
print("=" * 70)

# request_time in the log is in seconds, so multiply by 1000 to get ms.
# Percentiles need the values sorted first.
latencies_ms = []
for r in access_records:
    latencies_ms.append(r["request_time"] * 1000)
latencies_ms.sort()

median_latency = statistics.median(latencies_ms)


def nearest_rank_percentile(sorted_values, percentile):
    # nearest-rank method: sort ascending, take the value at position ceil(p/100 * n)
    rank = int(round(percentile / 100 * len(sorted_values) + 0.5))
    if rank < 1:
        rank = 1
    return sorted_values[rank - 1]


p95 = nearest_rank_percentile(latencies_ms, 95)
print("median:", round(median_latency, 1), "ms")
print("p95:", round(p95, 1), "ms")
print("(method: nearest-rank percentile on sorted request_time, converted seconds -> ms)")


print()
print("=" * 70)
print("Q6 - retried requests")
print("=" * 70)

# A retry shows up as one access.log line where "upstream" has more than one
# value separated by commas (first attempt failed, NGINX tried the next one).
retried_requests = []
for r in access_records:
    attempts = r["upstream"].split(",")
    if len(attempts) > 1:
        retried_requests.append(r)

succeeded_after_retry = 0
for r in retried_requests:
    if r["status"] == 200:
        succeeded_after_retry += 1

print("requests with more than one upstream attempt:", len(retried_requests))
print("of those, ended in a final 200:", succeeded_after_retry)
for r in retried_requests[:3]:
    print("  example:", r["request_id"], r["path"], r["upstream"], "-> final status", r["status"])


print()
print("=" * 70)
print("Q7 - dependency errors in application.log (this is where I had it wrong before)")
print("=" * 70)

# pull out just the dependency_error events (application.log also has
# http_request events mixed in, which we ignore here)
dependency_errors = []
for r in app_records:
    if r.get("event") == "dependency_error":
        dependency_errors.append(r)

# IMPORTANT: don't lump these together, they are two different problems
# (redis timeouts and postgres auth failures happen at different times for
# different reasons, see log_analysis.md Q7)
by_dependency = {}
for r in dependency_errors:
    dep = r.get("dependency")
    by_dependency[dep] = by_dependency.get(dep, 0) + 1
print("dependency_error events by dependency:", by_dependency)

by_dependency_minute = {}
for r in dependency_errors:
    dep = r.get("dependency")
    minute = r["timestamp"][11:16]
    by_dependency_minute.setdefault(dep, {})
    by_dependency_minute[dep][minute] = by_dependency_minute[dep].get(minute, 0) + 1
for dep in by_dependency_minute:
    print(" ", dep, "by minute:", by_dependency_minute[dep])


print()
print("=" * 70)
print("Q8 - a couple of correlated requests (same request_id across files)")
print("=" * 70)

# build a quick lookup so we can find the application.log record for a given request_id
app_by_request_id = {}
for r in app_records:
    if r.get("event") == "http_request":
        app_by_request_id[r["request_id"]] = r

# find one 502 that never made it to the app (proves it's a proxy-level
# failure, not an application bug) and show its matching error.log line
for r in access_records:
    if r["status"] == 502 and r["request_id"] not in app_by_request_id:
        print("FAILED example:", r["request_id"], r["timestamp"], r["path"], "status", r["status"])
        for e in error_records:
            if e["request_id"] == r["request_id"]:
                print("  matching error.log line:", e["message"])
        print("  application.log: nothing (request never reached the app)")
        break

# find one normal 200 and show it lines up across both logs
for r in access_records:
    if r["status"] == 200 and r["request_id"] in app_by_request_id:
        app_r = app_by_request_id[r["request_id"]]
        print("SUCCESS example:", r["request_id"], r["timestamp"], r["path"], "status", r["status"])
        print("  application.log:", app_r["instance_id"], "status", app_r["status"], "duration_ms", app_r["duration_ms"])
        break


print()
print("=" * 70)
print("Q9 - proxy/connectivity errors vs dependency/application errors")
print("=" * 70)

# The idea: a proxy/connectivity failure never reaches the app (no
# application.log entry), while a dependency/application failure does reach
# the app and shows up there as a dependency_error, not in error.log at all.
error_log_request_ids = set()
for e in error_records:
    error_log_request_ids.add(e["request_id"])

proxy_like = []  # 502/504 with no matching application.log entry
for r in access_records:
    if r["status"] in (502, 504) and r["request_id"] not in app_by_request_id:
        proxy_like.append(r)

app_like = []  # 503 that also has a dependency_error in application.log
dependency_error_ids = set()
for r in dependency_errors:
    dependency_error_ids.add(r["request_id"])
for r in access_records:
    if r["status"] == 503 and r["request_id"] in dependency_error_ids:
        app_like.append(r)

print("502/504 with no application.log entry at all (proxy/connectivity):", len(proxy_like))
print("503 with a matching dependency_error event (dependency/application):", len(app_like))
still_in_error_log = 0
for r in access_records:
    if r["status"] == 503 and r["request_id"] in error_log_request_ids:
        still_in_error_log += 1
print("503s that also show up in error.log (should be ~0):", still_in_error_log)


print()
print("=" * 70)
print("Q10 - what this doesn't prove")
print("=" * 70)
print("These logs only show what NGINX/the app logged for 30 minutes. They don't show:")
print("- why the backend actually stopped accepting connections (no container/OS logs here)")
print("- why redis timed out or why postgres rejected the password (no DB/redis-side logs)")
print("- whether 172.23.0.11/.12 map to the same containers today (inferred from this data only)")
