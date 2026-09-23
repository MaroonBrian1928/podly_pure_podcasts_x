"""Differential parity cases for all currently registered feed actions.

Every case uses synthetic fixture data and independent Python/Rust database
clones. Only generated IDs, secrets, hashes derived from generated secrets, and
clock fields are normalized, with each nondeterministic value checked against
its semantic contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.writer.protocol import WriteCommand, WriteCommandType
from tests.writer_parity_fixtures import WriterParityPair

WRITER_DIFFERENTIAL_CASES = (
    {
        "case_id": "feed_refresh_existing_post_and_metadata",
        "operation": "action",
        "action": "refresh_feed",
        "owner": "refresh_feed",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "feed_refresh",
        "expect_success": True,
    },
    {
        "case_id": "feed_add_with_post_defaults",
        "operation": "action",
        "action": "add_feed",
        "owner": "add_feed",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "add_feed",
        "expect_success": True,
    },
    {
        "case_id": "feed_update_settings",
        "operation": "action",
        "action": "update_feed_settings",
        "owner": "update_feed_settings",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_increment_download_count",
        "operation": "action",
        "action": "increment_download_count",
        "owner": "increment_download_count",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_whitelist_post",
        "operation": "action",
        "action": "whitelist_post",
        "owner": "whitelist_post",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_ensure_membership",
        "operation": "action",
        "action": "ensure_user_feed_membership",
        "owner": "ensure_user_feed_membership",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "membership",
        "expect_success": True,
    },
    {
        "case_id": "feed_remove_membership",
        "operation": "action",
        "action": "remove_user_feed_membership",
        "owner": "remove_user_feed_membership",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_whitelist_latest_post",
        "operation": "action",
        "action": "whitelist_latest_post_for_feed",
        "owner": "whitelist_latest_post_for_feed",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_toggle_whitelist_all",
        "operation": "action",
        "action": "toggle_whitelist_all_for_feed",
        "owner": "toggle_whitelist_all_for_feed",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_create_dev_test_feed",
        "operation": "action",
        "action": "create_dev_test_feed",
        "owner": "create_dev_test_feed",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "dev_feed",
        "expect_success": True,
    },
    {
        "case_id": "feed_delete_cascade",
        "operation": "action",
        "action": "delete_feed_cascade",
        "owner": "delete_feed_cascade",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "exact",
        "expect_success": True,
    },
    {
        "case_id": "feed_create_access_token",
        "operation": "action",
        "action": "create_feed_access_token",
        "owner": "create_feed_access_token",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "token_create",
        "expect_success": True,
    },
    {
        "case_id": "feed_touch_access_token",
        "operation": "action",
        "action": "touch_feed_access_token",
        "owner": "touch_feed_access_token",
        "owner_group": "feed",
        "source": "src/app/writer/actions/feeds.py",
        "semantics": "token_touch",
        "expect_success": True,
    },
)


def _params(case_id: str, pair: WriterParityPair) -> dict[str, Any]:
    user_id = pair.manifest.user_id
    feed_id, second_feed_id = pair.manifest.feed_ids
    post_id, second_post_id = pair.manifest.post_ids
    token_id = pair.manifest.token_ids[0]
    factories: dict[str, Callable[[], dict[str, Any]]] = {
        "feed_refresh_existing_post_and_metadata": lambda: {
            "feed_id": feed_id,
            "updates": {"description": "Updated by differential parity"},
            "new_posts": [],
            "existing_post_updates": [
                {
                    "post_id": post_id,
                    "title": "Refreshed parity episode",
                    "duration": 3600.25,
                }
            ],
        },
        "feed_add_with_post_defaults": lambda: {
            "feed": {
                "title": "Differentially added feed",
                "rss_url": "https://added.example.invalid/parity.xml",
                "description": "Synthetic add-feed parity fixture",
                "author": "Parity Test",
            },
            "posts": [
                {
                    "guid": "parity-added-feed-post",
                    "title": "Added synthetic episode",
                    "download_url": "https://added.example.invalid/episode.mp3",
                    "release_date": "2026-01-03T04:05:06",
                    "duration": 123.5,
                    "whitelisted": False,
                }
            ],
        },
        "feed_update_settings": lambda: {
            "feed_id": second_feed_id,
            "auto_whitelist_new_episodes_override": True,
        },
        "feed_increment_download_count": lambda: {"post_id": post_id},
        "feed_whitelist_post": lambda: {"post_id": second_post_id},
        "feed_ensure_membership": lambda: {
            "feed_id": second_feed_id,
            "user_id": user_id,
        },
        "feed_remove_membership": lambda: {"feed_id": feed_id, "user_id": user_id},
        "feed_whitelist_latest_post": lambda: {"feed_id": second_feed_id},
        "feed_toggle_whitelist_all": lambda: {
            "feed_id": feed_id,
            "new_status": False,
        },
        "feed_create_dev_test_feed": lambda: {
            "rss_url": "https://dev-parity.example.invalid/feed.xml",
            "title": "Synthetic developer feed",
            "description": "Small differential fixture",
            "post_count": 2,
            "guid_prefix": "parity-dev",
            "download_url_prefix": "https://dev-parity.example.invalid/audio",
        },
        "feed_delete_cascade": lambda: {"feed_id": feed_id},
        "feed_create_access_token": lambda: {
            "user_id": user_id,
            "feed_id": second_feed_id,
        },
        "feed_touch_access_token": lambda: {
            "token_id": token_id,
            "secret": "synthetic-parity-touch-secret",
        },
    }
    try:
        return factories[case_id]()
    except KeyError:
        raise AssertionError(
            f"No feed action parameters defined for {case_id}"
        ) from None


def build_writer_feed_case(
    case_id: str, pair: WriterParityPair
) -> tuple[dict[str, Any], WriteCommand]:
    case = next(
        record for record in WRITER_DIFFERENTIAL_CASES if record["case_id"] == case_id
    )
    params = _params(case_id, pair)
    rust_operation = {"operation": "action", "action": case["action"], "params": params}
    python_command = WriteCommand(
        id=f"parity-{case_id}",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": case["action"], "params": params},
    )
    return rust_operation, python_command


def _rows_by_table(backend: Any) -> dict[str, list[dict[str, Any]]]:
    with sqlite3.connect(backend.db_path) as connection:
        connection.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables_as_dicts = {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in tables
        }
    for rows in tables_as_dicts.values():
        for row in rows:
            for field in ("unprocessed_audio_path", "processed_audio_path"):
                value = row.get(field)
                if isinstance(value, str):
                    try:
                        row[field] = str(Path(value).relative_to(backend.instance_dir))
                    except ValueError:
                        pass
    return tables_as_dicts


def _replace_stage_history_timestamps(value: Any) -> Any:
    if isinstance(value, list):
        return [_replace_stage_history_timestamps(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                "<timestamp>"
                if isinstance(item, str)
                and key in {"started_at", "completed_at", "timestamp"}
                else _replace_stage_history_timestamps(item)
            )
            for key, item in value.items()
        }
    return value


def _assert_db_equal(  # noqa: PLR0912 - normalization is parameterized by table/row semantics
    observation: dict[str, Any],
    *,
    ignored_fields: dict[str, set[str]] | None = None,
    ignored_row_predicates: dict[str, Callable[[dict[str, Any]], bool]] | None = None,
    generated_job_prefix: str | None = None,
    generated_token_ids: set[str] | None = None,
) -> None:
    pair: WriterParityPair = observation["pair"]
    left = _rows_by_table(pair.python)
    right = _rows_by_table(pair.rust)
    ignored_fields = ignored_fields or {}
    ignored_row_predicates = ignored_row_predicates or {}
    for rows in (left, right):
        for table, fields in ignored_fields.items():
            for row in rows.get(table, []):
                predicate = ignored_row_predicates.get(table)
                if predicate is not None and not predicate(row):
                    continue
                if table == "feed_access_token" and generated_token_ids is not None:
                    if row.get("token_id") not in generated_token_ids:
                        continue
                for field in fields:
                    if field in row:
                        row[field] = f"<nondeterministic:{table}.{field}>"
        if generated_job_prefix:
            for row in rows.get("processing_job", []):
                if not str(row.get("post_guid", "")).startswith(generated_job_prefix):
                    continue
                uuid.UUID(str(row["id"]))
                for field in ("id", "created_at", "started_at", "completed_at"):
                    if field in row:
                        row[field] = f"<nondeterministic:processing_job.{field}>"
                history = row.get("stage_history")
                if isinstance(history, str):
                    try:
                        row["stage_history"] = json.dumps(
                            _replace_stage_history_timestamps(json.loads(history)),
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    except json.JSONDecodeError as error:
                        raise AssertionError(
                            "processing-job stage_history is invalid JSON"
                        ) from error
    if left != right:
        differences = []
        differing_table_count = 0
        for table in sorted(left.keys() | right.keys()):
            python_rows = left.get(table, [])
            rust_rows = right.get(table, [])
            if python_rows == rust_rows:
                continue
            differing_table_count += 1

            row_differences = []
            for index, (python_row, rust_row) in enumerate(
                zip(python_rows, rust_rows, strict=False)
            ):
                if python_row == rust_row:
                    continue
                if isinstance(python_row, dict) and isinstance(rust_row, dict):
                    fields = sorted(
                        field
                        for field in python_row.keys() | rust_row.keys()
                        if python_row.get(field) != rust_row.get(field)
                    )
                    row_differences.append(f"row[{index}] fields={fields[:10]}")
                else:
                    row_differences.append(f"row[{index}] differs")
                if len(row_differences) == 3:
                    break

            if len(python_rows) != len(rust_rows):
                row_differences.append(
                    f"remaining rows: Python={len(python_rows)}, Rust={len(rust_rows)}"
                )
            details = ", ".join(row_differences) or "row ordering differs"
            differences.append(f"{table}: {details}")
            if len(differences) == 8:
                break

        suffix = "; ".join(differences)
        if differing_table_count > len(differences):
            suffix += "; additional differing tables omitted"
        raise AssertionError(f"feed writer persisted table rows differ: {suffix}")


def _assert_timestamp(value: Any) -> None:
    assert isinstance(value, str) and value
    datetime.fromisoformat(value.replace(" ", "T", 1))


def assert_writer_feed_parity(  # noqa: PLR0912 - action-specific semantic assertions
    observation: dict[str, Any],
) -> None:
    case = observation["case"]
    case_id = case["case_id"]
    assert observation["python_success"] is True, observation["python_error"]
    assert observation["rust_success"] is True, observation["rust_error"]

    if case_id == "feed_refresh_existing_post_and_metadata":
        assert observation["python_data"] == observation["rust_result"]
        assert observation["python_data"] == {
            "feed_id": 201,
            "new_posts_count": 0,
            "updated_posts_count": 1,
        }
        _assert_db_equal(
            observation,
            ignored_fields={"feed": {"last_changed_at"}},
            ignored_row_predicates={"feed": lambda row: row["id"] == 201},
        )
        for backend in (observation["pair"].python, observation["pair"].rust):
            tables = _rows_by_table(backend)
            feed = next(row for row in tables["feed"] if row["id"] == 201)
            post = next(row for row in tables["post"] if row["id"] == 301)
            assert feed["description"] == "Updated by differential parity"
            assert post["title"] == "Refreshed parity episode"
            assert post["duration"] == 3600.25
            _assert_timestamp(feed["last_changed_at"])
        return

    if case_id == "feed_add_with_post_defaults":
        assert observation["python_data"] == observation["rust_result"]
        _assert_db_equal(
            observation,
            ignored_fields={"feed": {"last_changed_at"}},
            ignored_row_predicates={
                "feed": lambda row: (
                    row["rss_url"] == "https://added.example.invalid/parity.xml"
                )
            },
        )
        for backend in (observation["pair"].python, observation["pair"].rust):
            tables = _rows_by_table(backend)
            created_feed = next(
                row
                for row in tables["feed"]
                if row["rss_url"] == "https://added.example.invalid/parity.xml"
            )
            added_post = next(
                row for row in tables["post"] if row["guid"] == "parity-added-feed-post"
            )
            assert created_feed["ad_detection_strategy"] == "llm"
            assert created_feed["enable_profanity_bleeping"] is False or (
                created_feed["enable_profanity_bleeping"] == 0
            )
            assert added_post["duration"] == 123.5
            assert added_post["whitelisted"] is False or added_post["whitelisted"] == 0
            _assert_timestamp(created_feed["last_changed_at"])
        return

    if case_id == "feed_ensure_membership":
        assert (
            observation["python_data"]
            == observation["rust_result"]
            == {
                "created": True,
                "previous_count": 0,
            }
        )
        _assert_db_equal(
            observation,
            ignored_fields={"feed_supporter": {"created_at"}},
            ignored_row_predicates={
                "feed_supporter": lambda row: (
                    row["feed_id"] == 202
                    and row["user_id"] == observation["pair"].manifest.user_id
                )
            },
        )
        for backend in (observation["pair"].python, observation["pair"].rust):
            membership = next(
                row
                for row in _rows_by_table(backend)["feed_supporter"]
                if row["feed_id"] == 202 and row["user_id"] == 101
            )
            _assert_timestamp(membership["created_at"])
        return

    if case_id == "feed_create_dev_test_feed":
        assert observation["python_data"] == observation["rust_result"]
        _assert_db_equal(
            observation,
            ignored_fields={"feed": {"last_changed_at"}, "post": {"release_date"}},
            ignored_row_predicates={
                "feed": lambda row: (
                    row["rss_url"] == "https://dev-parity.example.invalid/feed.xml"
                ),
                "post": lambda row: row["guid"].startswith("parity-dev-"),
            },
            generated_job_prefix="parity-dev-",
        )
        feed_id = observation["python_data"]["feed_id"]
        feeds = _rows_by_table(observation["pair"].python)
        jobs = [
            row
            for row in feeds["processing_job"]
            if row["post_guid"].startswith(f"parity-dev-{feed_id}-")
        ]
        assert len(jobs) == 2
        for job in jobs:
            assert job["status"] == "completed"
            assert job["current_step"] == 4
            _assert_timestamp(job["created_at"])
            _assert_timestamp(job["started_at"])
            _assert_timestamp(job["completed_at"])
        for backend in (observation["pair"].python, observation["pair"].rust):
            tables = _rows_by_table(backend)
            feed = next(
                row
                for row in tables["feed"]
                if row["rss_url"] == "https://dev-parity.example.invalid/feed.xml"
            )
            _assert_timestamp(feed["last_changed_at"])
            dev_posts = [
                row
                for row in tables["post"]
                if row["guid"].startswith(f"parity-dev-{feed_id}-")
            ]
            assert len(dev_posts) == 2
            assert all(row["whitelisted"] for row in dev_posts)
            assert all(row["duration"] == 3600 for row in dev_posts)
            dev_jobs = [
                row
                for row in tables["processing_job"]
                if row["post_guid"].startswith(f"parity-dev-{feed_id}-")
            ]
            assert len(dev_jobs) == 2
            assert all(row["status"] == "completed" for row in dev_jobs)
        return

    if case_id == "feed_create_access_token":
        left_result = observation["python_data"]
        right_result = observation["rust_result"]
        assert set(left_result) == set(right_result) == {"token_id", "secret"}
        for backend, result in (
            (observation["pair"].python, left_result),
            (observation["pair"].rust, right_result),
        ):
            uuid.UUID(hex=result["token_id"])
            assert re.fullmatch(r"[A-Za-z0-9_-]{24}", result["secret"])
            token_row = next(
                row
                for row in _rows_by_table(backend)["feed_access_token"]
                if row["token_id"] == result["token_id"]
            )
            assert token_row["token_secret"] == result["secret"]
            assert (
                token_row["token_hash"]
                == hashlib.sha256(result["secret"].encode()).hexdigest()
            )
            assert token_row["user_id"] == observation["pair"].manifest.user_id
            assert token_row["feed_id"] == observation["pair"].manifest.feed_ids[1]
            assert token_row["revoked"] is False or token_row["revoked"] == 0
            assert token_row["last_used_at"] is None
            _assert_timestamp(token_row["created_at"])
        _assert_db_equal(
            observation,
            ignored_fields={
                "feed_access_token": {
                    "token_id",
                    "token_hash",
                    "token_secret",
                    "created_at",
                }
            },
            generated_token_ids={
                left_result["token_id"],
                right_result["token_id"],
            },
        )
        return

    if case_id == "feed_touch_access_token":
        assert (
            observation["python_data"]
            == observation["rust_result"]
            == {"updated": True}
        )
        _assert_db_equal(
            observation,
            ignored_fields={"feed_access_token": {"last_used_at"}},
            ignored_row_predicates={
                "feed_access_token": lambda row: (
                    row["token_id"] == observation["pair"].manifest.token_ids[0]
                )
            },
        )
        for backend in (observation["pair"].python, observation["pair"].rust):
            token_row = next(
                row
                for row in _rows_by_table(backend)["feed_access_token"]
                if row["token_id"] == observation["pair"].manifest.token_ids[0]
            )
            _assert_timestamp(token_row["last_used_at"])
        return

    assert observation["python_data"] == observation["rust_result"], {
        "case_id": case_id,
        "python": observation["python_data"],
        "rust": observation["rust_result"],
    }
    assert observation["python_rows"] == observation["rust_rows"], (
        f"feed writer persisted table rows differ for {case_id}"
    )
    tables = _rows_by_table(observation["pair"].python)
    if case_id == "feed_update_settings":
        assert next(row for row in tables["feed"] if row["id"] == 202)[
            "auto_whitelist_new_episodes_override"
        ] in (True, 1)
    elif case_id == "feed_increment_download_count":
        assert (
            next(row for row in tables["post"] if row["id"] == 301)["download_count"]
            == 3
        )
    elif case_id == "feed_whitelist_post":
        assert next(row for row in tables["post"] if row["id"] == 302)[
            "whitelisted"
        ] in (True, 1)
    elif case_id == "feed_remove_membership":
        assert not any(
            row["feed_id"] == 201 and row["user_id"] == 101
            for row in tables["feed_supporter"]
        )
    elif case_id == "feed_whitelist_latest_post":
        assert next(row for row in tables["post"] if row["id"] == 302)[
            "whitelisted"
        ] in (True, 1)
    elif case_id == "feed_toggle_whitelist_all":
        assert all(
            not row["whitelisted"] for row in tables["post"] if row["feed_id"] == 201
        )
    elif case_id == "feed_delete_cascade":
        assert not any(row["id"] == 201 for row in tables["feed"])
        assert not any(row["feed_id"] == 201 for row in tables["post"])
        assert not any(row["feed_id"] == 201 for row in tables["feed_access_token"])
