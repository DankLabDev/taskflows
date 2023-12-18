import os
from datetime import datetime, timezone
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from taskflows.utils import logger

SCHEMA_NAME = "taskflows"


@lru_cache
def engine_from_env() -> Engine:
    """Create an SQLAlchemy engine and cache it so we only create it once.
    The open connections can be closed by: engine_from_env().dispose()

    Returns:
        Engine: The SQLAlchemy engine.
    """
    return sa.create_engine(os.environ["TASKFLOWS_DB"])


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


metadata = sa.MetaData(schema="taskflows")

service_runs_table = sa.Table(
    "service_runs",
    metadata,
    sa.Column("service_name", sa.String, primary_key=True),
    sa.Column(
        "started",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    ),
    sa.Column("finished", sa.DateTime(timezone=True)),
    sa.Column("success", sa.Boolean),
)

task_runs_table = sa.Table(
    "task_runs",
    metadata,
    sa.Column("task_name", sa.String, primary_key=True),
    sa.Column(
        "started",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    ),
    sa.Column("finished", sa.DateTime(timezone=True)),
    sa.Column("retries", sa.Integer, default=0),
    sa.Column("status", sa.String),
    sa.Column("return_value", sa.String),
)

task_errors_table = sa.Table(
    "task_errors",
    metadata,
    sa.Column("task_name", sa.String, primary_key=True),
    sa.Column(
        "time",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    ),
    sa.Column("type", sa.String),
    sa.Column("message", sa.String),
)
