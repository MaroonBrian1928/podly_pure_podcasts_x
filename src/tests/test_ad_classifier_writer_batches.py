from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from podcast_processor import ad_classifier as ad_classifier_module
from podcast_processor.ad_classifier import AdClassifier
from shared.test_utils import create_standard_test_config


def _classifier() -> AdClassifier:
    return AdClassifier(
        create_standard_test_config(),
        logging.getLogger("test"),
        model_call_query=MagicMock(),
        identification_query=MagicMock(),
        db_session=MagicMock(),
    )


def test_insert_identifications_uses_writer_batches(monkeypatch) -> None:
    monkeypatch.setenv("PODLY_WRITER_BATCH_SIZE", "2")
    calls: list[tuple[str, dict]] = []

    def fake_action(action_name: str, params: dict, wait: bool = True):
        del wait
        calls.append((action_name, params))
        return SimpleNamespace(
            success=True,
            data={"inserted": len(params.get("identifications", []))},
        )

    monkeypatch.setattr(ad_classifier_module.writer_client, "action", fake_action)

    classifier = _classifier()
    inserted = classifier._insert_identifications_batched(
        [
            {"transcript_segment_id": 1, "model_call_id": 1, "label": "ad"},
            {"transcript_segment_id": 2, "model_call_id": 1, "label": "ad"},
            {"transcript_segment_id": 3, "model_call_id": 1, "label": "ad"},
        ]
    )

    assert inserted == 3
    assert [name for name, _params in calls] == [
        "insert_identifications",
        "insert_identifications",
    ]
    assert [len(params["identifications"]) for _name, params in calls] == [2, 1]


def test_replace_identifications_deletes_once_then_inserts_batches(monkeypatch) -> None:
    monkeypatch.setenv("PODLY_WRITER_BATCH_SIZE", "2")
    calls: list[tuple[str, dict]] = []

    def fake_action(action_name: str, params: dict, wait: bool = True):
        del wait
        calls.append((action_name, params))
        return SimpleNamespace(
            success=True,
            data={"inserted": len(params.get("identifications", []))},
        )

    monkeypatch.setattr(ad_classifier_module.writer_client, "action", fake_action)

    classifier = _classifier()
    inserted = classifier._replace_identifications_batched(
        delete_ids=[10, 11],
        new_identifications=[
            {"transcript_segment_id": 1, "model_call_id": 1, "label": "ad"},
            {"transcript_segment_id": 2, "model_call_id": 1, "label": "ad"},
            {"transcript_segment_id": 3, "model_call_id": 1, "label": "ad"},
        ],
    )

    assert inserted == 3
    assert [name for name, _params in calls] == [
        "replace_identifications",
        "insert_identifications",
        "insert_identifications",
    ]
    assert calls[0][1] == {"delete_ids": [10, 11], "new_identifications": []}
    assert [len(params.get("identifications", [])) for _name, params in calls[1:]] == [
        2,
        1,
    ]
