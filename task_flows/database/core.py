import os
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from task_flows.utils import logger

from .tables import SCHEMA_NAME, task_errors_table, task_runs_table


@lru_cache
def engine_from_env() -> Engine:
    """Create an SQLAlchemy engine and cache it so we only create it once.
    The open connections can be closed by: engine_from_env().dispose()

    Returns:
        Engine: The SQLAlchemy engine.
    """
    return sa.create_engine(os.environ["TASK_FLOWS_DB"])


@lru_cache
def create_missing_tables():
    """Create any tables that do not currently exist in the database."""
    with engine_from_env().begin() as conn:
        if not conn.dialect.has_schema(conn, schema=SCHEMA_NAME):
            logger.info("Creating schema '%s'", SCHEMA_NAME)
            conn.execute(sa.schema.CreateSchema(SCHEMA_NAME))
        for table in (
            task_runs_table,
            task_errors_table,
        ):
            table.create(conn, checkfirst=True)
