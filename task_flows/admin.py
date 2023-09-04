import re
import subprocess
from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatch
from time import time
from typing import Any, Dict, List, Optional, Tuple

import click
import sqlalchemy as sa
from click.core import Group as ClickGroup
from dynamic_imports import import_module
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from tqdm import tqdm

from .database import engine_from_env
from .database.tables import task_runs_table
from .schedule import ScheduledTask
from .systemd.core import (
    _names_from_files,
    disable_scheduled_task,
    enable_scheduled_task,
    remove_scheduled_task,
    restart_task,
    run_task,
    stop_task,
)
from .utils import _FILE_PREFIX, parse_systemctl_tables

# TODO add host argument and forward commands via Fabric, record task host in database, pull stats and logs from hosts.

cli = ClickGroup("task-flows")


def task_runs_history(
    count: Optional[int] = None, match: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Get task run history.

    Args:
        count (Optional[int], optional): Return the `count` latest task runs. Defaults to None.
        match (Optional[str], optional): Return history for task names that contain `match` substring. Defaults to None.

    Returns:
        Dict[str, List[Dict[str, Any]]]: Map task name to task run history.
    """
    query = sa.select(task_runs_table.c.task_name).distinct()
    if match:
        query = query.where(task_runs_table.c.task_name.like(f"%{match}%"))
    engine = engine_from_env()
    with engine.begin() as conn:
        task_names = list(conn.execute(query).scalars())
    columns = [c.name.replace("_", " ").title() for c in task_runs_table.columns]
    tasks_hist = {}
    for task_name in task_names:
        query = (
            sa.select(task_runs_table)
            .where(task_runs_table.c.task_name == task_name)
            .order_by(task_runs_table.c.started.desc())
        )
        if count:
            query = query.limit(count)
        with engine.begin() as conn:
            rows = [dict(zip(columns, row)) for row in conn.execute(query).fetchall()]
        tasks_hist[task_name] = rows
    return tasks_hist


def task_runs_history_tables(*args, **kwargs) -> Dict[str, Table]:
    """Get task run history for console display.

    Returns:
        Dict[str, Table]: Map task name to task run history table.
    """
    history = task_runs_history(*args, **kwargs)
    task_hist_tables = {}
    for task_name, rows in history.items():
        columns = list(rows[0].keys())
        columns.remove("Task Name")
        table = Table(title="Task Runs")
        if all(row["Return Value"] is None for row in rows):
            columns.remove("Return Value")
        if all(row["Retries"] == 0 for row in rows):
            columns.remove("Retries")
        for c in columns:
            table.add_column(c, style="cyan", justify="default")
        for row in rows:
            table.add_row(*[str(row[c]) for c in columns])
        task_hist_tables[task_name] = table
    return task_hist_tables


def tasks_status(match: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Map task name to status info."""
    task_meta = defaultdict(dict)
    # get task status.
    for timer_sched in parse_systemctl_tables(["systemctl", "--user", "list-timers"]):
        if task_name := re.search(r"^task_flow_([\w-]+)\.timer", timer_sched["UNIT"]):
            task_meta[task_name.group(1)].update(
                {
                    "Next Run": f"{timer_sched['NEXT']} ({timer_sched['LEFT']})",
                    "Last Run": f"{timer_sched['LAST']} ({timer_sched['PASSED']})",
                }
            )
    for service_status in parse_systemctl_tables(
        "systemctl --user list-units --type=service".split()
    ):
        if task_name := re.search(
            r"^task_flow_([\w-]+)\.service", service_status["UNIT"]
        ):
            task_name = task_name.group(1)
            meta = task_meta[task_name]
            meta["Task"] = (
                f'{task_name} ({service_status["DESCRIPTION"]})'
                if service_status["DESCRIPTION"]
                else task_name
            )
            if service_status["ACTIVE"] == "active":
                meta["Last Run"] += " (running)"
    if match:
        task_meta = {k: v for k, v in task_meta.items() if fnmatch(k, f"*{match}*")}
    for task_name, meta in task_meta.items():
        if "Task" not in meta:
            meta["Task"] = task_name
    task_meta = dict(
        sorted(
            task_meta.items(),
            key=lambda row: time()
            if (
                "(running)" in row[1]["Last Run"]
                or not (
                    dt := re.search(
                        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", row[1]["Last Run"]
                    )
                )
            )
            else datetime.fromisoformat(dt.group(0)).timestamp(),
        )
    )
    return task_meta


@cli.command()
@click.option("-m", "--match")
@click.option(
    "-h",
    "--history",
    type=int,
    default=3,
    help="Number of most recent task runs to show.",
)
def show(match: Optional[str] = None, history: Optional[int] = None):
    """Show task status and history."""
    history = task_runs_history_tables(history, match)
    status = tasks_status(match)
    task_names = {*history.keys(), *status.keys()}
    panels = []
    for task_name in task_names:
        group_members = []
        if task_status := status.get(task_name):
            task_title = task_status.pop("Task")
            text = Text(justify="center")
            for k, v in task_status.items():
                text.append(f"{k}: ", style="yellow3 bold")
                text.append(f"{v}\n", style="yellow3")
            group_members.append(text)
        else:
            task_title = task_name
        if task_name in history:
            group_members.append(history[task_name])
        panels.append(
            Panel(
                Group(*group_members),
                title="[spring_green1]" + task_title,
                border_style="spring_green1",
            )
        )
    Console().print(Group(*panels), justify="center")


@cli.command()
@click.argument("task_name")
def logs(task_name: str):
    """Show logs for a task."""
    subprocess.run(f"journalctl --user -u {_FILE_PREFIX}{task_name}".split())


@cli.command()
@click.argument("tasks_file", default="deployments.py")
@click.option(
    "-i",
    "--include",
    multiple=True,
    help="Name(s) of task(s)/task list(s) that should be scheduled.",
)
@click.option(
    "-e",
    "--exclude",
    multiple=True,
    help="Name(s) of task(s)/task list(s) that should not be scheduled.",
)
def create(
    tasks_file: str,
    include: Optional[Tuple[str]] = None,
    exclude: Optional[Tuple[str]] = None,
):
    """Create scheduled tasks from a Python file containing tasks/task lists or dict with tasks or task lists as values."""
    tasks = {}
    if tasks_file.endswith(".py"):
        for member in import_module(tasks_file).__dict__.values():
            if isinstance(member, ScheduledTask):
                tasks[member.task_name] = member
            elif isinstance(member, (list, tuple)):
                tasks.update(
                    {m.task_name: m for m in member if isinstance(m, ScheduledTask)}
                )
            elif isinstance(member, dict):
                for k, v in member.items():
                    if isinstance(v, ScheduledTask):
                        tasks[v.task_name] = v
                        tasks[k] = v
                    elif isinstance(v, (list, tuple)) and (
                        v := {m.task_name: m for m in v if isinstance(m, ScheduledTask)}
                    ):
                        tasks.update(v)
                        tasks[k] = v
    if include:
        tasks = {k: v for k, v in tasks.items() if any(text in k for text in include)}
    if exclude:
        tasks = {k: v for k, v in tasks.items() if any(text in k for text in exclude)}
    click.echo(
        click.style(f"Creating {len(tasks)} task(s) from {tasks_file}.", fg="cyan")
    )
    for task in tasks.values():
        task.create()
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("task_name")
def run(task_name: str):
    """Run a task.

    Args:
        task_name (str): Name of the task to run.
    """
    run_task(task_name)


@cli.command()
@click.argument("task_name")
def stop(task_name: str):
    """Stop a running task.

    Args:
        name (str): Name of task to stop.
    """
    stop_task(task_name)


@cli.command()
@click.argument("task_name")
def restart(task_name: str):
    """Restart a running task.

    Args:
        name (str): Name of task to restart.
    """
    restart_task(task_name)


@cli.command()
@click.option(
    "-n", "--names", "task_names", multiple=True, help="Names of task(s) to enable."
)
def enable(task_names: Optional[Tuple[str]] = None):
    """Reenable a currently disabled scheduled task."""
    for task_name in tqdm(task_names):
        enable_scheduled_task(task_name)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.option(
    "-n", "--names", "task_names", multiple=True, help="Names of task(s) to disable."
)
def disable(task_names: Optional[Tuple[str]] = None):
    """Disable a scheduled task."""
    for task_name in tqdm(task_names):
        disable_scheduled_task(task_name)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.option(
    "-n", "--names", "task_names", multiple=True, help="Names of task(s) to remove."
)
def remove(
    task_names: Optional[Tuple[str]] = None,
):
    """Disable task(s) and remove any Systemd and Docker artifacts."""
    task_names = task_names or _names_from_files("task")
    if not task_names:
        click.echo(click.style("No tasks to remove!", fg="yellow"))
        return
    for task_name in tqdm(task_names):
        # click.echo(click.style(f"Removing scheduled task {task_name}", fg="cyan"))
        remove_scheduled_task(task_name)
        # TODO remove docker artifacts
    click.echo(click.style("Done!", fg="green"))
