from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.auth.oidc_settings import OidcSettings
from app.extensions import db
from app.models import User
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")

# Keyed by issuer URL; cleared on process restart which is acceptable.
_discovery_cache: dict[str, dict[str, Any]] = {}


class OidcAuthError(Exception):
    """Base error for OIDC auth failures."""


class OidcRegistrationDisabledError(OidcAuthError):
    """Self-registration via OIDC is disabled."""


@dataclass
class OidcUserInfo:
    sub: str
    email: str | None
    preferred_username: str | None
    name: str | None


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _get_discovery(issuer: str) -> dict[str, Any]:
    """Fetch the OIDC discovery document, cached per issuer for process lifetime."""
    if issuer in _discovery_cache:
        return _discovery_cache[issuer]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=10) as client:
        response = client.get(url)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    _discovery_cache[issuer] = data
    return data


def build_authorization_url(
    settings: OidcSettings, state: str, code_challenge: str
) -> str:
    if not settings.issuer:
        raise OidcAuthError("OIDC issuer not configured")
    discovery = _get_discovery(settings.issuer)
    auth_endpoint = discovery["authorization_endpoint"]
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{auth_endpoint}?{urlencode(params)}"


def exchange_code_for_token(
    settings: OidcSettings, code: str, code_verifier: str
) -> dict[str, Any]:
    if not settings.issuer:
        raise OidcAuthError("OIDC issuer not configured")
    discovery = _get_discovery(settings.issuer)
    token_endpoint = discovery["token_endpoint"]
    with httpx.Client(timeout=10) as client:
        response = client.post(
            token_endpoint,
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def get_userinfo(settings: OidcSettings, access_token: str) -> OidcUserInfo:
    if not settings.issuer:
        raise OidcAuthError("OIDC issuer not configured")
    discovery = _get_discovery(settings.issuer)
    userinfo_endpoint = discovery["userinfo_endpoint"]
    with httpx.Client(timeout=10) as client:
        response = client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    return OidcUserInfo(
        sub=str(data["sub"]),
        email=data.get("email"),
        preferred_username=data.get("preferred_username"),
        name=data.get("name"),
    )


def find_or_create_user_from_oidc(
    userinfo: OidcUserInfo,
    settings: OidcSettings,
) -> User:
    result = writer_client.action(
        "upsert_oidc_user",
        {
            "oidc_sub": userinfo.sub,
            "oidc_email": userinfo.email,
            "preferred_username": userinfo.preferred_username,
            "name": userinfo.name,
            "allow_registration": settings.allow_registration,
        },
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        err = getattr(result, "error", "Failed to upsert OIDC user")
        if "disabled" in str(err).lower():
            raise OidcRegistrationDisabledError(str(err))
        raise OidcAuthError(str(err))

    user_id = int(result.data["user_id"])
    user = db.session.get(User, user_id)
    if user is None:
        raise OidcAuthError("OIDC user upserted but not found in database")
    return user
