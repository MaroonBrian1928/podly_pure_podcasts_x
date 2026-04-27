from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Iterator, Sized
from itertools import batched

logger = logging.getLogger("global_logger")

DEFAULT_WRITER_BATCH_SIZE = 500


def get_writer_batch_size() -> int:
    raw = os.environ.get("PODLY_WRITER_BATCH_SIZE")
    if raw is None:
        return DEFAULT_WRITER_BATCH_SIZE
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid PODLY_WRITER_BATCH_SIZE=%r; using %s",
            raw,
            DEFAULT_WRITER_BATCH_SIZE,
        )
        return DEFAULT_WRITER_BATCH_SIZE
    return max(1, value)


def iter_writer_batches[T](
    values: Iterable[T],
    *,
    batch_size: int | None = None,
) -> Iterator[tuple[T, ...]]:
    yield from batched(values, batch_size or get_writer_batch_size(), strict=False)


def batch_count_for(total_count: int, *, batch_size: int | None = None) -> int:
    size = batch_size or get_writer_batch_size()
    if total_count <= 0:
        return 0
    return (total_count + size - 1) // size


def sized_count(values: Iterable[object]) -> int | None:
    return len(values) if isinstance(values, Sized) else None
