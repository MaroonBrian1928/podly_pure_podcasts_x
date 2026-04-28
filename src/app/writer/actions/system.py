import logging
import os
from datetime import UTC, datetime
from typing import Any

from app.extensions import db
from app.jobs_manager_run_service import get_or_create_singleton_run
from app.models import DiscordSettings, OidcSettings

logger = logging.getLogger("writer")


def ensure_active_run_action(params: dict[str, Any]) -> dict[str, Any]:
    trigger = params.get("trigger", "system")
    context = params.get("context")

    logger.info(
        "[WRITER] ensure_active_run_action: trigger=%s context_keys=%s",
        trigger,
        list(context.keys()) if isinstance(context, dict) else None,
    )

    run = get_or_create_singleton_run(db.session, trigger, context)
    db.session.flush()  # Ensure ID is available

    logger.info(
        "[WRITER] ensure_active_run_action: obtained run_id=%s status=%s",
        getattr(run, "id", None),
        getattr(run, "status", None),
    )

    return {"run_id": run.id}


def update_discord_settings_action(params: dict[str, Any]) -> dict[str, Any]:
    settings = db.session.get(DiscordSettings, 1)
    if settings is None:
        settings = DiscordSettings(id=1)
        db.session.add(settings)

    for field in (
        "client_id",
        "client_secret",
        "redirect_uri",
        "guild_ids",
        "allow_registration",
    ):
        if field in params:
            setattr(settings, field, params.get(field))

    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush()
    return {"updated": True}


_OIDC_ENV_LOCKS: dict[str, str] = {
    "issuer": "OIDC_ISSUER",
    "client_id": "OIDC_CLIENT_ID",
    "client_secret": "OIDC_CLIENT_SECRET",
    "redirect_uri": "OIDC_REDIRECT_URI",
    "allow_registration": "OIDC_ALLOW_REGISTRATION",
}


def update_oidc_settings_action(params: dict[str, Any]) -> dict[str, Any]:
    settings = db.session.get(OidcSettings, 1)
    if settings is None:
        settings = OidcSettings(id=1)
        db.session.add(settings)

    for field, env_var in _OIDC_ENV_LOCKS.items():
        if field in params and not os.environ.get(env_var):
            setattr(settings, field, params.get(field))

    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush()
    return {"updated": True}


def update_combined_config_action(params: dict[str, Any]) -> dict[str, Any]:
    payload = params.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    # Import locally to avoid cyclic dependencies
    from app.config_store import (
        hydrate_runtime_config_inplace,
        update_combined,
    )

    updated = update_combined(payload)

    # Ensure the running process sees the new config immediately
    hydrate_runtime_config_inplace()

    # Reset processor instance to pick up new config (e.g. litellm globals)
    # Import locally to avoid cyclic dependencies
    import importlib

    processor = importlib.import_module("app.processor")
    processor.ProcessorSingleton.reset_instance()

    if not isinstance(updated, dict):
        return {"updated": True}
    return updated
