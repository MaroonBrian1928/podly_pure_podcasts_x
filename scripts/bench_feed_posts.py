#!/usr/bin/env python3
"""Benchmark /api/feeds/<id>/posts: latency + RSS delta over N requests.

Run twice to compare paths:
    PODLY_RUST_FEED_POSTS_ENABLED=false  → restart container → ./scripts/bench_feed_posts.py ...
    PODLY_RUST_FEED_POSTS_ENABLED=true   → restart container → ./scripts/bench_feed_posts.py ...

The script does not flip the flag itself; that requires a container restart
which the operator should do between runs so the steady-state RSS is clean.

Usage:
    ./scripts/bench_feed_posts.py --url https://podly.example.com/api/feeds/6/posts \\
        --count 50 --concurrency 8 --container podly-pure-podcasts \\
        --login-env-file .env.local
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def read_container_rss(container: str) -> int | None:
    """Sum RSS (kB) across all python3 processes in the container.

    Returns None when docker isn't available or the container can't be queried,
    so the script can still run latency-only benchmarks against a remote host.
    """
    try:
        out = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "sh",
                "-c",
                "for p in /proc/[0-9]*; do "
                "  pid=${p##*/}; "
                "  [ -r $p/status ] || continue; "
                '  cmd=$(tr "\\0" " " < $p/cmdline); '
                '  case "$cmd" in *python3*) '
                '    awk "/VmRSS/{print \\$2}" $p/status;; '
                "  esac; "
                "done",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None

    total = 0
    for raw_line in out.stdout.splitlines():
        stripped = raw_line.strip()
        if stripped.isdigit():
            total += int(stripped)
    return total or None


def hit(url: str, cookie: str | None) -> tuple[float, int, int]:
    """Return (latency_seconds, status_code, body_length)."""
    req = urllib.request.Request(url, method="GET")
    if cookie:
        req.add_header("Cookie", cookie)

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        status = exc.code
    elapsed = time.perf_counter() - started
    return elapsed, status, len(body)


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def login_cookie_from_env_file(url: str, env_file: Path) -> str:
    values = read_env_file(env_file)
    username = values["PODLY_ADMIN_USERNAME"]
    password = values["PODLY_ADMIN_PASSWORD"]

    parsed = urllib.parse.urlsplit(url)
    base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    body = json.dumps({"username": username, "password": password}).encode()
    request = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.open(request, timeout=30).read()
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)


def hit_many(
    *, url: str, cookie: str | None, count: int, concurrency: int
) -> tuple[list[float], list[int], list[int]]:
    latencies: list[float] = []
    statuses: list[int] = []
    body_sizes: list[int] = []

    if concurrency <= 1:
        for _ in range(count):
            elapsed, status, size = hit(url, cookie)
            latencies.append(elapsed)
            statuses.append(status)
            body_sizes.append(size)
        return latencies, statuses, body_sizes

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(hit, url, cookie) for _ in range(count)]
        for future in concurrent.futures.as_completed(futures):
            elapsed, status, size = future.result()
            latencies.append(elapsed)
            statuses.append(status)
            body_sizes.append(size)

    return latencies, statuses, body_sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", required=True, help="Full URL to /api/feeds/<id>/posts"
    )
    parser.add_argument("--count", type=int, default=50, help="Requests to fire")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent worker threads to use for measured requests",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Pre-flight requests excluded from stats and from RSS-delta math",
    )
    parser.add_argument(
        "--container",
        default=os.environ.get("PODLY_CONTAINER_NAME", "podly-pure-podcasts"),
        help="Docker container to read RSS from; omit RSS metrics if absent",
    )
    parser.add_argument(
        "--cookie", default=None, help="Optional Cookie header for auth"
    )
    parser.add_argument(
        "--login-env-file",
        type=Path,
        default=None,
        help="Optional .env file containing PODLY_ADMIN_USERNAME/PODLY_ADMIN_PASSWORD",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()
    cookie = args.cookie
    if cookie is None and args.login_env_file is not None:
        cookie = login_cookie_from_env_file(args.url, args.login_env_file)

    label = (
        "rust"
        if os.environ.get("PODLY_RUST_FEED_POSTS_ENABLED", "").lower()
        in {"1", "true", "yes", "on"}
        else "python"
    )

    for _ in range(args.warmup):
        hit(args.url, cookie)

    rss_before_kb = read_container_rss(args.container)

    concurrency = max(1, args.concurrency)
    latencies, statuses, body_sizes = hit_many(
        url=args.url,
        cookie=cookie,
        count=args.count,
        concurrency=concurrency,
    )

    rss_after_kb = read_container_rss(args.container)

    quantile = statistics.quantiles(latencies, n=100, method="inclusive")
    result: dict[str, object] = {
        "label_from_env": label,
        "url": args.url,
        "count": args.count,
        "concurrency": concurrency,
        "status_codes": dict(
            sorted({code: statuses.count(code) for code in set(statuses)}.items())
        ),
        "body_size_bytes_mean": int(statistics.fmean(body_sizes)),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies) * 1000, 2),
            "median": round(statistics.median(latencies) * 1000, 2),
            "p95": round(quantile[94] * 1000, 2),
            "p99": round(quantile[98] * 1000, 2),
            "max": round(max(latencies) * 1000, 2),
        },
    }
    if rss_before_kb is not None and rss_after_kb is not None:
        result["rss_kb"] = {
            "before": rss_before_kb,
            "after": rss_after_kb,
            "delta": rss_after_kb - rss_before_kb,
            "per_request_kb": round((rss_after_kb - rss_before_kb) / args.count, 2),
        }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[{label}] {args.url}")
        print(
            f"  requests:    {args.count} at c={concurrency} "
            f"(after {args.warmup} warmup)"
        )
        print(f"  status:      {result['status_codes']}")
        print(f"  body bytes:  mean={result['body_size_bytes_mean']}")
        lat = result["latency_ms"]
        print(
            f"  latency ms:  mean={lat['mean']}  p50={lat['median']}  "
            f"p95={lat['p95']}  p99={lat['p99']}  max={lat['max']}"
        )
        rss = result.get("rss_kb")
        if rss is not None:
            print(
                f"  python RSS:  {rss['before']} kB → {rss['after']} kB  "
                f"(Δ {rss['delta']} kB, {rss['per_request_kb']} kB / request)"
            )
        else:
            print("  python RSS:  unavailable (docker exec failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
