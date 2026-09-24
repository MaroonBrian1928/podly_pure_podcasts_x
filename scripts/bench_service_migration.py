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
from itertools import pairwise
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

DEFAULT_PROFILE: dict[str, int | float] = {
    "repetitions": 3,
    "duration_seconds": 60,
    "idle_seconds": 60,
    "cooldown_seconds": 60,
    "sample_interval_seconds": 1,
    "concurrency": 8,
    "small_writes": 1000,
    "large_writes": 12,
    "mixed_writes": 100,
}
PROFILE_KEYS = tuple(DEFAULT_PROFILE)
P0_ACCEPTANCE = {
    "idle_memory_bytes_max": 130_652_570,
    "writer_rss_bytes_max": 49_753_293,
    "feed_posts_p95_ms_max": 49.210,
    "feed_posts_p99_ms_max": 81.428,
    "feed_posts_throughput_min": 320.073,
    "rss_p95_ms_max": 933.051,
    "rss_p99_ms_max": 1110.410,
    "rss_throughput_min": 11.136,
    "writer_small_p95_ms_max": 22.313,
    "writer_small_p99_ms_max": 39.341,
    "writer_large_p95_ms_max": 2392.645,
    "writer_large_p99_ms_max": 2581.554,
    "writer_mixed_p95_ms_max": 534.044,
    "writer_mixed_p99_ms_max": 598.306,
    "queue_small_p95_ms_max": 20.440,
    "queue_small_p99_ms_max": 31.947,
    "queue_large_p95_ms_max": 2026.144,
    "queue_large_p99_ms_max": 2122.885,
    "queue_mixed_p95_ms_max": 321.793,
    "queue_mixed_p99_ms_max": 593.488,
    "cpu_efficiency_ratio_max": 1.15,
    "recovery_memory_headroom_bytes": 10 * 1024 * 1024,
    "recovery_threads_headroom": 2,
    "recovery_fds_headroom": 8,
}


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


def paired_profile(
    baseline_report: Path | None, requested: dict[str, int | float | None]
) -> tuple[dict[str, int | float], Path | None, dict[str, Any] | None]:
    if baseline_report is None:
        profile = {
            key: requested[key] if requested.get(key) is not None else default
            for key, default in DEFAULT_PROFILE.items()
        }
        return profile, None, None

    baseline = json.loads(baseline_report.read_text(encoding="utf-8"))
    baseline_protocol = baseline.get("protocol")
    if not isinstance(baseline_protocol, dict):
        raise ValueError("baseline report has no protocol object")
    missing = [key for key in PROFILE_KEYS if key not in baseline_protocol]
    if missing:
        raise ValueError(f"baseline protocol is missing profile fields: {missing}")
    profile = {key: baseline_protocol[key] for key in PROFILE_KEYS}
    mismatches = {
        key: {"baseline": profile[key], "requested": requested[key]}
        for key in PROFILE_KEYS
        if requested.get(key) is not None and requested[key] != profile[key]
    }
    if mismatches:
        raise ValueError(f"requested profile differs from P0 baseline: {mismatches}")
    source_instance = baseline_report.resolve().parent / "source" / "instance"
    if not (source_instance / "sqlite3.db").is_file():
        raise ValueError("P0 baseline source/instance/sqlite3.db is missing")
    actual_fixture = hashlib.sha256(
        (source_instance / "sqlite3.db").read_bytes()
    ).hexdigest()
    if actual_fixture != baseline_protocol.get("fixture_sha256"):
        raise ValueError(
            "P0 baseline fixture hash mismatch: "
            f"expected {baseline_protocol.get('fixture_sha256')}, got {actual_fixture}"
        )
    if len(baseline.get("runs", [])) < 3:
        raise ValueError("P0 baseline must contain at least three runs")
    return profile, source_instance, baseline


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


def _docker_env(writer_backend: str) -> list[str]:
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
        "PODLY_WRITER_BACKEND": writer_backend,
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


def start_container(
    name: str, image: str, instance_dir: Path, writer_backend: str
) -> str:
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--restart=no",
        "--label",
        "podly.benchmark=rust-writer-migration",
        "-p",
        "127.0.0.1:0:5001",
        "--mount",
        f"type=bind,src={instance_dir.resolve()},dst=/app/src/instance",
        "--add-host",
        "one.example.invalid:127.0.0.1",
        "--add-host",
        "two.example.invalid:127.0.0.1",
        *_docker_env(writer_backend),
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


