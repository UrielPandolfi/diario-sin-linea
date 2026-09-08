from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import Base


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")


@pytest.fixture()
def db_session(apply_migrations: None) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
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
