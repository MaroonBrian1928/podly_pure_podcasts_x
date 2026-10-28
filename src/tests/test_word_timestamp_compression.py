import json
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified

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


def test_only_large_text_rows_are_rewritten_through_the_writer(
    app, monkeypatch
) -> None:
    from app.writer.client import writer_client

    with app.app_context():
        large = _post("large", json.dumps(LARGE))
        small = _post("small", json.dumps([{"sequence_num": 0, "words": []}]))
        cleared = _post("cleared", "null")
        never_set = _post("never", None)
        written: list[tuple[int, Any]] = []

        def fake_update(model: str, post_id: int, data: dict[str, Any], wait: bool):
            written.append((post_id, data["transcript_word_timestamps"]))
            post = db.session.get(Post, post_id)
            assert post is not None
            post.transcript_word_timestamps = data["transcript_word_timestamps"]
            flag_modified(post, "transcript_word_timestamps")
            db.session.commit()
            return SimpleNamespace(success=True)

        monkeypatch.setattr(writer_client, "update", fake_update)

        dry = compress_word_timestamps(apply=False)
        assert dry == {
            "apply": False,
            "candidates": 1,
            "compressed": 0,
            "unchanged": 0,
            "failed": 0,
        }
        assert written == []

        result = compress_word_timestamps(apply=True, pause=0)

        assert result["compressed"] == 1 and result["failed"] == 0
        assert written == [(large, LARGE)]
        assert _typeof(large) == "blob"
        assert [_typeof(i) for i in (small, cleared)] == ["text", "text"]
        assert _typeof(never_set) == "null"

        again = compress_word_timestamps(apply=True, pause=0)
        assert again["candidates"] == 0


def test_failed_writes_are_counted_and_the_row_is_left_alone(app, monkeypatch) -> None:
    from app.writer.client import writer_client

    with app.app_context():
        post_id = _post("large", json.dumps(LARGE))
        monkeypatch.setattr(
            writer_client,
            "update",
            lambda *args, **kwargs: SimpleNamespace(success=False),
        )

        result = compress_word_timestamps(apply=True, pause=0)

        assert result["failed"] == 1 and result["compressed"] == 0
        assert _typeof(post_id) == "text"
