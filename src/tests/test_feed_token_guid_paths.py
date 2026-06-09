from __future__ import annotations

from collections.abc import Generator

import pytest
from flask import Flask

from app.auth.feed_tokens import _resolve_feed_id
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
        assert _resolve_feed_id(f"/post/{URL_GUID}.mp3") == expected


def test_resolve_feed_id_for_url_shaped_guid_original_mp3(
    app_with_post: Flask,
) -> None:
    with app_with_post.app_context():
        expected = app_with_post.config["URL_FEED_ID"]
        assert _resolve_feed_id(f"/post/{URL_GUID}/original.mp3") == expected


def test_resolve_feed_id_for_plain_guid_unchanged(app_with_post: Flask) -> None:
    with app_with_post.app_context():
        expected = app_with_post.config["PLAIN_FEED_ID"]
        assert _resolve_feed_id("/post/episode-1.mp3") == expected
        assert _resolve_feed_id("/post/episode-1/original.mp3") == expected
