from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

    from app.models import OidcSettings as OidcSettingsModel

logger = logging.getLogger("global_logger")


@dataclass(slots=True, frozen=True)
class OidcSettings:
    enabled: bool
    issuer: str | None
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    allow_registration: bool


def load_oidc_settings() -> OidcSettings:
    """Load OIDC settings from environment variables and database.

    Environment variables take precedence over database values.
    """
    db_settings = _load_from_database()

    issuer = os.environ.get("OIDC_ISSUER") or (
        db_settings.issuer if db_settings else None
    )
    client_id = os.environ.get("OIDC_CLIENT_ID") or (
        db_settings.client_id if db_settings else None
    )
    client_secret = os.environ.get("OIDC_CLIENT_SECRET") or (
        db_settings.client_secret if db_settings else None
    )
    redirect_uri = os.environ.get("OIDC_REDIRECT_URI") or (
        db_settings.redirect_uri if db_settings else None
    )

    enabled = bool(issuer and client_id and client_secret and redirect_uri)

    allow_reg_env = os.environ.get("OIDC_ALLOW_REGISTRATION")
    if allow_reg_env is not None:
        allow_registration = allow_reg_env.lower() in ("true", "1", "yes")
    elif db_settings is not None:
        allow_registration = db_settings.allow_registration
    else:
        allow_registration = True

    return OidcSettings(
        enabled=enabled,
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        allow_registration=allow_registration,
    )


def _load_from_database() -> OidcSettingsModel | None:
    try:
        from app.extensions import db
        from app.models import OidcSettings as OidcSettingsModel

        return db.session.get(OidcSettingsModel, 1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to load OIDC settings from database: %s", exc)
        return None


def reload_oidc_settings(app: Flask) -> OidcSettings:
    """Reload OIDC settings and update app config."""
    old_settings: OidcSettings | None = app.config.get("OIDC_SETTINGS")
    settings = load_oidc_settings()
    app.config["OIDC_SETTINGS"] = settings

    if old_settings is None or old_settings.issuer != settings.issuer:
        from app.auth.oidc_service import _discovery_cache
        _discovery_cache.clear()

    return settings
