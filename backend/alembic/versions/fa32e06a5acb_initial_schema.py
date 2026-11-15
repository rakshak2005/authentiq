"""initial_schema

Revision ID: fa32e06a5acb
Revises: 
Create Date: 2026-11-15 14:19:21.011086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "fa32e06a5acb"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(conn)
    return table in inspector.get_table_names()


def _has_column(conn, table: str, column: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(conn, table: str, index_name: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return index_name in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    """Upgrade schema.

    Uses SQLAlchemy's inspector so this migration is idempotent and works on
    both SQLite (tests) and PostgreSQL (production). Safe to run after
    Base.metadata.create_all() has already created columns defined on models.

    Only adds columns/indexes to tables that already exist. If `create_all()`
    created the table already, the column/index already exists and is skipped.
    """
    conn = op.get_context().connection

    if _table_exists(conn, "disputes"):
        if not _has_column(conn, "disputes", "determination"):
            op.add_column("disputes", sa.Column("determination", sa.String(length=32), nullable=True))
        if not _has_column(conn, "disputes", "resolution_reason"):
            op.add_column("disputes", sa.Column("resolution_reason", sa.Text(), nullable=True))

    if _table_exists(conn, "ledger_transactions"):
        if not _has_index(conn, "ledger_transactions", "ix_ledger_transactions_idempotency_key"):
            op.create_index(
                op.f("ix_ledger_transactions_idempotency_key"),
                "ledger_transactions",
                ["idempotency_key"],
                unique=True,
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_context().connection

    if _table_exists(conn, "disputes"):
        if _has_column(conn, "disputes", "resolution_reason"):
            op.drop_column("disputes", "resolution_reason")
        if _has_column(conn, "disputes", "determination"):
            op.drop_column("disputes", "determination")
    if _table_exists(conn, "ledger_transactions"):
        if _has_index(conn, "ledger_transactions", "ix_ledger_transactions_idempotency_key"):
            op.drop_index(
                op.f("ix_ledger_transactions_idempotency_key"),
                table_name="ledger_transactions",
            )
