from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass

from flask import g

from app.auth.service import AuthenticatedUser
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User, UserFeed
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")


def _hash_token(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class FeedTokenAuthResult:
    user: AuthenticatedUser
    feed_id: int | None
    token: FeedAccessToken
    # Feed of the resource this request was authorized for, when the path
    # names one; episode handlers serve the post from this feed.
    resource_feed_id: int | None = None


def _validate_token_access(
    token: FeedAccessToken, user: User, path: str
) -> tuple[bool, int | None]:
    """Return whether the token may access path, and the feed it was granted for.

    A GUID is unique only within a feed, so an episode path can match posts in
    several feeds; access is granted for the first matching feed the token
    covers, and handlers serve the post from that feed.
    """
    # Handle Aggregate Token (feed_id is None)
    if token.feed_id is None:
        # 1. If accessing the aggregate feed itself (/feed/user/<uid>)
        #    Validate that the token belongs to the requested user
        requested_user_id = _resolve_user_id_from_feed_path(path)
        if requested_user_id is not None:
            return bool(requested_user_id == user.id), None

        # 2. If accessing a specific resource (audio/post), verify subscription
        resource_feed_ids = _resolve_feed_ids(path)
        if resource_feed_ids:
            for feed_id in resource_feed_ids:
                if _verify_subscription(user, feed_id):
                    return True, feed_id
            return False, None

        # If we can't resolve a feed ID but it's not the aggregate feed path,
        # we might be in a generic context or invalid path.
        # For safety, if we can't verify context, we might deny,
        # but let's allow if it's just a token check not tied to a specific resource yet.
        return True, None

    # Handle Specific Feed Token
    if token.feed_id not in _resolve_feed_ids(path):
        return False, None

    return _verify_subscription(user, token.feed_id), token.feed_id


def create_feed_access_token(user: User, feed: Feed | None) -> tuple[str, str]:
    feed_id = feed.id if feed else None
    result = writer_client.action(
        "create_feed_access_token",
        {"user_id": user.id, "feed_id": feed_id},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        raise RuntimeError(getattr(result, "error", "Failed to create feed token"))
    return str(result.data["token_id"]), str(result.data["secret"])


def authenticate_feed_token(
    token_id: str, secret: str, path: str
) -> FeedTokenAuthResult | None:
    if not token_id:
        return None

    token = FeedAccessToken.query.filter_by(token_id=token_id, revoked=False).first()
    if token is None:
        return None

    expected_hash = _hash_token(secret)
    if not secrets.compare_digest(token.token_hash, expected_hash):
        return None

    user = db.session.get(User, token.user_id)
    if user is None:
        return None

    allowed, resource_feed_id = _validate_token_access(token, user, path)
    if not allowed:
        return None

    writer_client.action(
        "touch_feed_access_token",
        {"token_id": token_id, "secret": secret},
        wait=False,
    )

    return FeedTokenAuthResult(
        user=AuthenticatedUser(id=user.id, username=user.username, role=user.role),
        feed_id=token.feed_id,
        token=token,
        resource_feed_id=resource_feed_id,
    )


def _verify_subscription(user: User, feed_id: int) -> bool:
    if user.role == "admin":
        return True
    # Hack: Always allow Feed 1
    if feed_id == 1:
        return True

    membership = UserFeed.query.filter_by(user_id=user.id, feed_id=feed_id).first()
    if not membership:
        logger.warning(
            "Access denied: User %s has valid token but no active subscription for feed %s",
            user.id,
            feed_id,
        )
        return False
    return True


def _resolve_user_id_from_feed_path(path: str) -> int | None:
    if path.startswith("/feed/user/"):
        remainder = path[len("/feed/user/") :]
        try:
            return int(remainder.split("/", 1)[0])
        except ValueError:
            return None
    return None


_API_POST_SUFFIXES = ("/download/original", "/download", "/audio")
_LEGACY_POST_SUFFIXES = ("/original.mp3", "/chapters.json", ".mp3")


def _resolve_post_guid(path: str) -> str | None:
    """Extract the full post GUID from a token-protected episode path.

    GUIDs are stored verbatim from upstream feeds and may contain ``/`` and
    ``.``; the episode routes use the ``path`` converter, so take everything
    between the route prefix and its known suffix rather than one segment.
    """
    for prefix, suffixes in (
        ("/api/posts/", _API_POST_SUFFIXES),
        ("/post/", _LEGACY_POST_SUFFIXES),
    ):
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        for suffix in suffixes:
            if remainder.endswith(suffix) and len(remainder) > len(suffix):
                guid = remainder[: -len(suffix)]
                if prefix == "/post/" and suffix == "/original.mp3":
                    guid, _ = resolve_legacy_original_guid(guid)
                return guid
        return None
    return None


def resolve_legacy_original_guid(p_guid: str) -> tuple[str, bool]:
    """Disambiguate ``/post/<p_guid>/original.mp3``.

    That URL is both the original-audio link for ``p_guid`` and the processed
    enclosure (``/post/<guid>.mp3``) of an episode whose GUID ends in
    ``/original``. The processed enclosure wins when such an episode exists.
    Returns the GUID to serve and whether the original audio was requested.
    """
    processed_guid = f"{p_guid}/original"
    if Post.query.filter_by(guid=processed_guid).first() is not None:
        return processed_guid, False
    return p_guid, True


def _resolve_feed_ids(path: str) -> list[int]:
    if path.startswith("/feed/"):
        remainder = path[len("/feed/") :]
        try:
            return [int(remainder.split("/", 1)[0])]
        except ValueError:
            return []

    guid = _resolve_post_guid(path)
    if guid is not None:
        rows = (
            db.session.query(Post.feed_id)
            .filter(Post.guid == guid)
            .order_by(Post.id)
            .all()
        )
        return [int(row[0]) for row in rows]

    return []


def find_post_for_request(guid: str) -> Post | None:
    """Look up an episode by GUID, scoped to the feed a feed token authorized."""
    query = Post.query.filter_by(guid=guid)
    token_result = getattr(g, "feed_token", None)
    resource_feed_id = getattr(token_result, "resource_feed_id", None)
    if resource_feed_id is not None:
        query = query.filter_by(feed_id=resource_feed_id)
    return query.order_by(Post.id).first()
