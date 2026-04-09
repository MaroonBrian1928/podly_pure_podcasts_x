from __future__ import annotations

import os


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def show_discord_integration() -> bool:
    return not _env_bool("PODLY_HIDE_DISCORD_INTEGRATION", default=False)


def show_report_issue_button() -> bool:
    return not _env_bool("PODLY_HIDE_REPORT_ISSUE_BUTTON", default=False)
