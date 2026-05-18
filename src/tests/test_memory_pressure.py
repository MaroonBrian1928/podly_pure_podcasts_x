from __future__ import annotations

import logging

from app import memory_pressure


def test_memory_trim_after_context_round_trips(app) -> None:
    with app.app_context():
        memory_pressure.request_memory_trim_after_context("feed refresh")
        memory_pressure.request_memory_trim_after_context("feed XML")

        assert memory_pressure.consume_memory_trim_contexts() == [
            "feed refresh",
            "feed XML",
        ]
        assert memory_pressure.consume_memory_trim_contexts() == []


def test_release_memory_to_os_runs_gc_and_malloc_trim(monkeypatch) -> None:
    """On glibc (no jemalloc), release_memory_to_os falls back to malloc_trim."""
    calls: list[str] = []

    monkeypatch.setattr(
        memory_pressure.gc,
        "collect",
        lambda: calls.append("gc") or 3,
    )
    monkeypatch.setattr(
        memory_pressure,
        "_jemalloc_purge_all_arenas",
        lambda _logger: False,  # jemalloc not loaded
    )
    monkeypatch.setattr(
        memory_pressure,
        "_malloc_trim",
        lambda: lambda _pad: calls.append("trim") or 1,
    )

    memory_pressure.release_memory_to_os("test", logging.getLogger("test"))

    assert calls == ["gc", "trim"]


def test_release_memory_to_os_prefers_jemalloc_when_available(monkeypatch) -> None:
    """When jemalloc is preloaded, we must NOT call glibc malloc_trim — it's a
    no-op stub under jemalloc and pollutes logs with false negatives.
    """
    calls: list[str] = []

    monkeypatch.setattr(
        memory_pressure.gc,
        "collect",
        lambda: calls.append("gc") or 3,
    )
    monkeypatch.setattr(
        memory_pressure,
        "_jemalloc_purge_all_arenas",
        lambda _logger: calls.append("jemalloc_purge") or True,
    )
    # If the fallback path runs by mistake, this raises and the test fails.
    monkeypatch.setattr(
        memory_pressure,
        "_malloc_trim",
        lambda: (_ for _ in ()).throw(
            AssertionError("malloc_trim must not run under jemalloc")
        ),
    )

    memory_pressure.release_memory_to_os("test", logging.getLogger("test"))

    assert calls == ["gc", "jemalloc_purge"]


def test_release_memory_to_os_can_be_disabled(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setenv("PODLY_MEMORY_TRIM_ENABLED", "0")
    monkeypatch.setattr(
        memory_pressure.gc,
        "collect",
        lambda: calls.append("gc") or 0,
    )

    memory_pressure.release_memory_to_os("test", logging.getLogger("test"))

    assert calls == []


def test_collect_incremental_uses_generation_one(monkeypatch) -> None:
    calls: list[int] = []

    monkeypatch.setattr(
        memory_pressure.gc,
        "collect",
        lambda generation=2: calls.append(generation) or 5,
    )

    memory_pressure.collect_incremental("test", logging.getLogger("test"))

    assert calls == [1]
