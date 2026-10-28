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


def _stored_as_blob(post_id: int) -> bool:
    from app.extensions import db

    return (
        db.session.execute(
            text("SELECT typeof(transcript_word_timestamps) FROM post WHERE id = :id"),
            {"id": post_id},
        ).scalar()
        == "blob"
    )


def compress_word_timestamps(
    *, apply: bool, limit: int | None = None, pause: float = PAUSE_BETWEEN_ROWS_SECONDS
) -> dict[str, Any]:
    from app.extensions import db
    from app.models import Post
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
        post = db.session.get(Post, post_id)
        words = post.transcript_word_timestamps if post is not None else None
        db.session.expire_all()
        if words is None:
            continue
        write = writer_client.update(
            "Post", post_id, {"transcript_word_timestamps": words}, wait=True
        )
        if not write or not write.success:
            result["failed"] += 1
        elif _stored_as_blob(post_id):
            result["compressed"] += 1
        else:
            # A writer that skips no-op updates (the Python fallback) leaves it.
            result["unchanged"] += 1
        del words
        if pause:
            time.sleep(pause)
    if result["compressed"]:
        logger.info(
            "Compressed word timestamps for %d posts; run VACUUM to shrink the "
            "database file",
            result["compressed"],
        )
    return result
