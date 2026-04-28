from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from urllib.parse import quote_plus

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    request,
    session,
)

from app.auth.guards import require_admin
from app.auth.service import update_user_last_active
from app.auth.oidc_service import (
    OidcAuthError,
    OidcRegistrationDisabledError,
    build_authorization_url,
    exchange_code_for_token,
    find_or_create_user_from_oidc,
    generate_oauth_state,
    generate_pkce_pair,
    get_userinfo,
)
from app.auth.oidc_settings import reload_oidc_settings
from app.writer.client import writer_client

if TYPE_CHECKING:
    from app.auth.oidc_settings import OidcSettings

logger = logging.getLogger("global_logger")

oidc_bp = Blueprint("oidc", __name__)

SESSION_OAUTH_STATE_KEY = "oidc_oauth_state"
SESSION_PKCE_VERIFIER_KEY = "oidc_pkce_verifier"
SESSION_USER_KEY = "user_id"


def _get_oidc_settings() -> OidcSettings | None:
    return current_app.config.get("OIDC_SETTINGS")


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _has_env_override(env_var: str) -> bool:
    return bool(os.environ.get(env_var))


@oidc_bp.route("/api/auth/oidc/status", methods=["GET"])
def oidc_status() -> Response:
    settings = _get_oidc_settings()
    return jsonify({"enabled": settings.enabled if settings else False})


@oidc_bp.route("/api/auth/oidc/config", methods=["GET"])
def oidc_config_get() -> Response | tuple[Response, int]:
    _, error_response = require_admin()
    if error_response:
        return error_response, error_response.status_code

    settings = _get_oidc_settings()

    env_overrides: dict[str, dict[str, str | bool]] = {}
    for env_var, key in [
        ("OIDC_ISSUER", "issuer"),
        ("OIDC_CLIENT_ID", "client_id"),
        ("OIDC_REDIRECT_URI", "redirect_uri"),
        ("OIDC_ALLOW_REGISTRATION", "allow_registration"),
    ]:
        if _has_env_override(env_var):
            env_overrides[key] = {
                "env_var": env_var,
                "value": os.environ.get(env_var, ""),
            }
    if _has_env_override("OIDC_CLIENT_SECRET"):
        env_overrides["client_secret"] = {
            "env_var": "OIDC_CLIENT_SECRET",
            "is_secret": True,
        }

    return jsonify(
        {
            "config": {
                "enabled": settings.enabled if settings else False,
                "issuer": settings.issuer if settings else None,
                "client_id": settings.client_id if settings else None,
                "client_secret_preview": (
                    _mask_secret(settings.client_secret) if settings else None
                ),
                "redirect_uri": settings.redirect_uri if settings else None,
                "allow_registration": (
                    settings.allow_registration if settings else True
                ),
            },
            "env_overrides": env_overrides,
        }
    )


@oidc_bp.route("/api/auth/oidc/config", methods=["PUT"])
def oidc_config_put() -> Response | tuple[Response, int]:
    _, error_response = require_admin()
    if error_response:
        return error_response, error_response.status_code

    payload = request.get_json(silent=True) or {}

    try:
        update_params: dict[str, object] = {}

        if "issuer" in payload and not _has_env_override("OIDC_ISSUER"):
            update_params["issuer"] = payload["issuer"] or None
        if "client_id" in payload and not _has_env_override("OIDC_CLIENT_ID"):
            update_params["client_id"] = payload["client_id"] or None
        if "client_secret" in payload and not _has_env_override("OIDC_CLIENT_SECRET"):
            secret = payload["client_secret"]
            if secret and not str(secret).endswith("..."):
                update_params["client_secret"] = secret
        if "redirect_uri" in payload and not _has_env_override("OIDC_REDIRECT_URI"):
            update_params["redirect_uri"] = payload["redirect_uri"] or None
        if "allow_registration" in payload and not _has_env_override(
            "OIDC_ALLOW_REGISTRATION"
        ):
            val = payload["allow_registration"]
            if isinstance(val, str):
                update_params["allow_registration"] = val.strip().lower() in (
                    "true", "1", "yes"
                )
            else:
                update_params["allow_registration"] = bool(val)

        if update_params:
            result = writer_client.action(
                "update_oidc_settings", update_params, wait=True
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Writer update failed"))

        new_settings = reload_oidc_settings(current_app)
        logger.info("OIDC settings updated (enabled=%s)", new_settings.enabled)

        return jsonify(
            {
                "status": "ok",
                "config": {
                    "enabled": new_settings.enabled,
                    "issuer": new_settings.issuer,
                    "client_id": new_settings.client_id,
                    "client_secret_preview": _mask_secret(new_settings.client_secret),
                    "redirect_uri": new_settings.redirect_uri,
                    "allow_registration": new_settings.allow_registration,
                },
            }
        )
    except Exception as e:
        logger.exception("Failed to update OIDC settings: %s", e)
        return jsonify({"error": "Failed to update OIDC settings"}), 500


@oidc_bp.route("/api/auth/oidc/login", methods=["GET"])
def oidc_login() -> Response | tuple[Response, int]:
    settings = _get_oidc_settings()
    if not settings or not settings.enabled:
        return jsonify({"error": "OIDC SSO is not configured."}), 404

    state = generate_oauth_state()
    code_verifier, code_challenge = generate_pkce_pair()
    session[SESSION_OAUTH_STATE_KEY] = state
    session[SESSION_PKCE_VERIFIER_KEY] = code_verifier

    try:
        auth_url = build_authorization_url(settings, state, code_challenge)
    except Exception as e:
        logger.exception("Failed to build OIDC authorization URL: %s", e)
        return jsonify({"error": "Failed to start OIDC login."}), 500

    return jsonify({"authorization_url": auth_url})


@oidc_bp.route("/api/auth/oidc/callback", methods=["GET"])
def oidc_callback() -> Response:
    settings = _get_oidc_settings()
    if not settings or not settings.enabled:
        return redirect("/?error=oidc_not_configured")

    state = request.args.get("state")
    expected_state = session.pop(SESSION_OAUTH_STATE_KEY, None)
    if not state or state != expected_state:
        return redirect("/?error=invalid_state")

    code_verifier = session.pop(SESSION_PKCE_VERIFIER_KEY, None)
    if not code_verifier:
        return redirect("/?error=invalid_state")

    error = request.args.get("error")
    if error:
        # URL-encode the provider error value before embedding in redirect
        return redirect(f"/?error={quote_plus(error)}")

    code = request.args.get("code")
    if not code:
        return redirect("/?error=missing_code")

    try:
        token_data = exchange_code_for_token(settings, code, code_verifier)
        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning("OIDC token response missing access_token")
            return redirect("/?error=auth_failed")

        userinfo = get_userinfo(settings, access_token)

        user = find_or_create_user_from_oidc(userinfo, settings)

        session.clear()
        session[SESSION_USER_KEY] = user.id
        session.permanent = True
        update_user_last_active(user.id)

        logger.info(
            "OIDC login successful for user %s (sub=%s)",
            user.username,
            userinfo.sub,
        )
        return redirect("/")

    except OidcRegistrationDisabledError:
        return redirect("/?error=registration_disabled")
    except OidcAuthError as e:
        logger.warning("OIDC auth error: %s", e)
        return redirect("/?error=auth_failed")
    except Exception as e:
        logger.exception("OIDC auth failed unexpectedly: %s", e)
        return redirect("/?error=auth_failed")
