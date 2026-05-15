from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from app import create_processing_app
from app.db_guard import db_guard
from app.extensions import db
from app.models import Post, ProcessingJob
from podcast_processor.processing_status_manager import ProcessingStatusManager

logger = logging.getLogger("global_logger")

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "skipped"}


class Processor(Protocol):
    def process(
        self,
        post: Post,
        *,
        job_id: str,
        cancel_callback: Callable[[], bool],
    ) -> None: ...


ProcessorFactory = Callable[[], Processor]


def _default_processor_factory() -> Processor:
    from app.runtime_config import config
    from podcast_processor.podcast_processor import PodcastProcessor

    return cast(Processor, PodcastProcessor(config))


def _is_terminal(job: ProcessingJob | None) -> bool:
    return job is None or job.status in TERMINAL_JOB_STATUSES


def _mark_failed(
    status_manager: ProcessingStatusManager,
    job: ProcessingJob,
    message: str,
) -> None:
    status_manager.update_job_status(
        job,
        "failed",
        job.current_step or 0,
        message,
        job.progress_percentage or 0.0,
    )


def run_processing_job(
    job_id: str,
    post_guid: str,
    *,
    processor_factory: ProcessorFactory | None = None,
) -> int:
    app = create_processing_app()
    factory = processor_factory or _default_processor_factory

    with app.app_context():
        status_manager = ProcessingStatusManager(db_session=db.session, logger=logger)
        with db_guard("processing_worker", db.session, logger):
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass

            try:
                db.session.expire_all()
                job = db.session.get(ProcessingJob, job_id)
                post = Post.query.filter_by(guid=post_guid).first()

                if not job:
                    logger.error(
                        "Processing worker cannot find job: job_id=%s post_guid=%s",
                        job_id,
                        post_guid,
                    )
                    return 1

                if not post:
                    logger.error(
                        "Processing worker cannot find post: job_id=%s post_guid=%s",
                        job_id,
                        post_guid,
                    )
                    _mark_failed(status_manager, job, "Post not found")
                    return 1

                def _cancelled() -> bool:
                    db.session.expire_all()
                    current_job = db.session.get(ProcessingJob, job_id)
                    return current_job is None or current_job.status == "cancelled"

                logger.info(
                    "Processing worker starting job_id=%s post_guid=%s",
                    job_id,
                    post_guid,
                )
                factory().process(post, job_id=job_id, cancel_callback=_cancelled)
                logger.info(
                    "Processing worker finished job_id=%s post_guid=%s",
                    job_id,
                    post_guid,
                )
                return 0
            except Exception as exc:
                db.session.expire_all()
                current_job = db.session.get(ProcessingJob, job_id)
                if _is_terminal(current_job):
                    logger.info(
                        "Processing worker exiting after terminal job state: "
                        "job_id=%s status=%s error=%s",
                        job_id,
                        None if current_job is None else current_job.status,
                        exc,
                    )
                    return 0

                logger.error(
                    "Processing worker failed job_id=%s post_guid=%s: %s",
                    job_id,
                    post_guid,
                    exc,
                    exc_info=True,
                )
                if current_job is not None:
                    _mark_failed(
                        status_manager, current_job, f"Job execution failed: {exc}"
                    )
                return 1
            finally:
                try:
                    db.session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    db.session.remove()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to remove processing worker session: %s", exc
                    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Podly processing job.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--post-guid", required=True)
    args = parser.parse_args(argv)
    return run_processing_job(args.job_id, args.post_guid)


if __name__ == "__main__":
    raise SystemExit(main())
