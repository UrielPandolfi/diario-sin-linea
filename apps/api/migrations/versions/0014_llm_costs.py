"""LLM cost book, cache tokens, attribution, model requested vs reported.

Revision ID: 0014_llm_costs
Revises: 0013_reader_cases
Create Date: 2026-09-08
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

revision: str = "0014_llm_costs"
down_revision: str | None = "0013_reader_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tarifas verificadas 2026-09-08 (docs oficiales OpenAI y Voyage).
_RATES = [
    ("openai", "gpt-4o", "input", "2.50"),
    ("openai", "gpt-4o", "cached_read", "1.25"),
    ("openai", "gpt-4o", "output", "10.00"),
    ("openai", "gpt-4o-mini", "input", "0.15"),
    ("openai", "gpt-4o-mini", "cached_read", "0.075"),
    ("openai", "gpt-4o-mini", "output", "0.60"),
    ("openai", "gpt-5-nano", "input", "0.05"),
    ("openai", "gpt-5-nano", "cached_read", "0.005"),
    ("openai", "gpt-5-nano", "output", "0.40"),
    ("openai", "gpt-5.6-luna", "input", "0.20"),
    ("openai", "gpt-5.6-luna", "cached_read", "0.02"),
    ("openai", "gpt-5.6-luna", "cached_write", "0.25"),
    ("openai", "gpt-5.6-luna", "output", "1.20"),
    ("voyage", "voyage-3", "embedding", "0.06"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "llm_price_books" not in tables:
        op.create_table(
            "llm_price_books",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name="pk_llm_price_books"),
        )
        op.create_index("ix_llm_price_books_effective_from", "llm_price_books", ["effective_from"])

    if "llm_price_rates" not in tables:
        op.create_table(
            "llm_price_rates",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("book_id", PGUUID(), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("usd_per_million", sa.Numeric(18, 10), nullable=False),
            sa.Column("extra_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.ForeignKeyConstraint(
                ["book_id"], ["llm_price_books.id"], ondelete="CASCADE", name="fk_llm_price_rates_book_id_llm_price_books"
            ),
            sa.PrimaryKeyConstraint("id", name="pk_llm_price_rates"),
            sa.UniqueConstraint(
                "book_id",
                "provider",
                "model",
                "kind",
                name="uq_llm_price_rates_book_provider_model_kind",
            ),
        )
        op.create_index("ix_llm_price_rates_book_id", "llm_price_rates", ["book_id"])

    if "llm_usages" in tables:
        columns = {col["name"] for col in inspector.get_columns("llm_usages")}
        to_add = [
            ("model_requested", sa.Column("model_requested", sa.String(length=128), nullable=True)),
            ("model_reported", sa.Column("model_reported", sa.String(length=128), nullable=True)),
            (
                "cache_read_tokens",
                sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
            ),
            (
                "cache_write_tokens",
                sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
            ),
            (
                "usage_reported",
                sa.Column("usage_reported", sa.Boolean(), nullable=False, server_default=sa.true()),
            ),
            (
                "attribution_kind",
                sa.Column(
                    "attribution_kind",
                    sa.String(length=32),
                    nullable=False,
                    server_default="unattributed",
                ),
            ),
            (
                "cost_status",
                sa.Column("cost_status", sa.String(length=16), nullable=False, server_default="unknown"),
            ),
            ("estimated_cost_usd", sa.Column("estimated_cost_usd", sa.Numeric(18, 10), nullable=True)),
            ("price_book_id", sa.Column("price_book_id", PGUUID(), nullable=True)),
            ("rate_snapshot", sa.Column("rate_snapshot", JSONB(), nullable=True)),
        ]
        for name, column in to_add:
            if name not in columns:
                op.add_column("llm_usages", column)
        existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("llm_usages")}
        if "fk_llm_usages_price_book_id_llm_price_books" not in existing_fks:
            op.create_foreign_key(
                "fk_llm_usages_price_book_id_llm_price_books",
                "llm_usages",
                "llm_price_books",
                ["price_book_id"],
                ["id"],
                ondelete="SET NULL",
            )
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("llm_usages")}
        for name, cols in (
            ("ix_llm_usages_attribution_kind", ["attribution_kind"]),
            ("ix_llm_usages_cost_status", ["cost_status"]),
            ("ix_llm_usages_price_book_id", ["price_book_id"]),
        ):
            if name not in existing_indexes:
                op.create_index(name, "llm_usages", cols)
        op.execute(
            """
            UPDATE llm_usages
            SET model_requested = model
            WHERE model_requested IS NULL AND model IS NOT NULL
            """
        )
        op.execute(
            """
            UPDATE llm_usages
            SET attribution_kind = CASE
                WHEN event_id IS NOT NULL THEN 'direct'
                WHEN source_item_id IS NOT NULL THEN 'item'
                ELSE 'unattributed'
            END
            WHERE attribution_kind = 'unattributed'
            """
        )

    book_id = uuid4()
    existing = bind.execute(sa.text("SELECT id FROM llm_price_books WHERE version = :v"), {"v": "2026-09-08"}).first()
    if existing is None:
        bind.execute(
            sa.text(
                """
                INSERT INTO llm_price_books (id, version, effective_from, source_url, notes)
                VALUES (:id, :version, :effective_from, :source_url, :notes)
                """
            ),
            {
                "id": book_id,
                "version": "2026-09-08",
                "effective_from": datetime(2026, 9, 8, tzinfo=timezone.utc),
                "source_url": "https://developers.openai.com/api/docs/pricing",
                "notes": (
                    "Semilla verificada 2026-09-08. OpenAI: gpt-4o, gpt-4o-mini, gpt-5-nano, "
                    "gpt-5.6-luna (corto). Voyage: voyage-3. Sin DeepSeek."
                ),
            },
        )
        for provider, model, kind, amount in _RATES:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO llm_price_rates (id, book_id, provider, model, kind, usd_per_million, extra_json)
                    VALUES (:id, :book_id, :provider, :model, :kind, :usd, '{}'::jsonb)
                    """
                ),
                {
                    "id": uuid4(),
                    "book_id": book_id,
                    "provider": provider,
                    "model": model,
                    "kind": kind,
                    "usd": Decimal(amount),
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "llm_usages" in tables:
        columns = {col["name"] for col in inspector.get_columns("llm_usages")}
        fks = {fk["name"] for fk in inspector.get_foreign_keys("llm_usages")}
        indexes = {idx["name"] for idx in inspector.get_indexes("llm_usages")}
        if "fk_llm_usages_price_book_id_llm_price_books" in fks:
            op.drop_constraint(
                "fk_llm_usages_price_book_id_llm_price_books", "llm_usages", type_="foreignkey"
            )
        for name in (
            "ix_llm_usages_price_book_id",
            "ix_llm_usages_cost_status",
            "ix_llm_usages_attribution_kind",
        ):
            if name in indexes:
                op.drop_index(name, table_name="llm_usages")
        for name in (
            "rate_snapshot",
            "price_book_id",
            "estimated_cost_usd",
            "cost_status",
            "attribution_kind",
            "usage_reported",
            "cache_write_tokens",
            "cache_read_tokens",
            "model_reported",
            "model_requested",
        ):
            if name in columns:
                op.drop_column("llm_usages", name)
    if "llm_price_rates" in tables:
        op.drop_table("llm_price_rates")
    if "llm_price_books" in tables:
        op.drop_table("llm_price_books")
