#!/usr/bin/env python3
"""Benchmark a Podly image in fresh synthetic containers for migration gates."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime as dt
import hashlib
import http.cookiejar
import json
import math
import os
import shutil
import sqlite3
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.writer_parity_fixtures import export_writer_parity_instance

RUST_FLAGS = (
    "PODLY_RUST_AD_MERGE_ENABLED",
    "PODLY_RUST_AUDIO_ENABLED",
    "PODLY_RUST_CHAPTERS_ENABLED",
    "PODLY_RUST_CHAPTER_FALLBACK_ENABLED",
    "PODLY_RUST_COSTS_ENABLED",
    "PODLY_RUST_FEED_POSTS_ENABLED",
    "PODLY_RUST_FEED_REFRESH_ENABLED",
    "PODLY_RUST_FEED_XML_ENABLED",
    "PODLY_RUST_JOBS_ENABLED",
    "PODLY_RUST_PROFANITY_ENABLED",
    "PODLY_RUST_STATS_ENABLED",
    "PODLY_RUST_TRANSCRIPT_ENABLED",
    "PODLY_RUST_WORD_BOUNDARY_ENABLED",
)


@dataclass(frozen=True)
class HttpSample:
    latency_ms: float
    status: int
    body_bytes: int


def _run(
    args: list[str], *, timeout: float = 120, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, check=check, timeout=timeout
    )


def parse_size_bytes(value: str) -> int:
    units = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
    }
    stripped = value.strip()
    for unit in sorted(units, key=len, reverse=True):
        if stripped.endswith(unit):
            return round(float(stripped[: -len(unit)].strip()) * units[unit])
    raise ValueError(f"unsupported size: {value}")


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {key: math.nan for key in ("p50", "p95", "p99", "max")}
    if len(values) == 1:
        only = round(values[0], 3)
        return {key: only for key in ("p50", "p95", "p99", "max")}
    percentile = statistics.quantiles(values, n=100, method="inclusive")
    return {
        "p50": round(statistics.median(values), 3),
        "p95": round(percentile[94], 3),
        "p99": round(percentile[98], 3),
        "max": round(max(values), 3),
    }


def parse_writer_timing(log_text: str, actions: set[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    marker = "[WRITER_TIMING] "
    decoder = json.JSONDecoder()
    for line in log_text.splitlines():
        if marker not in line:
            continue
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            payload, _end = decoder.raw_decode(line.split(marker, 1)[1])
            if payload.get("action") in actions:
                rows.append(payload)
    return {
        "count": len(rows),
        "failures": sum(not bool(row.get("success")) for row in rows),
        "queue_ms": quantiles(
            [float(row["queue_ms"]) for row in rows if row.get("queue_ms") is not None]
        ),
        "execution_ms": quantiles([float(row["execution_ms"]) for row in rows]),
        "total_ms": quantiles(
            [float(row["total_ms"]) for row in rows if row.get("total_ms") is not None]
        ),
    }


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(source) as source_conn,
        sqlite3.connect(destination) as destination_conn,
    ):
        source_conn.backup(destination_conn)


def clone_instance(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for child in source.iterdir():
        if child.name == "sqlite3.db":
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    _sqlite_backup(source / "sqlite3.db", destination / "sqlite3.db")


def _docker_env() -> list[str]:
    values = {
        "PUID": str(os.getuid()),
        "PGID": str(os.getgid()),
        "PODLY_INSTANCE_DIR": "/app/src/instance",
        "REQUIRE_AUTH": "true",
        "PODLY_ADMIN_USERNAME": "parity.user",
        "PODLY_ADMIN_PASSWORD": "parity-password-not-a-secret",
        "PODLY_SECRET_KEY": "synthetic-benchmark-session-key",
        "PODLY_IPC_AUTHKEY": "synthetic-benchmark-ipc-key",
        "PODLY_WRITER_TIMING_LOG": "true",
        "PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC": "900",
        "PODLY_MEMORY_TRIM_INTERVAL_MIN": "15",
        "PODLY_RUST_TOOLS_BIN": "/app/bin/podly_tools",
        "SERVER_THREADS": "32",
    }
    values.update({name: "true" for name in RUST_FLAGS})
    flattened: list[str] = []
    for key, value in values.items():
        flattened.extend(["-e", f"{key}={value}"])
    return flattened


def start_container(name: str, image: str, instance_dir: Path) -> str:
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--restart=no",
        "--label",
        "podly.benchmark=rust-writer-p0",
        "-p",
        "127.0.0.1:0:5001",
        "--mount",
        f"type=bind,src={instance_dir.resolve()},dst=/app/src/instance",
        "--add-host",
        "one.example.invalid:127.0.0.1",
        "--add-host",
        "two.example.invalid:127.0.0.1",
        *_docker_env(),
        image,
    ]
    _run(command, timeout=120)
    port = _run(["docker", "port", name, "5001/tcp"]).stdout.strip()
    return f"http://{port}"


def stop_container(name: str) -> None:
    _run(["docker", "stop", "--time", "20", name], timeout=40, check=False)
    _run(["docker", "rm", name], timeout=30, check=False)


def _request(url: str, cookie: str | None = None) -> HttpSample:
    request = urllib.request.Request(url, method="GET")
    if cookie:
        request.add_header("Cookie", cookie)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    return HttpSample((time.perf_counter() - started) * 1000, status, len(body))


def _login(base_url: str) -> str:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=json.dumps(
            {
                "username": "parity.user",
                "password": "parity-password-not-a-secret",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener.open(request, timeout=30).read()
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in jar)


def wait_ready(name: str, base_url: str, timeout: float = 120) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if _request(f"{base_url}/api/auth/status").status != 200:
                raise RuntimeError("auth status is not ready")
            readiness_code = """
