import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.test_database import (
    APPLICATION_DATABASE_NAME,
    ORIGINAL_APP_DATABASE_ENV,
    DatabaseGuardError,
    assert_not_application_database,
    bind_tests_to_dedicated_database,
    database_identity,
    require_test_database_url,
)

API_ROOT = Path(__file__).resolve().parents[1]
APP_URL = "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea"
TEST_URL = "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea_test"
APPLICATION_DATABASE_URL = os.environ.get(ORIGINAL_APP_DATABASE_ENV, "").strip()


def test_missing_test_database_url_is_rejected() -> None:
    with pytest.raises(DatabaseGuardError, match="TEST_DATABASE_URL is required"):
        require_test_database_url(None, APP_URL)


def test_blank_test_database_url_is_rejected() -> None:
    with pytest.raises(DatabaseGuardError, match="TEST_DATABASE_URL is required"):
        require_test_database_url("   ", APP_URL)


def test_application_database_name_is_rejected() -> None:
    with pytest.raises(DatabaseGuardError, match="application database"):
        require_test_database_url(APP_URL, APP_URL)


def test_same_identity_as_database_url_is_rejected() -> None:
    with pytest.raises(DatabaseGuardError, match="same database"):
        require_test_database_url(
            "postgresql://sin_linea:sin_linea@localhost:5432/sin_linea_test",
            "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea_test",
        )


def test_name_without_test_suffix_is_rejected() -> None:
    with pytest.raises(DatabaseGuardError, match="must end with"):
        require_test_database_url(
            "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea_prod",
            APP_URL,
        )


def test_dedicated_test_url_is_accepted() -> None:
    assert require_test_database_url(TEST_URL, APP_URL) == TEST_URL


def test_bind_stays_valid_after_database_url_is_rewritten() -> None:
    environ = {
        "DATABASE_URL": APP_URL,
        "TEST_DATABASE_URL": TEST_URL,
    }
    first = bind_tests_to_dedicated_database(
        test_url=TEST_URL,
        app_url=APP_URL,
        environ=environ,
    )
    second = bind_tests_to_dedicated_database(
        test_url=TEST_URL,
        app_url=environ["DATABASE_URL"],
        environ=environ,
    )
    assert first == second == TEST_URL
    assert environ[ORIGINAL_APP_DATABASE_ENV] == APP_URL
    assert environ["DATABASE_URL"] == TEST_URL
    assert environ["TEST_DATABASE_URL"] == TEST_URL


def test_destructive_guard_rejects_application_connection() -> None:
    with pytest.raises(RuntimeError, match="connected database"):
        assert_not_application_database(
            configured_url=TEST_URL,
            connected_name=APPLICATION_DATABASE_NAME,
        )


def test_destructive_guard_rejects_misconfigured_url() -> None:
    with pytest.raises(RuntimeError, match="configured database"):
        assert_not_application_database(
            configured_url=APP_URL,
            connected_name="sin_linea_test",
        )


def test_suite_engine_is_not_the_application_database() -> None:
    assert database_identity(os.environ["DATABASE_URL"]).name.endswith("_test")
    assert database_identity(os.environ["DATABASE_URL"]).name != APPLICATION_DATABASE_NAME


def _application_fingerprint() -> dict[str, object]:
    engine = create_engine(APPLICATION_DATABASE_URL)
    try:
        with engine.connect() as connection:
            return {
                "database": connection.execute(text("SELECT current_database()")).scalar_one(),
                "events": connection.execute(text("SELECT count(*) FROM events")).scalar_one(),
                "articles": connection.execute(text("SELECT count(*) FROM articles")).scalar_one(),
                "claims": connection.execute(text("SELECT count(*) FROM claims")).scalar_one(),
                "app_settings": connection.execute(
                    text("SELECT count(*) FROM app_settings")
                ).scalar_one(),
            }
    finally:
        engine.dispose()


def _can_fingerprint_application() -> bool:
    if not APPLICATION_DATABASE_URL:
        return False
    try:
        return (
            database_identity(APPLICATION_DATABASE_URL).name == APPLICATION_DATABASE_NAME
        )
    except DatabaseGuardError:
        return False


def _run_isolated_pytest(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_health.py",
        ],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(
    not _can_fingerprint_application(),
    reason="application DATABASE_URL is not available to fingerprint",
)
def test_pytest_aborts_without_test_url_and_does_not_truncate_app_db() -> None:
    before = _application_fingerprint()
    assert before["database"] == APPLICATION_DATABASE_NAME
    env = os.environ.copy()
    env["DATABASE_URL"] = APPLICATION_DATABASE_URL
    env.pop("TEST_DATABASE_URL", None)
    result = _run_isolated_pytest(env)
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert "TEST_DATABASE_URL is required" in combined
    assert _application_fingerprint() == before


@pytest.mark.skipif(
    not _can_fingerprint_application(),
    reason="application DATABASE_URL is not available to fingerprint",
)
def test_pytest_aborts_when_test_url_is_the_app_db_and_does_not_truncate() -> None:
    before = _application_fingerprint()
    env = os.environ.copy()
    env["DATABASE_URL"] = APPLICATION_DATABASE_URL
    env["TEST_DATABASE_URL"] = APPLICATION_DATABASE_URL
    result = _run_isolated_pytest(env)
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert "application database" in combined or "same database" in combined
    assert _application_fingerprint() == before
