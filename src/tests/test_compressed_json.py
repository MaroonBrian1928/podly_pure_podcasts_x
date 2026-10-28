import gzip
import json

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import Feed, Post

LARGE = [{"sequence_num": 0, "words": [{"word": "hi", "start": 1.0, "end": 1.5}] * 400}]


def _post(**fields: object) -> Post:
    feed = Feed(title="f", rss_url="https://example.com/feed.xml")
    db.session.add(feed)
    db.session.flush()
    post = Post(
        feed_id=feed.id,
        guid="g",
        title="t",
        download_url="https://e.com/a.mp3",
        **fields,
    )
    db.session.add(post)
    db.session.commit()
    return post


def _read(post_id: int) -> object:
    post = db.session.get(Post, post_id)
    assert post is not None
    return post.transcript_word_timestamps


def _raw(post_id: int) -> object:
    return db.session.execute(
        text("SELECT transcript_word_timestamps FROM post WHERE id=:id"),
        {"id": post_id},
    ).scalar()


def test_large_values_are_stored_as_gzip_and_read_back(app) -> None:
    with app.app_context():
        post = _post(transcript_word_timestamps=LARGE)
        db.session.expire_all()

        raw = _raw(post.id)
        assert isinstance(raw, bytes) and raw.startswith(b"\x1f\x8b")
        assert len(raw) < len(json.dumps(LARGE)) / 4
        assert _read(post.id) == LARGE


def test_small_values_and_none_stay_plain_json_text(app) -> None:
    with app.app_context():
        post = _post(transcript_word_timestamps=[{"sequence_num": 0, "words": []}])
        assert _raw(post.id) == '[{"sequence_num": 0, "words": []}]'

        post.transcript_word_timestamps = None
        db.session.commit()
        db.session.expire_all()
        assert _raw(post.id) == "null"
        assert _read(post.id) is None


def test_unset_column_reads_as_none(app) -> None:
    with app.app_context():
        post = _post()
        assert _raw(post.id) is None
        db.session.expire_all()
        assert _read(post.id) is None


@pytest.mark.parametrize("legacy", [LARGE, [{"sequence_num": 1, "words": []}]])
def test_rows_written_before_compression_still_read(app, legacy: list) -> None:
    with app.app_context():
        post = _post()
        db.session.execute(
            text("UPDATE post SET transcript_word_timestamps=:v WHERE id=:id"),
            {"v": json.dumps(legacy, separators=(",", ":")), "id": post.id},
        )
        db.session.commit()
        db.session.expire_all()

        assert _read(post.id) == legacy


def test_blobs_from_another_gzip_encoder_read(app) -> None:
    """The Rust writer's gzip bytes differ from Python's but decode the same."""
    with app.app_context():
        post = _post()
        db.session.execute(
            text("UPDATE post SET transcript_word_timestamps=:v WHERE id=:id"),
            {"v": gzip.compress(json.dumps(LARGE).encode(), 1), "id": post.id},
        )
        db.session.commit()
        db.session.expire_all()

        assert _read(post.id) == LARGE
