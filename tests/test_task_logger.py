import random
from importlib import reload
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa

import taskflows


def create_task_logger(monkeypatch, request, db: Literal["sqlite", "postgres"]):
    if db == "sqlite":
        db_url = "sqlite:///taskflows_test.sqlite"
    elif db == "postgres":
        db_url = request.config.getoption("--pg-url")
    monkeypatch.setenv("TASKFLOWS_DB_URL", db_url)
    reload(taskflows.db)
    reload(taskflows.tasks)
    reload(taskflows)
    from taskflows.tasks import TaskLogger

    return TaskLogger(
        name=str(uuid4()),
        required=False,
        exit_on_complete=False,
    )


@pytest.mark.parametrize("db", ["sqlite", "postgres"])
def test_on_task_start(monkeypatch, request, db):
    task_logger = create_task_logger(monkeypatch, request, db)
    task_logger.on_task_start()
    table = task_logger.db.task_runs_table
    query = sa.select(table.c.task_name, table.c.started).where(
        table.c.task_name == task_logger.name
    )
    with task_logger.engine.begin() as conn:
        tasks = list(conn.execute(query).fetchall())
    assert len(tasks) == 1
    # name and started columns should be null.
    assert all(v is not None for v in tasks[0])


@pytest.mark.parametrize("db", ["sqlite", "postgres"])
def test_on_task_error(monkeypatch, request, db):
    task_logger = create_task_logger(monkeypatch, request, db)
    error = Exception(str(uuid4()))
    task_logger.on_task_error(error)
    table = task_logger.db.task_errors_table
    query = sa.select(table).where(table.c.task_name == task_logger.name)
    with task_logger.engine.begin() as conn:
        errors = list(conn.execute(query).fetchall())
    assert len(errors) == 1
    # no columns should be null.
    assert all(v is not None for v in errors[0])


@pytest.mark.parametrize("db", ["sqlite", "postgres"])
def test_on_task_finish(monkeypatch, request, db):
    task_logger = create_task_logger(monkeypatch, request, db)
    task_logger.on_task_start()
    task_logger.on_task_finish(
        success=random.choice([True, False]),
        retries=random.randint(0, 5),
        return_value=str(uuid4()),
    )
    table = task_logger.db.task_runs_table
    query = sa.select(table).where(table.c.task_name == task_logger.name)
    with task_logger.engine.begin() as conn:
        tasks = list(conn.execute(query).fetchall())
    assert len(tasks) == 1
    # no columns should be null.
    assert all(v is not None for v in tasks[0])
