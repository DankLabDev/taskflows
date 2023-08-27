from datetime import datetime

import sqlalchemy as sa

SCHEMA_NAME = "task_flows"

metadata = sa.MetaData(schema="task_flows")

task_runs_table = sa.Table(
    "task_runs",
    metadata,
    sa.Column("task_name", sa.String, primary_key=True),
    sa.Column(
        "started",
        sa.DateTime(timezone=False),
        default=datetime.utcnow,
        primary_key=True,
    ),
    sa.Column("finished", sa.DateTime(timezone=False)),
    sa.Column("retries", sa.Integer, default=0),
    sa.Column("status", sa.String),
    sa.Column("return_value", sa.String),
)

task_errors_table = sa.Table(
    "task_errors",
    metadata,
    sa.Column("task_name", sa.String, primary_key=True),
    sa.Column(
        "time", sa.DateTime(timezone=False), default=datetime.utcnow, primary_key=True
    ),
    sa.Column("type", sa.String),
    sa.Column("message", sa.String),
)
