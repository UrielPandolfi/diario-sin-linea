"""Reader interest locality and the GeoRef catalog.

Revision ID: 0020_reader_locality
Revises: 0019_reader_saves
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0020_reader_locality"
down_revision: str | None = "0019_reader_saves"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "geo_localities" not in inspector.get_table_names():
        op.create_table(
            "geo_localities",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("name_folded", sa.String(length=160), nullable=False),
            sa.Column("province_id", sa.String(length=16), nullable=False),
            sa.Column("province_name", sa.String(length=80), nullable=False),
            sa.Column("department_id", sa.String(length=16), nullable=False),
            sa.Column("department_name", sa.String(length=120), nullable=False),
            sa.Column("country_code", sa.String(length=2), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_geo_localities"),
        )
        op.create_index("ix_geo_localities_name_folded", "geo_localities", ["name_folded"])
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "interest_locality_id" not in reader_columns:
        op.add_column("readers", sa.Column("interest_locality_id", sa.String(length=32), nullable=True))
        op.create_foreign_key(
            "fk_readers_interest_locality_id_geo_localities",
            "readers",
            "geo_localities",
            ["interest_locality_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "locality_step" not in reader_columns:
        op.add_column(
            "readers",
            sa.Column("locality_step", sa.String(length=16), server_default="done", nullable=False),
        )
        op.create_check_constraint(
            "ck_readers_locality_step",
            "readers",
            "locality_step IN ('pending', 'done', 'skipped')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    reader_columns = {column["name"] for column in inspector.get_columns("readers")} if "readers" in inspector.get_table_names() else set()
    if "locality_step" in reader_columns:
        op.drop_constraint("ck_readers_locality_step", "readers", type_="check")
        op.drop_column("readers", "locality_step")
    if "interest_locality_id" in reader_columns:
        op.drop_constraint("fk_readers_interest_locality_id_geo_localities", "readers", type_="foreignkey")
        op.drop_column("readers", "interest_locality_id")
    if "geo_localities" in inspector.get_table_names():
        op.drop_index("ix_geo_localities_name_folded", table_name="geo_localities")
        op.drop_table("geo_localities")
