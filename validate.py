#!/usr/bin/env python3
"""BARQ assessment environment validator.

Checks public access, all endpoints, all backends, PostgreSQL/Redis
readiness, network isolation, and prohibited host ports.

Usage:
    python validate.py [--url http://127.0.0.1:8080] [--project barq-assessment]

Exit codes: 0 = all pass, non-zero = one or more failures.
"""
import time
import argparse
import json
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse

_pass = 0
_fail = 0


def _result(name, ok, detail=""):
    global _pass, _fail
    tag = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {name}{suffix}")
    if ok:
        _pass += 1
    else:
        _fail += 1


def _get(url, timeout=5):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def _post(url, data, timeout=5):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def _docker_json(*args):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"docker failed")
    return json.loads(result.stdout.strip())


def _inspect(name):
    try:
        info = _docker_json("inspect", name)
        return info[0] if isinstance(info, list) and info else None
    except Exception:
        return None


def _host_bindings(info):
    """Return all host port bindings for a container."""
    ports = info.get("NetworkSettings", {}).get("Ports", {})

    return [
        binding
        for bindings in ports.values()
        if bindings
        for binding in bindings
    ]


def wait_for_readiness(base_url, timeout=60, interval=2):
    """Wait for PostgreSQL and Redis readiness with a bounded timeout."""
    print("\n=== Waiting for readiness ===")

    deadline = time.monotonic() + timeout
    last_error = "not ready yet"

    while time.monotonic() < deadline:
        try:
            status, body = _get(
                f"{base_url}/ready",
                timeout=3,
            )

            dependencies = body.get("dependencies", {})

            postgres_ready = dependencies.get("postgres") == "ready"
            redis_ready = dependencies.get("redis") == "ready"

            if status == 200 and postgres_ready and redis_ready:
                _result(
                    "Environment became ready",
                    True,
                    f"dependencies={dependencies}",
                )
                return True

            last_error = (
                f"status={status}, dependencies={dependencies}"
            )

        except Exception as exc:
            last_error = str(exc)

        time.sleep(interval)

    _result(
        "Environment became ready",
        False,
        f"timed out after {timeout}s: {last_error}",
    )

    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _discover_app_instances(project):
    """Return set of app-* container names owned by this project."""
    apps = set()
    try:
        all_names = _docker_json("ps", "-a", "--format", "{{.Names}}")
        for name in all_names.splitlines():
            if name.startswith("app-"):
                info = _inspect(name)
                label = info.get("Config", {}).get("Labels", {}).get("com.docker.compose.project", "")
                if label == project:
                    apps.add(name)
    except Exception:
        pass
    return apps or {"app-01", "app-02"}


def check_network_isolation(project):
    print("\n=== Network isolation ===")
    app01 = _inspect("app-01")
    if not app01:
        _result("Network check", False, "cannot inspect app-01")
        return

    app01_nets = app01["NetworkSettings"]["Networks"]
    frontend_net = next((n for n in app01_nets if n.endswith("frontend")), None)
    backend_net = next((n for n in app01_nets if n.endswith("backend")), None)

    _result("Frontend network exists", frontend_net is not None, f"name={frontend_net}")
    _result("Backend network exists", backend_net is not None, f"name={backend_net}")

    if not frontend_net or not backend_net:
        return

    try:
        backend_info = _docker_json("network", "inspect", backend_net)[0]
        _result("Backend network is internal",
                backend_info.get("Internal", False),
                f"internal={backend_info.get('Internal')}")
    except Exception:
        _result("Backend network is internal", False, "cannot inspect")

    app_containers = _discover_app_instances(project)
    required = {}
    for app in app_containers:
        required[app] = {"frontend", "backend"}
    required["nginx"] = {"frontend"}
    required["postgres"] = {"backend"}
    required["redis"] = {"backend"}

    for svc, expected_nets in required.items():
        info = _inspect(svc)
        if not info:
            _result(f"Container '{svc}' network membership", False, "cannot inspect")
            continue
        actual_nets = set()
        for net_name in info["NetworkSettings"]["Networks"]:
            if net_name.endswith("frontend"):
                actual_nets.add("frontend")
            if net_name.endswith("backend"):
                actual_nets.add("backend")
        _result(f"Container '{svc}' network membership",
                actual_nets == expected_nets,
                f"expected={expected_nets}, actual={actual_nets}")


