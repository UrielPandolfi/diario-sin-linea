"""Medición de intentos, caché de proveedores y tarifas DeepSeek 2026-10-03.

Revision ID: 0022_cost_measurement
Revises: 0021_account_security
Create Date: 2026-10-03

No reescribe llm_usages históricos.
"""

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

revision: str = "0022_cost_measurement"
down_revision: str | None = "0021_account_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_RATES = [
    ("deepseek", "deepseek-flash", "input", "0.15", {"window": "off_peak", "peak_multiplier": 2}),
    ("deepseek", "deepseek-flash", "cached_read", "0.003", {"window": "off_peak", "peak_multiplier": 2}),
    ("deepseek", "deepseek-flash", "output", "0.60", {"window": "off_peak", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-flash", "input", "0.15", {"alias_of": "deepseek-flash", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-flash", "cached_read", "0.003", {"alias_of": "deepseek-flash", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-flash", "output", "0.60", {"alias_of": "deepseek-flash", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-pro", "input", "0.66", {"window": "off_peak", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-pro", "cached_read", "0.022", {"window": "off_peak", "peak_multiplier": 2}),
    ("deepseek", "deepseek-v4-pro", "output", "1.98", {"window": "off_peak", "peak_multiplier": 2}),
    ("exa", "search", "request", "0.007", {"unit": "request", "source": "exa changelog per 1k requests"}),
    (
        "replicate",
        "black-forest-labs/flux-schnell",
        "request",
        "0.003",
        {"unit": "request", "source": "public listing"},
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "llm_usages" in tables:
        columns = {column["name"] for column in inspector.get_columns("llm_usages")}
        additions = [
            ("reasoning_tokens", sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0")),
            ("call_kind", sa.Column("call_kind", sa.String(length=32), nullable=False, server_default="llm")),
            (
                "environment",
                sa.Column("environment", sa.String(length=32), nullable=False, server_default="production"),
            ),
            ("attempt_index", sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="1")),
            ("request_options", sa.Column("request_options", JSONB(), nullable=True)),
            ("confirmed_cost_usd", sa.Column("confirmed_cost_usd", sa.Numeric(18, 10), nullable=True)),
        ]
        for name, column in additions:
            if name not in columns:
                op.add_column("llm_usages", column)
        indexes = {index["name"] for index in inspector.get_indexes("llm_usages")}
        if "ix_llm_usages_environment" not in indexes:
            op.create_index("ix_llm_usages_environment", "llm_usages", ["environment"])

    if "provider_result_cache" not in tables:
        op.create_table(
            "provider_result_cache",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("request_json", JSONB(), nullable=False),
            sa.Column("response_json", JSONB(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("event_id", PGUUID(), nullable=True),
            sa.Column("pipeline_run_id", PGUUID(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_provider_result_cache"),
        )
        op.create_index("ix_provider_result_cache_kind", "provider_result_cache", ["kind"])
        op.create_index("ix_provider_result_cache_request_hash", "provider_result_cache", ["request_hash"])
        op.create_index("ix_provider_result_cache_status", "provider_result_cache", ["status"])
        op.create_index(
            "uq_provider_cache_pending",
            "provider_result_cache",
            ["kind", "provider", "request_hash"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )
    if "provider_result_cache" in set(inspect(bind).get_table_names()):
        names = {index["name"] for index in inspect(bind).get_indexes("provider_result_cache")}
        if "uq_provider_cache_pending" not in names:
            op.create_index(
                "uq_provider_cache_pending",
                "provider_result_cache",
                ["kind", "provider", "request_hash"],
                unique=True,
                postgresql_where=sa.text("status = 'pending'"),
            )

    existing = bind.execute(
        sa.text("SELECT id FROM llm_price_books WHERE version = :version"),
        {"version": "2026-10-03"},
    ).first()
    if existing is not None:
        return
    book_id = uuid4()
    bind.execute(
        sa.text(
            """
            INSERT INTO llm_price_books (id, version, effective_from, source_url, notes)
            VALUES (:id, :version, :effective_from, :source_url, :notes)
            """
        ),
        {
            "id": book_id,
            "version": "2026-10-03",
            "effective_from": datetime(2026, 10, 3, tzinfo=timezone.utc),
            "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
            "notes": (
                "Copia 2026-09-08 más DeepSeek valle 2026-10-03 (pico lun-vie UTC "
                "01:00-04:00 y 06:00-10:00, x2; feriados de China no excluidos). "
                "deepseek-chat no tiene tarifa oficial. Exa 0.007 por request. "
                "flux-schnell 0.003 por imagen, listado público."
            ),
        },
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO llm_price_rates (id, book_id, provider, model, kind, usd_per_million, extra_json)
            SELECT gen_random_uuid(), :book_id, provider, model, kind, usd_per_million, extra_json
            FROM llm_price_rates
            WHERE book_id = (SELECT id FROM llm_price_books WHERE version = '2026-09-08')
            """
        ),
        {"book_id": book_id},
    )
    for provider, model, kind, amount, extra in _NEW_RATES:
        bind.execute(
            sa.text(
                """
                INSERT INTO llm_price_rates (id, book_id, provider, model, kind, usd_per_million, extra_json)
                VALUES (:id, :book_id, :provider, :model, :kind, :amount, CAST(:extra AS jsonb))
                """
            ),
            {
                "id": uuid4(),
                "book_id": book_id,
                "provider": provider,
                "model": model,
                "kind": kind,
                "amount": amount,
                "extra": json.dumps(extra),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    bind.execute(sa.text("DELETE FROM llm_price_books WHERE version = '2026-10-03'"))
    if "provider_result_cache" in tables:
        op.drop_table("provider_result_cache")
    if "llm_usages" in tables:
        columns = {column["name"] for column in inspector.get_columns("llm_usages")}
        for name in (
            "confirmed_cost_usd",
            "request_options",
            "attempt_index",
            "environment",
            "call_kind",
            "reasoning_tokens",
        ):
            if name in columns:
                op.drop_column("llm_usages", name)
