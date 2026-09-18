from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app import pricing_client, pricing_worker


@pytest.fixture(autouse=True)
def empty_pricing_cache():
    pricing_client._cache.clear()
    yield
    pricing_client._cache.clear()


def test_batches_only_uncached_unique_model_tier_pairs(monkeypatch):
    requests = []

    def run(_command, **kwargs):
        requested = json.loads(kwargs["input"])
        requests.append(requested)
        return SimpleNamespace(stdout=json.dumps([[1, 2, 3]] * len(requested)))

    monkeypatch.setattr(pricing_client.subprocess, "run", run)
    first = ("first", None)
    second = ("second", "priority")
    assert pricing_client.lookup_model_rates([first, first]) == {first: (1, 2, 3)}
    assert pricing_client.lookup_model_rates([first, second, second]) == {
        first: (1, 2, 3),
        second: (1, 2, 3),
    }
    assert pricing_client.lookup_model_rates([]) == {}
    assert requests == [[["first", None]], [["second", "priority"]]]


def test_cache_is_bounded_and_retains_recently_used_models(monkeypatch):
    requests = []

    def run(_command, **kwargs):
        requested = json.loads(kwargs["input"])
        requests.append(requested)
        return SimpleNamespace(stdout=json.dumps([[1, 2, 3]] * len(requested)))

    monkeypatch.setattr(pricing_client.subprocess, "run", run)
    pairs = [(f"model-{index}", None) for index in range(256)]
    assert len(pricing_client.lookup_model_rates(pairs)) == 256
    pricing_client.lookup_model_rates([pairs[0]])
    pricing_client.lookup_model_rates([("extra", None)])
    assert len(pricing_client._cache) == 256
    assert pairs[0] in pricing_client._cache
    assert pairs[1] not in pricing_client._cache
    pricing_client.lookup_model_rates([pairs[0], pairs[1]])
    assert requests[-1] == [["model-1", None]]
    assert len(requests) == 3


def test_expired_rates_refresh_without_extending_ttl_on_reads(monkeypatch):
    clock = [0.0]
    responses = iter(["[[1, 2, 3]]", "[[4, 5, 6]]"])
    monkeypatch.setattr(pricing_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        pricing_client.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=next(responses)),
    )
    pair = ("model", None)
    assert pricing_client.lookup_model_rates([pair])[pair] == (1, 2, 3)
    clock[0] = pricing_client.CACHE_TTL_SECONDS - 1
    assert pricing_client.lookup_model_rates([pair])[pair] == (1, 2, 3)
    clock[0] += 1
    assert pricing_client.lookup_model_rates([pair])[pair] == (4, 5, 6)


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("pricing-worker", 60),
        subprocess.CalledProcessError(1, "pricing-worker"),
        OSError("could not launch helper"),
        "not-json",
        "{}",
        "[]",
        "[[1, 2]]",
        "[[true, 2, 3]]",
        '[["1", 2, 3]]',
        "[[null, 2, 3]]",
        "[[NaN, 2, 3]]",
        "[[Infinity, 2, 3]]",
    ],
)
def test_failed_helper_returns_zero_and_next_request_recovers(monkeypatch, failure):
    responses = iter([failure, "[[1, 2, 3]]"])

    def run(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(stdout=response)

    monkeypatch.setattr(pricing_client.subprocess, "run", run)
    pair = ("model", None)
    assert pricing_client.lookup_model_rates([pair])[pair] == (0, 0, 0)
    assert pair not in pricing_client._cache
    assert pricing_client.lookup_model_rates([pair])[pair] == (1, 2, 3)


def test_invalid_batch_does_not_cache_partial_results(monkeypatch):
    monkeypatch.setattr(
        pricing_client.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="[[1, 2, 3], [false, 2, 3]]"),
    )
    pairs = [("first", None), ("second", None)]
    assert pricing_client.lookup_model_rates(pairs) == dict.fromkeys(pairs, (0, 0, 0))
    assert not pricing_client._cache


def test_concurrent_requests_for_same_model_launch_one_helper(monkeypatch):
    start = threading.Barrier(8)
    helper_entered = threading.Event()
    release_helper = threading.Event()
    calls = []

    def run(*_args, **_kwargs):
        calls.append(True)
        helper_entered.set()
        assert release_helper.wait(timeout=10)
        return SimpleNamespace(stdout="[[1, 2, 3]]")

    def lookup():
        start.wait(timeout=10)
        return pricing_client.lookup_model_rates([("model", None)])

    monkeypatch.setattr(pricing_client.subprocess, "run", run)
    with ThreadPoolExecutor(max_workers=8) as executor:
        pending = [executor.submit(lookup) for _ in range(8)]
        try:
            assert helper_entered.wait(timeout=10)
        finally:
            release_helper.set()
        results = [future.result(timeout=10) for future in pending]
    assert len(calls) == 1
    assert results == [{("model", None): (1, 2, 3)}] * 8


def test_worker_redirects_sdk_stdout_away_from_json(monkeypatch, capsys):
    from app import llm_pricing

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace())
    monkeypatch.setattr(sys, "stdin", io.StringIO('[["model", "priority"]]'))
    calls = []

    def rate(name, key, tier):
        print("SDK diagnostic")
        calls.append((name, key, tier))
        return 0.25

    monkeypatch.setattr(llm_pricing, "rate_from_litellm", rate)
    pricing_worker.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [[0.25, 0.25, 0.25]]
    assert captured.err.count("SDK diagnostic") == 3
    assert calls == [("model", key, "priority") for key in llm_pricing.RATE_KEYS]


@pytest.mark.parametrize("role", ["web", "writer"])
def test_resident_model_rates_does_not_import_litellm(role):
    script = f"""
import sys
from types import SimpleNamespace
import pytest
from flask import Flask
from app import pricing_client
from app.llm_pricing import model_rates
pricing_client.subprocess.run = lambda *args, **kwargs: SimpleNamespace(stdout='[[1,2,3]]')
app = Flask(__name__)
app.config['PODLY_APP_ROLE'] = {role!r}
with app.app_context():
    assert model_rates([('model', None)]) == {{('model', None): (1, 2, 3)}}
assert 'litellm' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
