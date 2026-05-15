from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

import app as _app_module  # noqa: F401  # registers the connect-time pragma hook


def test_sqlite_connect_applies_wal_and_size_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        synchronous = conn.execute(text("PRAGMA synchronous")).scalar()
        autocheckpoint = conn.execute(text("PRAGMA wal_autocheckpoint")).scalar()
        size_limit = conn.execute(text("PRAGMA journal_size_limit")).scalar()

    assert journal_mode == "wal"
    assert synchronous == 1  # NORMAL
    assert autocheckpoint == 1000
    assert size_limit == 67108864
