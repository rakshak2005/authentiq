"""Lightweight, idempotent schema upgrades.

DEPRECATED: Alembic (backend/alembic/) is now the canonical migration runner and
is invoked from ``app.core.database.init_db()`` via ``alembic upgrade head``.
This module is kept only as a fallback for environments that cannot run Alembic.

Every statement is written so that running it twice is a no-op.
"""

import logging

from sqlalchemy import inspect, text

from app.core.database import engine

logger = logging.getLogger("authentiq")

# (table, column, portable DDL type)
COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("registrations", "team_project_id", "VARCHAR(36)"),
    ("ledger_transactions", "idempotency_key", "VARCHAR(120)"),
    ("ledger_transactions", "contract_address", "VARCHAR(42)"),
    ("ledger_transactions", "chain_id", "INTEGER"),
    ("ledger_transactions", "revision", "INTEGER"),
    ("disputes", "determination", "VARCHAR(32)"),
    ("disputes", "resolution_reason", "TEXT"),
)

# (index name, table, column)
INDEX_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("ix_registrations_team_project_id", "registrations", "team_project_id"),
    ("ix_ledger_idempotency_key", "ledger_transactions", "idempotency_key"),
)


def ensure_schema() -> None:
    """Add columns and indexes that are missing from an existing database.

    Kept for backward compatibility. Preferred path is Alembic
    (``alembic upgrade head``), run from ``init_db()``.
    """
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

        for table, column, ddl_type in COLUMN_MIGRATIONS:
            if table not in tables:
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column in columns:
                continue
            logger.info("Applying schema upgrade: %s.%s", table, column)
            connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl_type}'))

        for index_name, table, column in INDEX_MIGRATIONS:
            if table not in tables:
                continue
            indexes = {item["name"] for item in inspector.get_indexes(table)}
            if index_name in indexes:
                continue
            logger.info("Creating index: %s", index_name)
            connection.execute(
                text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("{column}")')
            )
