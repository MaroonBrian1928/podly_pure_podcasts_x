"""One-off job: gzip word timestamps stored as plain JSON text.

New values are compressed when written (``CompressedJSON`` in Python, the Rust
writer's ``word_blob``). Rows saved by earlier releases stay as text until this
job rewrites them through the writer. SQLite keeps the freed pages inside the
file, so run ``VACUUM`` afterwards to shrink it on disk.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text

# Matches the writer's threshold: shorter values are stored as text.
MIN_TEXT_BYTES = 1024
PAUSE_BETWEEN_ROWS_SECONDS = 0.05

logger = logging.getLogger("global_logger")


def compress_word_timestamps(
    *, apply: bool, limit: int | None = None, pause: float = PAUSE_BETWEEN_ROWS_SECONDS
) -> dict[str, Any]:
    from app.extensions import db
    from app.writer.client import writer_client

    ids = [
        row[0]
        for row in db.session.execute(
            text(
                "SELECT id FROM post "
                "WHERE typeof(transcript_word_timestamps) = 'text' "
                "AND length(transcript_word_timestamps) >= :min_bytes "
                "AND transcript_word_timestamps != 'null' "
                "ORDER BY id LIMIT :limit"
            ),
            {"min_bytes": MIN_TEXT_BYTES, "limit": limit if limit else -1},
        )
    ]
    result: dict[str, Any] = {
        "apply": apply,
        "candidates": len(ids),
        "compressed": 0,
        "unchanged": 0,
        "failed": 0,
    }
    if not apply:
        return result

    for post_id in ids:
        try:
            write = writer_client.action(
                "compress_post_word_timestamps", {"post_id": post_id}, wait=True
            )
        except Exception:
            logger.exception("Word timestamp compression failed for post %s", post_id)
            result["failed"] += 1
            continue
        if not write or not write.success:
            result["failed"] += 1
        elif (write.data or {}).get("compressed"):
            result["compressed"] += 1
        else:
            result["unchanged"] += 1
        if pause:
            time.sleep(pause)
    if result["compressed"]:
        logger.info(
            "Compressed word timestamps for %d posts; run VACUUM to shrink the "
            "database file",
            result["compressed"],
        )
    return result
