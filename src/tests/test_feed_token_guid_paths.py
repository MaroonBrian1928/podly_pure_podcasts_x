from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from flask import Flask, g

from app.auth.feed_tokens import (
    _resolve_feed_ids,
    _validate_token_access,
    find_post_for_request,
)
from app.extensions import db
from app.models import Feed, Post

# A supercast-style guid: the episode URL is used verbatim as the <guid>, so it
# contains "/", ".", "?" and "&". Flask hands the auth middleware a *decoded*
# request.path, so these characters appear raw in the path the token validator
# parses.
URL_GUID = "https://searchengine.supercast.tech/episodes/1847512?key=abc"


@pytest.fixture
def app_with_post() -> Generator[Flask]:
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        feed = Feed(title="Supercast", rss_url="https://example.com/sc.xml")
        db.session.add(feed)
        db.session.commit()
        db.session.add(
            Post(
                feed_id=feed.id,
                guid=URL_GUID,
                download_url="https://example.com/a.mp3",
                title="Episode",
                whitelisted=True,
            )
        )
        # A plain-guid post in another feed to guard the unchanged path.
        plain_feed = Feed(title="Plain", rss_url="https://example.com/plain.xml")
        db.session.add(plain_feed)
        db.session.commit()
        db.session.add(
            Post(
                feed_id=plain_feed.id,
                guid="episode-1",
                download_url="https://example.com/b.mp3",
                title="Plain Episode",
                whitelisted=True,
            )
        )
        db.session.commit()
        app.config["URL_FEED_ID"] = feed.id
        app.config["PLAIN_FEED_ID"] = plain_feed.id
        yield app
        db.session.remove()
        db.drop_all()


def test_resolve_feed_id_for_url_shaped_guid_mp3(app_with_post: Flask) -> None:
    with app_with_post.app_context():
        expected = app_with_post.config["URL_FEED_ID"]
        # Decoded path the middleware sees for /post/<encoded-guid>.mp3.
        assert _resolve_feed_ids(f"/post/{URL_GUID}.mp3") == [expected]


def test_resolve_feed_id_for_url_shaped_guid_original_mp3(
    app_with_post: Flask,
) -> None:
    with app_with_post.app_context():
        expected = app_with_post.config["URL_FEED_ID"]
        assert _resolve_feed_ids(f"/post/{URL_GUID}/original.mp3") == [expected]


def test_resolve_feed_id_for_plain_guid_unchanged(app_with_post: Flask) -> None:
    with app_with_post.app_context():
        expected = app_with_post.config["PLAIN_FEED_ID"]
        assert _resolve_feed_ids("/post/episode-1.mp3") == [expected]
        assert _resolve_feed_ids("/post/episode-1/original.mp3") == [expected]


def test_chapters_json_path_resolves_feed_and_accepts_tokens(
    app_with_post: Flask,
) -> None:
    from app.auth.middleware import _is_token_protected_endpoint

    with app_with_post.app_context():
        assert _resolve_feed_ids(f"/post/{URL_GUID}/chapters.json") == [
            app_with_post.config["URL_FEED_ID"]
        ]
        assert _resolve_feed_ids("/post/episode-1/chapters.json") == [
            app_with_post.config["PLAIN_FEED_ID"]
        ]
    assert _is_token_protected_endpoint(f"/post/{URL_GUID}/chapters.json")
    assert not _is_token_protected_endpoint("/post/episode-1/other.json")


def test_chapters_json_route_serves_podcasting_chapters(app_with_post: Flask) -> None:
    import json

    from app.routes.post_routes import post_bp

    app_with_post.register_blueprint(post_bp)
    with app_with_post.app_context():
        post = Post.query.filter_by(guid="episode-1").one()
        post.chapter_data = json.dumps(
            {
                "chapters_for_output": [
                    {"title": "Later", "start_time": 485.0},
                    {"title": "Intro", "start_time": 0.0},
                    {"title": "  ", "start_time": 10.0},
                ]
            }
        )
        db.session.commit()

    client = app_with_post.test_client()
    response = client.get("/post/episode-1/chapters.json")
    assert response.status_code == 200
    assert response.get_json() == {
        "version": "1.2.0",
        "chapters": [
            {"startTime": 0.0, "title": "Intro"},
            {"startTime": 485.0, "title": "Later"},
        ],
    }
    assert client.get("/post/missing/chapters.json").status_code == 404


def _add_post(feed_id: int, guid: str, **fields: object) -> Post:
    post = Post(
        feed_id=feed_id,
        guid=guid,
        download_url=f"https://example.com/{feed_id}/{guid}.mp3",
        title=guid,
        whitelisted=True,
        **fields,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_duplicate_guid_across_feeds_is_scoped_to_the_token_feed(
    app_with_post: Flask,
) -> None:
    with app_with_post.app_context():
        url_feed = app_with_post.config["URL_FEED_ID"]
        plain_feed = app_with_post.config["PLAIN_FEED_ID"]
        duplicate = _add_post(url_feed, "episode-1")
        path = "/post/episode-1.mp3"

        assert _resolve_feed_ids(path) == [plain_feed, url_feed]

        user = cast(Any, SimpleNamespace(id=1, role="admin"))
        token = cast(Any, SimpleNamespace(feed_id=url_feed))
        assert _validate_token_access(token, user, path) == (True, url_feed)

        with app_with_post.test_request_context(path):
            g.feed_token = SimpleNamespace(resource_feed_id=url_feed)
            found = find_post_for_request("episode-1")
            assert found is not None
            assert found.id == duplicate.id


def test_guid_ending_in_original_serves_its_processed_enclosure(
    app_with_post: Flask, tmp_path: Path
) -> None:
    from app.routes.post_routes import post_bp

    app_with_post.register_blueprint(post_bp)
    processed = tmp_path / "processed.mp3"
    processed.write_bytes(b"processed-audio")
    original = tmp_path / "original.mp3"
    original.write_bytes(b"original-audio")
    with app_with_post.app_context():
        feed_id = app_with_post.config["PLAIN_FEED_ID"]
        _add_post(feed_id, "show/ep", unprocessed_audio_path=str(original))
        _add_post(feed_id, "show/ep/original", processed_audio_path=str(processed))

        # The processed enclosure /post/<guid>.mp3 of "show/ep/original" is the
        # same URL as the original-audio link of "show/ep".
        assert _resolve_feed_ids("/post/show/ep/original.mp3") == [feed_id]

    client = app_with_post.test_client()
    response = client.get("/post/show/ep/original.mp3")
    assert response.status_code == 200
    assert response.data == b"processed-audio"

    original_response = client.get("/api/posts/show/ep/download/original")
    assert original_response.status_code == 200
    assert original_response.data == b"original-audio"
