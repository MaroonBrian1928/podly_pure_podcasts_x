from contextlib import ExitStack
from pathlib import Path

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from app import _configure_database


def test_database_pool_releases_overflow_without_reducing_concurrency(
    tmp_path: Path,
) -> None:
    app = Flask("database-pool-bounds", instance_path=str(tmp_path))
    _configure_database(app)
    options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    assert options["pool_size"] + options["max_overflow"] == 10
    assert options["connect_args"]["timeout"] == 60

    engine = create_engine(f"sqlite:///{tmp_path / 'isolated-pool.db'}", **options)
    try:
        assert isinstance(engine.pool, QueuePool)
        with ExitStack() as connections:
            for _ in range(10):
                connections.enter_context(engine.connect())
            assert engine.pool.checkedout() == 10
        assert engine.pool.checkedout() == 0
        assert engine.pool.checkedin() == 3
        assert engine.pool.size() == 3
    finally:
        engine.dispose()
