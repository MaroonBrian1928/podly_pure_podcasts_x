import os
from typing import Any

from flask_apscheduler import APScheduler
from flask_sqlalchemy import SQLAlchemy

# Unbound singletons; initialized in app factory
db = SQLAlchemy()
scheduler = APScheduler()

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
migrations_dir = os.path.join(base_dir, "migrations")


class LazyMigrate:
    def __init__(self, directory: str) -> None:
        self.directory = directory
        self._migrate: Any | None = None

    def _get_migrate(self) -> Any:
        if self._migrate is None:
            from flask_migrate import Migrate

            self._migrate = Migrate(directory=self.directory)
        return self._migrate

    def init_app(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_migrate().init_app(*args, **kwargs)


migrate = LazyMigrate(directory=migrations_dir)
