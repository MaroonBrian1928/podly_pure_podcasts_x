"""HMAC token utilities for the episode process-request link.

The token is a stable, per-episode signature derived from the server
SECRET_KEY and the episode GUID.  It is embedded in the RSS description
so that a podcast app user can tap the link to trigger processing without
needing to log in.

Security properties:
- Unforgeable without the server secret.
- Stable (no expiry) — valid as long as the server secret doesn't change.
- The RSS feed itself is already protected by the feed_token auth layer,
  so these tokens are only visible to authorised subscribers.
"""

import hashlib
import hmac

from flask import current_app


def make_process_token(post_guid: str) -> str:
    """Return a 32-hex-char HMAC-SHA256 token for *post_guid*.

    Raises RuntimeError if SECRET_KEY is not configured — an empty key
    would make all tokens predictable and is therefore rejected.
    """
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not configured; cannot generate a secure process token"
        )
    key = secret.encode() if isinstance(secret, str) else bytes(secret)
    return hmac.new(key, post_guid.encode(), hashlib.sha256).hexdigest()[:32]


def verify_process_token(post_guid: str, token: str) -> bool:
    """Return True iff *token* is the valid process token for *post_guid*."""
    try:
        expected = make_process_token(post_guid)
        return hmac.compare_digest(expected, token)
    except Exception:  # noqa: BLE001
        return False
