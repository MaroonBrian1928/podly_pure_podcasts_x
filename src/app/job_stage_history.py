"""Helpers for maintaining ``ProcessingJob.stage_history``.

The column is a JSON list of ``{"step": int, "step_name": str, "started_at":
ISO}`` entries appended whenever a job's stage changes. Every ``ProcessingJob``
should be created with at least one initial entry so the UI can report
"time queued" for the very first stage before any status transitions happen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def initial_stage_history(
    *,
    step: int = 0,
    step_name: str | None = "Queued",
    at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return a single-entry stage history seeded at ``at`` (UTC, naive).

    Use this for every fresh ``ProcessingJob`` and for any reset path that
    sends a job back to ``pending`` so the queue wait gets measured.
    """
    seed_at = (at or datetime.now(UTC).replace(tzinfo=None)).isoformat()
    return [
        {
            "step": step,
            "step_name": step_name,
            "started_at": seed_at,
        }
    ]