def check_port_exposure(public_port):
    print("\n=== Port exposure ===")

    for name in ("postgres", "redis"):
        info = _inspect(name)
        if not info:
            _result(f"Container '{name}' port check", False, "cannot inspect")
            continue
        ports = info.get("NetworkSettings", {}).get("Ports", {})
        host_bindings = {p: b for p, b in ports.items() if b}
        _result(f"Container '{name}' has no host port mappings",
                len(host_bindings) == 0,
                f"host_ports={list(host_bindings.keys())}" if host_bindings else "no host mappings")

    # Apps must not publish any host ports.
    for name in ("app-01", "app-02"):
        info = _inspect(name)

        if not info:
            _result(
                f"Container '{name}' port check",
                False,
                "cannot inspect",
            )
            continue

        host_bindings = _host_bindings(info)

        _result(
            f"Container '{name}' has no host port mappings",
            len(host_bindings) == 0,
            (
                f"host_ports="
                f"{[b.get('HostPort') for b in host_bindings]}"
                if host_bindings
                else "no host mappings"
            ),
        )

    nginx_info = _inspect("nginx")
    if not nginx_info:
        _result("NGINX port check", False, "cannot inspect nginx")
        return

    ports = nginx_info.get("NetworkSettings", {}).get("Ports", {})
    all_bindings = [b for bindings in ports.values() for b in (bindings or [])]

    has_one_correct = (
        len(all_bindings) == 1
        and str(all_bindings[0].get("HostPort", "")) == str(public_port)
    )

    _result(
        f"NGINX publishes exactly port {public_port} on host",
        has_one_correct,
        f"host_ports={[b.get('HostPort') for b in all_bindings]}"
        if all_bindings else "no host bindings"
    )


def check_endpoints(base_url):
    print("\n=== Endpoint checks ===")

    checks = [
        ("GET /", f"{base_url}/", "service", "barq-api"),
        ("GET /health", f"{base_url}/health", "status", "alive"),
    ]

    for label, url, key, expected in checks:
        try:
            status, body = _get(url)
            _result(label, status == 200 and body.get(key) == expected,
                    f"status={status}, {key}={body.get(key)}")
        except Exception as exc:
            _result(label, False, str(exc))

    # GET /ready — postgres + redis
    try:
        status, body = _get(f"{base_url}/ready")
        deps = body.get("dependencies", {})
        all_ready = all(v == "ready" for v in deps.values())
        _result("GET /ready", status == 200 and all_ready,
                f"status={status}, deps={deps}")
    except Exception as exc:
        _result("GET /ready", False, str(exc))

    # GET /instance
    try:
        status, body = _get(f"{base_url}/instance")
        _result("GET /instance", status == 200 and body.get("instance_id", "") != "",
                f"status={status}, instance_id={body.get('instance_id')}")
    except Exception as exc:
        _result("GET /instance", False, str(exc))

    # GET /records
    try:
        status, body = _get(f"{base_url}/records")
        _result("GET /records", status == 200 and isinstance(body.get("records"), list),
                f"status={status}, count={len(body.get('records', []))}")
    except Exception as exc:
        _result("GET /records", False, str(exc))

    # POST /records
    try:
        status, body = _post(
            f"{base_url}/records",
            {"title": "validate.py test record"}
        )
        _result(
            "POST /records creates record",
            status == 201 and "id" in body.get("record", {}),
            f"status={status}, record={body.get('record')}"
        )
    except Exception as exc:
        _result("POST /records creates record", False, str(exc))

    # GET /counter
    try:
        status, body = _get(f"{base_url}/counter")
        _result(
            "GET /counter",
            status == 200 and isinstance(body.get("counter"), int),
            f"status={status}, counter={body.get('counter')}"
        )
    except Exception as exc:
        _result("GET /counter", False, str(exc))


def check_backends_serving(base_url, expected_instances, iterations=20):
    print("\n=== All backends serving ===")
    seen = set()
    errors = 0

    for _ in range(iterations):
        try:
            _, body = _get(f"{base_url}/instance", timeout=3)
            seen.add(body.get("instance_id", ""))
        except Exception:
            errors += 1

    _result(
        f"All backends served ({iterations} requests)",
        seen == expected_instances,
        f"saw={seen}, expected={expected_instances}, errors={errors}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080",
        help="Public NGINX URL (default: http://127.0.0.1:8080)"
    )

    parser.add_argument(
        "--project",
        default="barq-assessment",
        help="Docker Compose project name (default: barq-assessment)"
    )

    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    project = args.project
    parsed = urlparse(base_url)
    public_port = parsed.port or 80

    print(f"BARQ Environment Validator")
    print(f"URL: {base_url}  |  Port: {public_port}")

    # Wait for PostgreSQL and Redis before running endpoint checks.
    if not wait_for_readiness(base_url):
        sys.exit(1)

    check_network_isolation(project)
    check_port_exposure(public_port)
    check_endpoints(base_url)

    expected_instances = _discover_app_instances(project)

    _result(
        "Exactly two app instances exist",
        expected_instances == {"app-01", "app-02"},
        f"instances={sorted(expected_instances)}"
    )

    check_backends_serving(base_url, expected_instances)

    total = _pass + _fail

    print(f"\n{'='*50}")
    print(f"Results: {_pass}/{total} passed, {_fail}/{total} failed")
    print(f"{'='*50}")

    sys.exit(1 if _fail > 0 else 0)


if __name__ == "__main__":
    main()
