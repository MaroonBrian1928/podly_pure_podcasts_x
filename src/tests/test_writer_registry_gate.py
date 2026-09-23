from __future__ import annotations

from scripts.check_writer_registry import case_mapping_failure


def test_case_mapping_requires_a_differential_case() -> None:
    assert (
        case_mapping_failure(
            "create_user", None, {}, set(), "action", action="create_user"
        )
        == "create_user: production-reachable operation has no mapped differential parity case"
    )


def test_case_mapping_requires_a_case_consumed_by_the_differential_runner() -> None:
    cases = {
        "update_post_title": {
            "case_id": "update_post_title",
            "operation": "update",
            "model": "Post",
        }
    }
    assert (
        case_mapping_failure(
            "update:Post", "update_post_title", cases, set(), "update", model="Post"
        )
        == "update:Post: parity case 'update_post_title' is not registered and executed by the differential test"
    )


def test_case_mapping_checks_the_actual_operation_action_and_model() -> None:
    cases = {
        "update_post_title": {
            "case_id": "update_post_title",
            "operation": "update",
            "model": "Post",
        }
    }
    executed = {"update_post_title"}
    assert (
        case_mapping_failure(
            "create_user",
            "update_post_title",
            cases,
            executed,
            "action",
            action="create_user",
        )
        == "create_user: mapped parity case 'update_post_title' covers a different operation"
    )
    assert (
        case_mapping_failure(
            "update:Feed", "update_post_title", cases, executed, "update", model="Feed"
        )
        == "update:Feed: mapped parity case 'update_post_title' covers a different model"
    )


def test_case_mapping_accepts_an_executed_matching_case() -> None:
    cases = {
        "create_user": {
            "case_id": "create_user",
            "operation": "action",
            "action": "create_user",
        }
    }
    assert (
        case_mapping_failure(
            "create_user",
            "create_user",
            cases,
            {"create_user"},
            "action",
            action="create_user",
        )
        is None
    )