def wait_ready(
    name: str, base_url: str, writer_backend: str, timeout: float = 120
) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if _request(f"{base_url}/api/auth/status").status != 200:
                raise RuntimeError("auth status is not ready")
            if writer_backend == "rust":
                _run(["docker", "exec", name, "/app/bin/podly_writer", "--probe"])
            readiness_code = """
from app.writer.client import writer_client
r=writer_client.action('update_user_last_active',{'user_id':101},wait=True)
assert r is not None and r.success, r
"""
            if writer_backend == "python":
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


def _writer_role(processes: list[dict[str, Any]]) -> str | None:
    commands = "\n".join(str(process["command"]) for process in processes)
    if "podly_writer" in commands:
        return "rust"
    if "app.writer" in commands:
        return "python"
    return None


def _assert_writer_identity(name: str, writer_backend: str) -> list[dict[str, Any]]:
    processes = _process_snapshot(name)
    actual = _writer_role(processes)
    if actual != writer_backend:
        raise RuntimeError(
            f"requested {writer_backend} writer but process identity is {actual}: "
            f"{processes}"
        )
    if writer_backend == "rust" and any(
        "app.writer" in str(process["command"]) for process in processes
    ):
        raise RuntimeError("Rust benchmark contains a resident Python writer")
    return processes


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
    name: str, workload: str, count: int, concurrency: int, writer_backend: str
) -> dict[str, Any]:
    log_before = _application_log(name)
    workload_started_at = dt.datetime.now(dt.UTC).isoformat()
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
    if writer_backend == "rust":
        log_result = _run(
            ["docker", "logs", "--since", workload_started_at, name], check=False
        )
        logs = log_result.stdout + log_result.stderr
    else:
        log_after = _application_log(name)
        logs = (
            log_after[len(log_before) :]
            if log_after.startswith(log_before)
            else log_after
        )
    actions = (
        {"update_user_last_active"}
        if workload == "small"
        else {"replace_transcription"}
        if workload == "large"
        else {"update_user_last_active", "replace_transcription"}
    )
    return {
        "client": client,
        "writer_timing": parse_writer_timing(logs, actions),
    }


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


def _median_metric(report: dict[str, Any], selector: Any) -> float:
    values = [float(selector(run)) for run in report["runs"]]
    return float(statistics.median(values))


def _process_role(command: str) -> str | None:
    lowered = command.lower()
    if "podly_writer" in lowered or "app.writer" in lowered:
        return "writer"
    if "src/main.py" in lowered:
        return "web"
    if "start_services.sh" in lowered:
        return "supervisor"
    return None


