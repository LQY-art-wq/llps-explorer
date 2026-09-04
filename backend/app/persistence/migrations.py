"""Programmatic Alembic upgrade using the already configured SQLAlchemy engine."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine


def upgrade_database(engine: Engine) -> None:
    script_location = Path(__file__).resolve().parent / "alembic"
    config = Config()
    config.set_main_option("script_location", str(script_location))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
