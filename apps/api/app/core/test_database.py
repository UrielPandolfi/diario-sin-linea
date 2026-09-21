"""Guards that keep pytest off the application database."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import normalize_database_url

APPLICATION_DATABASE_NAME = "sin_linea"
TEST_DATABASE_SUFFIX = "_test"
ORIGINAL_APP_DATABASE_ENV = "PYTEST_APPLICATION_DATABASE_URL"


class DatabaseGuardError(Exception):
    """pytest must stop; the dedicated test database is missing or unsafe."""


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: int
    name: str


def database_identity(url: str) -> DatabaseIdentity:
    parsed = urlparse(normalize_database_url(url.strip()))
    name = unquote_name(parsed.path)
    host = (parsed.hostname or "").lower()
    port = parsed.port or 5432
    if not name:
        raise DatabaseGuardError("Database URL is missing a database name.")
    return DatabaseIdentity(host=host, port=port, name=name)


def unquote_name(path: str) -> str:
    return (path or "").lstrip("/").split("/", 1)[0].split("?", 1)[0]


def require_test_database_url(
    test_url: str | None,
    app_url: str | None = None,
) -> str:
    candidate = (test_url or "").strip()
    if not candidate:
        raise DatabaseGuardError(
            "TEST_DATABASE_URL is required. Pytest refuses to use DATABASE_URL "
            "or the application database as a fallback."
        )
    identity = database_identity(candidate)
    if identity.name == APPLICATION_DATABASE_NAME:
        raise DatabaseGuardError(
            "TEST_DATABASE_URL points at the application database "
            f"{APPLICATION_DATABASE_NAME!r}."
        )
    if not identity.name.endswith(TEST_DATABASE_SUFFIX):
        raise DatabaseGuardError(
            f"TEST_DATABASE_URL database {identity.name!r} must end with "
            f"{TEST_DATABASE_SUFFIX!r}."
        )
    app_candidate = (app_url or "").strip()
    if app_candidate and identity == database_identity(app_candidate):
        raise DatabaseGuardError(
            "TEST_DATABASE_URL must not be the same database as DATABASE_URL."
        )
    return candidate


def bind_tests_to_dedicated_database(
    *,
    test_url: str | None,
    app_url: str | None,
    environ: MutableMapping[str, str],
) -> str:
    preserved = (environ.get(ORIGINAL_APP_DATABASE_ENV) or "").strip()
    original_app = preserved or (app_url or "").strip()
    url = require_test_database_url(test_url, original_app)
    if original_app and not preserved:
        environ[ORIGINAL_APP_DATABASE_ENV] = original_app
    environ["DATABASE_URL"] = url
    return url


def assert_not_application_database(
    *,
    configured_url: str,
    connected_name: str,
) -> None:
    identity = database_identity(configured_url)
    connected = (connected_name or "").strip()
    if identity.name == APPLICATION_DATABASE_NAME or not identity.name.endswith(
        TEST_DATABASE_SUFFIX
    ):
        raise RuntimeError(
            "Refusing a destructive test operation on configured database "
            f"{identity.name!r}."
        )
    if connected == APPLICATION_DATABASE_NAME or not connected.endswith(
        TEST_DATABASE_SUFFIX
    ):
        raise RuntimeError(
            "Refusing a destructive test operation on connected database "
            f"{connected!r}."
        )
