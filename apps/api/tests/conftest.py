from collections.abc import Generator
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.test_database import (
    DatabaseGuardError,
    assert_not_application_database,
    bind_tests_to_dedicated_database,
)

_BOOTSTRAP = Settings()
try:
    bind_tests_to_dedicated_database(
        test_url=_BOOTSTRAP.test_database_url,
        app_url=_BOOTSTRAP.database_url,
        environ=os.environ,
    )
except DatabaseGuardError as exc:
    pytest.exit(str(exc), returncode=4)

get_settings.cache_clear()

from app.core.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402


def _refuse_application_database(session: Session) -> None:
    connected = session.execute(text("SELECT current_database()")).scalar_one()
    assert_not_application_database(
        configured_url=get_settings().database_url,
        connected_name=str(connected),
    )


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    with engine.connect() as connection:
        connected = connection.execute(text("SELECT current_database()")).scalar_one()
        assert_not_application_database(
            configured_url=get_settings().database_url,
            connected_name=str(connected),
        )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def disable_article_images(monkeypatch: pytest.MonkeyPatch) -> None:
    """La suite no llama a DeepSeek ni a Replicate. Cada test que los cubre los reactiva con fakes."""
    monkeypatch.setattr(get_settings(), "article_image_enabled", False)


@pytest.fixture()
def db_session(apply_migrations: None) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        _refuse_application_database(session)
        yield session
        session.rollback()
        _refuse_application_database(session)
        skip = {"llm_price_books", "llm_price_rates"}
        table_names = ", ".join(
            table.name
            for table in reversed(Base.metadata.sorted_tables)
            if table.name not in skip
        )
        session.execute(text(f"TRUNCATE {table_names} CASCADE"))
        session.commit()
    finally:
        session.close()


@pytest.fixture(scope="session")
def db_engine():
    return engine