from app.writer.client import writer_client
r=writer_client.action('update_user_last_active',{'user_id':101},wait=True)
assert r is not None and r.success, r
"""
            _run(
                [
                    "docker",
                    "exec",
                    "-e",
                    "PYTHONPATH=/app/src",
                    "-e",
                    "PODLY_WRITER_TIMEOUT_SECONDS=2",
                    name,
                    "python3",
                    "-c",
                    readiness_code,
                ],
                timeout=10,
            )
            cookie = _login(base_url)
            if _request(f"{base_url}/feeds", cookie).status == 200:
                return cookie
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"isolated container did not become ready: {last_error}")


def direct_rust_probe(name: str) -> dict[str, int]:
    code = """
from pathlib import Path
from shared.rust_sidecar import try_render_aggregate_feed_xml, try_render_feed_posts
p=Path('/app/src/instance/sqlite3.db')
posts=try_render_feed_posts(db_path=p,feed_id=201,page=1,page_size=200,whitelisted_only=False)
xml=try_render_aggregate_feed_xml(db_path=p,user_id=101,base_url='http://benchmark.invalid',require_auth=True,limit_per_feed=3,feed_token=None,feed_secret=None)
assert isinstance(posts,bytes), type(posts)
assert isinstance(xml,bytes), type(xml)
import json; print(json.dumps({'feed_posts_bytes':len(posts),'feed_xml_bytes':len(xml)}))
"""
    output = _run(
        [
            "docker",
            "exec",
            "-e",
            "PYTHONPATH=/app/src",
            name,
            "python3",
            "-c",
            code,
        ],
        timeout=120,
    ).stdout
    return json.loads(output.strip().splitlines()[-1])


def _process_snapshot(name: str) -> list[dict[str, Any]]:
    output = _run(
        ["docker", "top", name, "-eo", "pid,ppid,rss,nlwp,args"], check=False
    ).stdout
    rows: list[dict[str, Any]] = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 4)
        if len(parts) != 5 or not all(item.isdigit() for item in parts[:4]):
            continue
        pid = int(parts[0])
        try:
            fd_count = len(list(Path(f"/proc/{pid}/fd").iterdir()))
        except OSError:
            fd_count = -1
        rows.append(
            {
                "pid": pid,
                "ppid": int(parts[1]),
                "rss_bytes": int(parts[2]) * 1024,
                "threads": int(parts[3]),
                "fds": fd_count,
                "command": parts[4],
            }
        )
    return rows


def _application_log(name: str) -> str:
    result = _run(
        ["docker", "exec", name, "cat", "/app/src/instance/logs/app.log"],
        timeout=30,
        check=False,
    )
    return result.stdout + result.stderr


def resource_sample(name: str, phase: str) -> dict[str, Any]:
    raw = _run(
        ["docker", "stats", name, "--no-stream", "--format", "{{json .}}"],
        timeout=30,
    ).stdout.strip()
    stats = json.loads(raw)
    usage = stats["MemUsage"].split("/", 1)[0].strip()
    return {
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "phase": phase,
        "container_memory_bytes": parse_size_bytes(usage),
        "container_cpu_percent": float(stats["CPUPerc"].rstrip("%")),
        "container_pids": int(stats["PIDs"]),
        "processes": _process_snapshot(name),
    }


class Sampler:
    def __init__(self, name: str, interval: float) -> None:
        self.name = name
        self.interval = interval
        self.phase = "idle"
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._started = False

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def close(self) -> None:
        if not self._started:
            return
        self._stop.set()
        self._thread.join(timeout=self.interval + 30)

    def _loop(self) -> None:
        while not self._stop.is_set():
            with contextlib.suppress(Exception):
                self.samples.append(resource_sample(self.name, self.phase))
            self._stop.wait(self.interval)


def http_workload(
    url: str, cookie: str, duration: float, concurrency: int
) -> dict[str, Any]:
    deadline = time.monotonic() + duration

    def worker() -> list[HttpSample]:
        samples: list[HttpSample] = []
        while time.monotonic() < deadline:
            samples.append(_request(url, cookie))
        return samples

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        batches = list(executor.map(lambda _index: worker(), range(concurrency)))
    elapsed = time.perf_counter() - started
    samples = [sample for batch in batches for sample in batch]
    statuses = {
        status: sum(item.status == status for item in samples)
        for status in {item.status for item in samples}
    }
    return {
        "url": url,
        "count": len(samples),
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 6),
        "throughput_per_second": round(len(samples) / elapsed, 3),
        "status_codes": statuses,
        "body_bytes_mean": round(statistics.fmean(item.body_bytes for item in samples)),
        "latency_ms": quantiles([item.latency_ms for item in samples]),
    }


def writer_workload(
    name: str, workload: str, count: int, concurrency: int
) -> dict[str, Any]:
    log_before = _application_log(name)
    result = _run(
        [
            "docker",
            "exec",
            "-e",
            "PYTHONPATH=/app/src",
            name,
            "python3",
            "/app/scripts/bench_writer_service.py",
            "--workload",
            workload,
            "--count",
            str(count),
            "--concurrency",
            str(concurrency),
        ],
        timeout=1800,
    )
    client = json.loads(result.stdout.strip().splitlines()[-1])
    log_after = _application_log(name)
    logs = (
        log_after[len(log_before) :] if log_after.startswith(log_before) else log_after
    )
    actions = (
        {"update_user_last_active"}
        if workload == "small"
        else {"replace_transcription"}
        if workload == "large"
        else {"update_user_last_active", "replace_transcription"}
    )
    return {"client": client, "writer_timing": parse_writer_timing(logs, actions)}


def summarize_resources(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_phase: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_phase.setdefault(sample["phase"], []).append(sample)
    output: dict[str, Any] = {}
    for phase, rows in by_phase.items():
        memory = [row["container_memory_bytes"] for row in rows]
        cpu = [row["container_cpu_percent"] for row in rows]
        output[phase] = {
            "samples": len(rows),
            "memory_bytes_median": round(statistics.median(memory)),
            "memory_bytes_max": max(memory),
            "cpu_percent_mean": round(statistics.fmean(cpu), 3),
            "pids_max": max(row["container_pids"] for row in rows),
            "threads_max": max(
                sum(process["threads"] for process in row["processes"]) for row in rows
            ),
            "fds_max": max(
                sum(max(0, process["fds"]) for process in row["processes"])
                for row in rows
            ),
        }
    return output


def cooldown(sampler: Sampler, seconds: float, label: str) -> None:
    sampler.phase = f"cooldown_{label}"
    time.sleep(seconds)


def run_repetition(
    *,
    image: str,
    output: Path,
    index: int,
    duration: float,
    idle_seconds: float,
    cooldown_seconds: float,
    sample_interval: float,
    concurrency: int,
    small_writes: int,
    large_writes: int,
    mixed_writes: int,
) -> dict[str, Any]:
    name = f"podly-writer-p0-{os.getpid()}-{index}"
    instance_dir = output / f"run-{index}" / "instance"
    clone_instance(output / "source" / "instance", instance_dir)
    base_url = start_container(name, image, instance_dir)
    sampler = Sampler(name, sample_interval)
    started_at = dt.datetime.now(dt.UTC).isoformat()
    try:
        cookie = wait_ready(name, base_url)
        rust_probe = direct_rust_probe(name)
        sampler.start()
        sampler.phase = "idle"
        time.sleep(idle_seconds)

        # Warm both paths, including the one allowed opportunistic refresh.
        for url in (
            f"{base_url}/api/feeds/201/posts?page=1&page_size=200",
            f"{base_url}/feed/user/101",
        ):
            for _ in range(10):
                _request(url, cookie)
        time.sleep(2)

        sampler.phase = "http_feed_posts"
        feed_posts = http_workload(
            f"{base_url}/api/feeds/201/posts?page=1&page_size=200",
            cookie,
            duration,
            concurrency,
        )
        cooldown(sampler, cooldown_seconds, "http_feed_posts")

        sampler.phase = "http_rss"
        rss = http_workload(f"{base_url}/feed/user/101", cookie, duration, concurrency)
        cooldown(sampler, cooldown_seconds, "http_rss")

        sampler.phase = "writer_small"
        small = writer_workload(name, "small", small_writes, concurrency)
        cooldown(sampler, cooldown_seconds, "writer_small")

        sampler.phase = "writer_large"
        large = writer_workload(name, "large", large_writes, concurrency)
        cooldown(sampler, cooldown_seconds, "writer_large")

        sampler.phase = "writer_mixed"
        mixed = writer_workload(name, "mixed", mixed_writes, concurrency)
        cooldown(sampler, cooldown_seconds, "writer_mixed")
        sampler.close()

        log_result = _run(["docker", "logs", "--since", started_at, name], check=False)
        logs = log_result.stdout + log_result.stderr + _application_log(name)
        fallback_lines = [
            line
            for line in logs.splitlines()
            if "falling back" in line.lower()
            and ("feed" in line.lower() or "posts" in line.lower())
        ]
        process_end = _process_snapshot(name)
        return {
            "run": index,
            "container": name,
            "base_url": base_url,
            "started_at": started_at,
            "rust_probe": rust_probe,
            "fallback_lines": fallback_lines,
            "http": {"feed_posts": feed_posts, "rss": rss},
            "writer": {"small": small, "large": large, "mixed": mixed},
            "resources": summarize_resources(sampler.samples),
            "processes_after_cooldown": process_end,
        }
    finally:
        sampler.close()
        stop_container(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--duration-seconds", type=float, default=60)
    parser.add_argument("--idle-seconds", type=float, default=60)
    parser.add_argument("--cooldown-seconds", type=float, default=60)
    parser.add_argument("--sample-interval-seconds", type=float, default=1)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--small-writes", type=int, default=1000)
    parser.add_argument("--large-writes", type=int, default=12)
    parser.add_argument("--mixed-writes", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be absent or empty")
    if args.repetitions < 3 or args.concurrency < 8:
        parser.error("migration baselines require at least 3 repetitions and c=8")
    args.output.mkdir(parents=True, exist_ok=True)
    source_instance = args.output / "source" / "instance"
    export_writer_parity_instance(source_instance, benchmark_post_count=200)
    fixture_sha256 = hashlib.sha256(
        (source_instance / "sqlite3.db").read_bytes()
    ).hexdigest()
    image_info = json.loads(_run(["docker", "image", "inspect", args.image]).stdout)[0]
    protocol = {
        "image": args.image,
        "image_id": image_info["Id"],
        "fixture_sha256": fixture_sha256,
        "repetitions": args.repetitions,
        "duration_seconds": args.duration_seconds,
        "idle_seconds": args.idle_seconds,
        "cooldown_seconds": args.cooldown_seconds,
        "sample_interval_seconds": args.sample_interval_seconds,
        "concurrency": args.concurrency,
        "small_writes": args.small_writes,
        "large_writes": args.large_writes,
        "mixed_writes": args.mixed_writes,
        "environment_names": sorted(
            [
                "PODLY_INSTANCE_DIR",
                "REQUIRE_AUTH",
                "SERVER_THREADS",
                "PODLY_WRITER_TIMING_LOG",
                "PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC",
                *RUST_FLAGS,
            ]
        ),
    }
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    runs = []
    for index in range(1, args.repetitions + 1):
        result = run_repetition(
            image=args.image,
            output=args.output,
            index=index,
            duration=args.duration_seconds,
            idle_seconds=args.idle_seconds,
            cooldown_seconds=args.cooldown_seconds,
            sample_interval=args.sample_interval_seconds,
            concurrency=args.concurrency,
            small_writes=args.small_writes,
            large_writes=args.large_writes,
            mixed_writes=args.mixed_writes,
        )
        runs.append(result)
        (args.output / f"run-{index}.json").write_text(json.dumps(result, indent=2))
    report = {"protocol": protocol, "runs": runs}
    (args.output / "report.json").write_text(json.dumps(report, indent=2))

    errors = []
    for run in runs:
        errors.extend(run["fallback_lines"])
        for workload in run["http"].values():
            if set(workload["status_codes"]) != {200}:
                errors.append(f"unexpected HTTP statuses: {workload['status_codes']}")
        for workload in run["writer"].values():
            if workload["client"]["failures"] or workload["writer_timing"]["failures"]:
                errors.append("writer workload failure")
    print(json.dumps({"report": str(args.output / "report.json"), "errors": errors}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
