import json
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text

from app.extensions import db
from app.models import Feed, Post
from app.word_timestamp_compression import compress_word_timestamps

LARGE = [{"sequence_num": 0, "words": [{"word": "hi", "start": 1.0, "end": 1.5}] * 400}]


def _post(guid: str, raw: str | None) -> int:
    feed = Feed(title=guid, rss_url=f"https://example.com/{guid}.xml")
    db.session.add(feed)
    db.session.flush()
    post = Post(
        feed_id=feed.id, guid=guid, title=guid, download_url=f"https://e/{guid}"
    )
    db.session.add(post)
    db.session.commit()
    db.session.execute(
        text("UPDATE post SET transcript_word_timestamps=:v WHERE id=:id"),
        {"v": raw, "id": post.id},
    )
    db.session.commit()
    return post.id


def _typeof(post_id: int) -> str:
    return db.session.execute(
        text("SELECT typeof(transcript_word_timestamps) FROM post WHERE id=:id"),
        {"id": post_id},
    ).scalar_one()


def _run_action(monkeypatch, fail_for: set[int] | None = None) -> list[int]:
    """Route the job's writer calls to the real Python writer action."""
    from app.writer.actions import compress_post_word_timestamps_action
    from app.writer.client import writer_client

    calls: list[int] = []

    def fake_action(name: str, params: dict[str, Any], wait: bool = True):
        assert name == "compress_post_word_timestamps"
        post_id = params["post_id"]
        calls.append(post_id)
        if fail_for and post_id in fail_for:
            raise RuntimeError("request too large")
        data = compress_post_word_timestamps_action(params)
        db.session.commit()
        return SimpleNamespace(success=True, data=data)

    monkeypatch.setattr(writer_client, "action", fake_action)
    return calls


def test_only_large_text_rows_are_compressed(app, monkeypatch) -> None:
    with app.app_context():
        large = _post("large", json.dumps(LARGE))
        small = _post("small", json.dumps([{"sequence_num": 0, "words": []}]))
        cleared = _post("cleared", "null")
        never_set = _post("never", None)
        calls = _run_action(monkeypatch)

        dry = compress_word_timestamps(apply=False)
        assert dry == {
            "apply": False,
            "candidates": 1,
            "compressed": 0,
            "unchanged": 0,
            "failed": 0,
        }
        assert calls == []

        result = compress_word_timestamps(apply=True, pause=0)

        assert result["compressed"] == 1 and result["failed"] == 0
        assert calls == [large]
        assert _typeof(large) == "blob"
        stored = db.session.get(Post, large)
        assert stored is not None and stored.transcript_word_timestamps == LARGE
        assert [_typeof(i) for i in (small, cleared)] == ["text", "text"]
        assert _typeof(never_set) == "null"

        again = compress_word_timestamps(apply=True, pause=0)
        assert again["candidates"] == 0


def test_job_compresses_the_value_stored_when_the_writer_runs(app, monkeypatch) -> None:
    """Words saved between the job listing a post and the writer acting survive."""
    from app.writer.actions import compress_post_word_timestamps_action
    from app.writer.client import writer_client

    newer = [
        {"sequence_num": 0, "words": [{"word": "new", "start": 1, "end": 2}] * 300}
    ]
    with app.app_context():
        post_id = _post("race", json.dumps(LARGE))

        def action_after_newer_write(
            name: str, params: dict[str, Any], wait: bool = True
        ):
            # A transcription lands (still legacy text) after the listing query.
            db.session.execute(
                text("UPDATE post SET transcript_word_timestamps=:v WHERE id=:id"),
                {"v": json.dumps(newer), "id": params["post_id"]},
            )
            data = compress_post_word_timestamps_action(params)
            db.session.commit()
            return SimpleNamespace(success=True, data=data)

        monkeypatch.setattr(writer_client, "action", action_after_newer_write)

        result = compress_word_timestamps(apply=True, pause=0)

        assert result["compressed"] == 1
        assert _typeof(post_id) == "blob"
        db.session.expire_all()
        stored = db.session.get(Post, post_id)
        assert stored is not None and stored.transcript_word_timestamps == newer


def test_action_skips_posts_that_are_missing_small_cleared_or_compressed(app) -> None:
    from app.writer.actions import compress_post_word_timestamps_action

    with app.app_context():
        ids = [
            _post("small", json.dumps([{"sequence_num": 0, "words": []}])),
            _post("cleared", "null"),
            _post("never", None),
        ]
        large = _post("large", json.dumps(LARGE))
        assert compress_post_word_timestamps_action({"post_id": large})["compressed"]
        ids.append(large)
        ids.append(999_999)

        results = [
            compress_post_word_timestamps_action({"post_id": i})["compressed"]
            for i in ids
        ]

        assert results == [False] * 5


def test_one_failing_row_does_not_stop_the_rest(app, monkeypatch) -> None:
    with app.app_context():
        first = _post("first", json.dumps(LARGE))
        second = _post("second", json.dumps(LARGE))
        _run_action(monkeypatch, fail_for={first})

        result = compress_word_timestamps(apply=True, pause=0)

        assert result["failed"] == 1 and result["compressed"] == 1
        assert _typeof(first) == "text"
        assert _typeof(second) == "blob"
