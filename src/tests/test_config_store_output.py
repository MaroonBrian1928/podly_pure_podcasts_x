from typing import Any

from app.models import OutputSettings
from shared import defaults as DEFAULTS


def test_output_config_exposes_bleep_padding_defaults(app: Any) -> None:
    with app.app_context():
        app.config["PODLY_APP_ROLE"] = "writer"

        from app.config_store import read_combined

        payload = read_combined()

    assert payload["output"]["bleep_padding_start_ms"] == (
        DEFAULTS.OUTPUT_BLEEP_PADDING_START_MS
    )
    assert payload["output"]["bleep_padding_end_ms"] == (
        DEFAULTS.OUTPUT_BLEEP_PADDING_END_MS
    )


def test_output_config_updates_bleep_padding(app: Any) -> None:
    with app.app_context():
        app.config["PODLY_APP_ROLE"] = "writer"

        from app.config_store import read_combined, update_combined

        read_combined()
        payload = update_combined(
            {
                "output": {
                    "bleep_padding_start_ms": 90,
                    "bleep_padding_end_ms": 220,
                }
            }
        )
        row = OutputSettings.query.get(1)
        assert row is not None
        row_start_ms = row.bleep_padding_start_ms
        row_end_ms = row.bleep_padding_end_ms

    assert payload["output"]["bleep_padding_start_ms"] == 90
    assert payload["output"]["bleep_padding_end_ms"] == 220
    assert row_start_ms == 90
    assert row_end_ms == 220
