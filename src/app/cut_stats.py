"""Cut-window helpers shared by the stats endpoint and the backfill command."""

from __future__ import annotations

from typing import Any

from app.models import Post

CUT_STATS_BACKFILLED = "backfilled"
CUT_STATS_RECORDED = "recorded"
CUT_STATS_UNVERIFIED = "unverified"


def stored_cut_windows(post: Post) -> tuple[list[tuple[float, float]], float] | None:
    """Return the windows and source length the cutter recorded, if any.

    ``removed_ad_windows`` of None (SQL NULL or JSON null) means nothing was
    recorded; an empty list means the cutter removed nothing.
    """
    windows = post.removed_ad_windows
    original = post.original_duration_seconds
    if windows is None or original is None or not isinstance(windows, list):
        return None
    parsed: list[tuple[float, float]] = []
    for item in windows:
        try:
            parsed.append((float(item[0]), float(item[1])))
        except TypeError, ValueError, IndexError, KeyError:
            continue
    return parsed, float(original)


def merge_like_cutter(
    audio_processor: Any,
    runtime_config: Any,
    ad_blocks: list[tuple[float, float]],
    duration_seconds: float,
) -> list[tuple[float, float]]:
    """Apply the cutter's merge to ad blocks, returning second-based windows."""
    merged_ms = audio_processor.merge_ad_segments(
        duration_ms=round(duration_seconds * 1000),
        ad_segments=ad_blocks,
        min_ad_segment_length_seconds=float(
            runtime_config.output.min_ad_segment_length_seconds
        ),
        min_ad_segment_separation_seconds=float(
            runtime_config.output.min_ad_segement_separation_seconds
        ),
    )
    return [(start / 1000.0, end / 1000.0) for start, end in merged_ms]


MISMATCH_TOLERANCE_SECONDS = 1.0


def _transcript_end_seconds(post: Post) -> float:
    from sqlalchemy import func

    from app.extensions import db
    from app.models import TranscriptSegment

    end = (
        db.session.query(func.max(TranscriptSegment.end_time))
        .filter(TranscriptSegment.post_id == post.id)
        .scalar()
    )
    return float(end or 0.0)


def rebuild_recorded_windows(
    post: Post,
    audio_processor: Any,
    runtime_config: Any,
    original_seconds: float,
) -> list[tuple[float, float]]:
    """Rebuild the windows the cutter would have removed, with the fade inset."""
    ad_blocks = audio_processor.get_ad_segments(post)
    if not ad_blocks:
        return []
    merged = merge_like_cutter(
        audio_processor, runtime_config, ad_blocks, original_seconds
    )
    fade_ms = int(runtime_config.output.fade_ms)
    effective_ms = audio_processor._effective_removed_windows(
        [(round(start * 1000), round(end * 1000)) for start, end in merged], fade_ms
    )
    return [(start / 1000.0, end / 1000.0) for start, end in effective_ms]


def backfill_cut_windows(*, apply: bool) -> dict[str, Any]:
    """Store reconstructed cut windows for processed posts that lack them."""
    import logging

    from app.extensions import db
    from app.runtime_config import config as runtime_config
    from app.writer.client import writer_client
    from podcast_processor.audio_processor import AudioProcessor

    audio_processor = AudioProcessor(
        config=runtime_config,
        logger=logging.getLogger("global_logger"),
        db_session=db.session,
    )
    result: dict[str, Any] = {
        "apply": apply,
        "checked": 0,
        "stored": 0,
        "skipped_mismatch": 0,
        "skipped_no_transcript": 0,
        "skipped_no_duration": 0,
        "failed_writes": 0,
    }
    mismatches: list[tuple[float, str]] = []

    def mark_unverified(post: Post) -> None:
        if not apply:
            return
        write = writer_client.update(
            "Post",
            post.id,
            {
                "removed_ad_windows": None,
                "original_duration_seconds": None,
                "cut_stats_source": CUT_STATS_UNVERIFIED,
            },
            wait=True,
        )
        if not write or not write.success:
            result["failed_writes"] += 1

    candidates = (
        Post.query.filter(
            Post.processed_audio_path.isnot(None),
            Post.cut_stats_source.is_(None),
        )
        .order_by(Post.id)
        .all()
    )
    for post in candidates:
        if post.removed_ad_windows is not None:
            continue
        result["checked"] += 1
        if not post.duration or post.duration <= 0:
            result["skipped_no_duration"] += 1
            mark_unverified(post)
            continue
        original = _transcript_end_seconds(post)
        if original <= 0:
            result["skipped_no_transcript"] += 1
            mark_unverified(post)
            continue
        windows = rebuild_recorded_windows(
            post, audio_processor, runtime_config, original
        )
        removed = sum(end - start for start, end in windows if end > start)
        gap = original - removed - float(post.duration)
        if abs(gap) > MISMATCH_TOLERANCE_SECONDS:
            result["skipped_mismatch"] += 1
            mismatches.append((abs(gap), post.title))
            mark_unverified(post)
            continue
        if apply:
            write = writer_client.update(
                "Post",
                post.id,
                {
                    "removed_ad_windows": [
                        [round(start, 3), round(end, 3)] for start, end in windows
                    ],
                    "original_duration_seconds": round(original, 3),
                    "cut_stats_source": CUT_STATS_BACKFILLED,
                },
                wait=True,
            )
            if not write or not write.success:
                result["failed_writes"] += 1
                continue
        result["stored"] += 1

    mismatches.sort(key=lambda item: item[0], reverse=True)
    result["largest_mismatches"] = [
        {"title": title, "gap_seconds": round(gap, 1)} for gap, title in mismatches[:10]
    ]
    return result


def register_cli(app: Any) -> None:
    import json

    import click

    @app.cli.command("backfill-cut-windows")
    @click.option(
        "--apply/--dry-run",
        "apply",
        default=False,
        help="Write rebuilt windows through the writer service (default: dry run).",
    )
    def backfill_cut_windows_command(apply: bool) -> None:
        """Store rebuilt cut windows for processed posts that lack them."""
        click.echo(json.dumps(backfill_cut_windows(apply=apply), indent=2))
