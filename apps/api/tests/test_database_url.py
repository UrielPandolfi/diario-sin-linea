from app.core.config import Settings, get_settings, normalize_database_url


def test_plain_postgresql_url_uses_psycopg3_dialect() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_postgres_scheme_and_query_are_preserved() -> None:
    assert (
        normalize_database_url("postgres://user:pass@host:5432/db?sslmode=require")
        == "postgresql+psycopg://user:pass@host:5432/db?sslmode=require"
    )


def test_existing_psycopg3_url_is_unchanged() -> None:
    url = "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea"
    assert normalize_database_url(url) == url


def test_settings_rewrites_railway_style_database_url(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:secret@postgres.railway.internal:5432/railway",
    )
    try:
        assert (
            Settings().database_url
            == "postgresql+psycopg://user:secret@postgres.railway.internal:5432/railway"
        )
    finally:
        get_settings.cache_clear()