def compare_to_p0(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Apply the fixed P0.7 acceptance limits to a same-profile P4 report."""
    gates: dict[str, dict[str, Any]] = {}

    def bounded(
        name: str, observed: float, limit: float, *, minimum: bool = False
    ) -> None:
        passed = observed >= limit if minimum else observed <= limit
        gates[name] = {
            "observed": round(observed, 3),
            "threshold": limit,
            "comparison": ">=" if minimum else "<=",
            "passed": passed,
        }

    def value(path: tuple[str, ...]) -> float:
        return _median_metric(
            current,
            lambda run: _deep_get(run, path),
        )

    def baseline_cpu_efficiency(
        workload: str, phase: str, section: tuple[str, ...]
    ) -> float:
        return _median_metric(
            baseline,
            lambda run: (
                float(_deep_get(run, ("resources", phase, "cpu_percent_mean")))
                / max(float(_deep_get(run, (*section, "throughput_per_second"))), 1e-9)
            ),
        )

    def current_cpu_efficiency(
        workload: str, phase: str, section: tuple[str, ...]
    ) -> float:
        return _median_metric(
            current,
            lambda run: (
                float(_deep_get(run, ("resources", phase, "cpu_percent_mean")))
                / max(float(_deep_get(run, (*section, "throughput_per_second"))), 1e-9)
            ),
        )

    idle_memory = value(("resources", "idle", "memory_bytes_median"))
    bounded(
        "idle_container_memory", idle_memory, P0_ACCEPTANCE["idle_memory_bytes_max"]
    )

    writer_rss = _median_metric(
        current,
        lambda run: next(
            int(process["rss_bytes"])
            for process in run["processes_after_cooldown"]
            if _process_role(str(process["command"])) == "writer"
            and "podly_writer" in str(process["command"])
        ),
    )
    bounded("rust_writer_rss", writer_rss, P0_ACCEPTANCE["writer_rss_bytes_max"])

    for key, path in (
        ("feed_posts_p95_ms_max", ("http", "feed_posts", "latency_ms", "p95")),
        ("feed_posts_p99_ms_max", ("http", "feed_posts", "latency_ms", "p99")),
        (
            "feed_posts_throughput_min",
            ("http", "feed_posts", "throughput_per_second"),
        ),
        ("rss_p95_ms_max", ("http", "rss", "latency_ms", "p95")),
        ("rss_p99_ms_max", ("http", "rss", "latency_ms", "p99")),
        ("rss_throughput_min", ("http", "rss", "throughput_per_second")),
    ):
        bounded(
            key,
            value(path),
            P0_ACCEPTANCE[key],
            minimum=key.endswith("throughput_min"),
        )

    for name in ("small", "large", "mixed"):
        for percentile in ("p95", "p99"):
            e2e_key = f"writer_{name}_{percentile}_ms_max"
            queue_key = f"queue_{name}_{percentile}_ms_max"
            bounded(
                e2e_key,
                value(("writer", name, "client", "latency_ms", percentile)),
                P0_ACCEPTANCE[e2e_key],
            )
            bounded(
                queue_key,
                value(("writer", name, "writer_timing", "queue_ms", percentile)),
                P0_ACCEPTANCE[queue_key],
            )

    cpu_sections = (
        ("feed_posts", "http_feed_posts", ("http", "feed_posts")),
        ("rss", "http_rss", ("http", "rss")),
        ("small", "writer_small", ("writer", "small", "client")),
        ("large", "writer_large", ("writer", "large", "client")),
        ("mixed", "writer_mixed", ("writer", "mixed", "client")),
    )
    for name, phase, section in cpu_sections:
        baseline_efficiency = baseline_cpu_efficiency(name, phase, section)
        current_efficiency = current_cpu_efficiency(name, phase, section)
        ratio = (
            current_efficiency / baseline_efficiency
            if baseline_efficiency
            else math.inf
        )
        bounded(
            f"cpu_efficiency_{name}",
            ratio,
            P0_ACCEPTANCE["cpu_efficiency_ratio_max"],
        )

    recovery_ok = True
    recovery_observed: dict[str, int] = {}
    for run in current["runs"]:
        idle = int(run["resources"]["idle"]["memory_bytes_median"])
        cooldown_rows = [
            row
            for phase, row in run["resources"].items()
            if phase.startswith("cooldown_")
        ]
        recovery_observed[run["run"]] = max(
            (int(row["memory_bytes_max"]) - idle for row in cooldown_rows),
            default=0,
        )
        recovery_ok = (
            recovery_ok
            and bool(cooldown_rows)
            and all(
                int(row["memory_bytes_max"])
                <= idle + P0_ACCEPTANCE["recovery_memory_headroom_bytes"]
                for row in cooldown_rows
            )
        )
    gates["post_burst_memory_recovery"] = {
        "observed_extra_bytes_by_run": recovery_observed,
        "threshold_extra_bytes": P0_ACCEPTANCE["recovery_memory_headroom_bytes"],
        "passed": recovery_ok,
    }

    resource_ok = True
    resource_observed: dict[str, dict[str, int]] = {}
    for run in current["runs"]:
        idle_resources = run["resources"]["idle"]
        final_processes = run["processes_after_cooldown"]
        final_threads = sum(int(process["threads"]) for process in final_processes)
        final_fds = sum(max(0, int(process["fds"])) for process in final_processes)
        thread_delta = final_threads - int(idle_resources["threads_max"])
        fd_delta = final_fds - int(idle_resources["fds_max"])
        resource_observed[str(run["run"])] = {
            "threads_delta": thread_delta,
            "fds_delta": fd_delta,
        }
        resource_ok = resource_ok and (
            thread_delta <= P0_ACCEPTANCE["recovery_threads_headroom"]
            and fd_delta <= P0_ACCEPTANCE["recovery_fds_headroom"]
        )
    gates["thread_fd_recovery"] = {
        "observed_deltas_by_run": resource_observed,
        "thread_headroom": P0_ACCEPTANCE["recovery_threads_headroom"],
        "fd_headroom": P0_ACCEPTANCE["recovery_fds_headroom"],
        "passed": resource_ok,
    }

    idle_series = [
        int(run["resources"]["idle"]["memory_bytes_median"]) for run in current["runs"]
    ]
    monotonic_growth = len(idle_series) > 1 and all(
        right > left for left, right in pairwise(idle_series)
    )
    gates["no_monotonic_idle_growth"] = {
        "idle_memory_bytes_by_run": idle_series,
        "passed": not monotonic_growth,
    }

    process_ok = True
    for run in current["runs"]:
        commands = [
            str(process["command"]) for process in run["processes_after_cooldown"]
        ]
        process_ok = process_ok and run["writer_backend_process_identity"] == "rust"
        process_ok = process_ok and any(
            "src/main.py" in command for command in commands
        )
        process_ok = process_ok and not any(
            "app.writer" in command or "bootstrap" in command for command in commands
        )
        process_ok = process_ok and not run["fallback_lines"]
    gates["rust_identity_and_fallback"] = {"passed": process_ok}
    return {
        "thresholds": P0_ACCEPTANCE,
        "gates": gates,
        "passed": all(gate["passed"] for gate in gates.values()),
    }


def _deep_get(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current_value: Any = value
    for key in path:
        current_value = current_value[key]
    return current_value


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
    writer_backend: str,
) -> dict[str, Any]:
    name = f"podly-writer-{writer_backend}-{os.getpid()}-{index}"
    instance_dir = output / f"run-{index}" / "instance"
    clone_instance(output / "source" / "instance", instance_dir)
    base_url = start_container(name, image, instance_dir, writer_backend)
    sampler = Sampler(name, sample_interval)
    started_at = dt.datetime.now(dt.UTC).isoformat()
    try:
        cookie = wait_ready(name, base_url, writer_backend)
        processes_ready = _assert_writer_identity(name, writer_backend)
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
        small = writer_workload(
            name, "small", small_writes, concurrency, writer_backend
        )
        cooldown(sampler, cooldown_seconds, "writer_small")

        sampler.phase = "writer_large"
        large = writer_workload(
            name, "large", large_writes, concurrency, writer_backend
        )
        cooldown(sampler, cooldown_seconds, "writer_large")

        sampler.phase = "writer_mixed"
        mixed = writer_workload(
            name, "mixed", mixed_writes, concurrency, writer_backend
        )
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
        final_writer = _writer_role(process_end)
        return {
            "run": index,
            "container": name,
            "base_url": base_url,
            "started_at": started_at,
            "rust_probe": rust_probe,
            "writer_backend_requested": writer_backend,
            "writer_backend_process_identity": final_writer,
            "processes_after_ready": processes_ready,
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
    parser, args = _parse_benchmark_args()
    try:
        profile, baseline_instance, baseline = paired_profile(
            args.baseline_report, _requested_profile(args)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    _validate_run_options(parser, args, profile)
    args.output.mkdir(parents=True, exist_ok=True)
    source_instance = args.output / "source" / "instance"
    _copy_benchmark_fixture(source_instance, baseline_instance)
    protocol = _build_protocol(args, profile, source_instance, baseline, parser)
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    runs = _execute_repetitions(args, profile)
    report = {"protocol": protocol, "runs": runs}
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    errors = _collect_run_errors(runs, args.writer_backend)
    if baseline is not None:
        comparison = compare_to_p0(baseline, report)
        (args.output / "comparison.json").write_text(json.dumps(comparison, indent=2))
        errors.extend(_comparison_errors(comparison))
    print(json.dumps({"report": str(args.output / "report.json"), "errors": errors}))
    return 0 if not errors else 1


def _parse_benchmark_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument(
        "--writer-backend", choices=("python", "rust"), default="python"
    )
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--idle-seconds", type=float)
    parser.add_argument("--cooldown-seconds", type=float)
    parser.add_argument("--sample-interval-seconds", type=float)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--small-writes", type=int)
    parser.add_argument("--large-writes", type=int)
    parser.add_argument("--mixed-writes", type=int)
    return parser, parser.parse_args()


def _requested_profile(args: argparse.Namespace) -> dict[str, int | float | None]:
    return {
        "repetitions": args.repetitions,
        "duration_seconds": args.duration_seconds,
        "idle_seconds": args.idle_seconds,
        "cooldown_seconds": args.cooldown_seconds,
        "sample_interval_seconds": args.sample_interval_seconds,
        "concurrency": args.concurrency,
        "small_writes": args.small_writes,
        "large_writes": args.large_writes,
        "mixed_writes": args.mixed_writes,
    }


def _validate_run_options(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    profile: dict[str, int | float],
) -> None:
    if profile["repetitions"] < 3 or profile["concurrency"] < 8:
        parser.error("migration benchmarks require at least 3 repetitions and c=8")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be absent or empty")


def _copy_benchmark_fixture(
    source_instance: Path, baseline_instance: Path | None
) -> None:
    if baseline_instance is None:
        export_writer_parity_instance(source_instance, benchmark_post_count=200)
    else:
        shutil.copytree(baseline_instance, source_instance)


def _build_protocol(
    args: argparse.Namespace,
    profile: dict[str, int | float],
    source_instance: Path,
    baseline: dict[str, Any] | None,
    parser: argparse.ArgumentParser,
) -> dict[str, Any]:
    fixture_sha256 = hashlib.sha256(
        (source_instance / "sqlite3.db").read_bytes()
    ).hexdigest()
    if (
        baseline is not None
        and fixture_sha256 != baseline["protocol"]["fixture_sha256"]
    ):
        parser.error("cloned P0 fixture does not match the recorded baseline hash")
    image_info = json.loads(_run(["docker", "image", "inspect", args.image]).stdout)[0]
    protocol = {
        "image": args.image,
        "image_id": image_info["Id"],
        "fixture_sha256": fixture_sha256,
        "writer_backend": args.writer_backend,
        **profile,
        "paired_baseline_report": (
            str(args.baseline_report.resolve()) if args.baseline_report else None
        ),
        "environment_names": sorted(
            [
                "PODLY_INSTANCE_DIR",
                "REQUIRE_AUTH",
                "SERVER_THREADS",
                "PODLY_WRITER_BACKEND",
                "PODLY_WRITER_TIMING_LOG",
                "PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC",
                *RUST_FLAGS,
            ]
        ),
    }
    return protocol


def _execute_repetitions(
    args: argparse.Namespace, profile: dict[str, int | float]
) -> list[dict[str, Any]]:
    runs = []
    for index in range(1, int(profile["repetitions"]) + 1):
        result = run_repetition(
            image=args.image,
            output=args.output,
            index=index,
            duration=profile["duration_seconds"],
            idle_seconds=profile["idle_seconds"],
            cooldown_seconds=profile["cooldown_seconds"],
            sample_interval=profile["sample_interval_seconds"],
            concurrency=profile["concurrency"],
            small_writes=profile["small_writes"],
            large_writes=profile["large_writes"],
            mixed_writes=profile["mixed_writes"],
            writer_backend=args.writer_backend,
        )
        runs.append(result)
        (args.output / f"run-{index}.json").write_text(json.dumps(result, indent=2))
    return runs


def _collect_run_errors(runs: list[dict[str, Any]], writer_backend: str) -> list[str]:
    errors = []
    for run in runs:
        errors.extend(run["fallback_lines"])
        for workload in run["http"].values():
            if set(workload["status_codes"]) != {200}:
                errors.append(f"unexpected HTTP statuses: {workload['status_codes']}")
        for workload in run["writer"].values():
            if workload["client"]["failures"] or workload["writer_timing"]["failures"]:
                errors.append("writer workload failure")
            if workload["writer_timing"]["count"] != workload["client"]["successes"]:
                errors.append(
                    "writer timing record count does not match successful commands"
                )
        if run["writer_backend_process_identity"] != writer_backend:
            errors.append("writer process identity does not match selected backend")
    return errors


def _comparison_errors(comparison: dict[str, Any]) -> list[str]:
    return [
        f"P0 acceptance gate failed: {name}={gate.get('observed')}"
        for name, gate in comparison["gates"].items()
        if not gate["passed"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
