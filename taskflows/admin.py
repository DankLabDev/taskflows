import re
import os
import subprocess
from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatchcase
from functools import lru_cache
from itertools import cycle
from pathlib import Path

import click
from rich.rule import Rule
import sqlalchemy as sa
from click.core import Group
from dynamic_imports import class_inst
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .db import task_flows_db
from .service.service import (
    DockerService,
    Service,
    _disable_service,
    _enable_service,
    _remove_service,
    _start_service,
    _restart_service,
    _stop_service,
    get_unit_file_states,
    get_unit_files,
    get_schedule_info,
    get_units,
)
from .utils import _SYSTEMD_FILE_PREFIX


cli = Group("taskflows", chain=True)


@cli.command
@click.option(
    "-l",
    "--limit",
    type=int,
    default=3,
    help="Number of most recent task runs to show.",
)
@click.option(
    "-m", "--match", help="Only show history for this task name or task name pattern."
)
def history(limit: int, match: str = None):
    """Print task run history to console display."""
    # https://rich.readthedocs.io/en/stable/appendix/colors.html#appendix-colors
    db = task_flows_db()
    table = db.task_runs_table
    console = Console()
    column_color = table_column_colors()
    task_names_query = sa.select(table.c.task_name).distinct()
    if match:
        task_names_query = task_names_query.where(table.c.task_name.like(f"%{match}%"))
    query = (
        sa.select(table)
        .where(table.c.task_name.in_(task_names_query))
        .order_by(table.c.started.desc(), table.c.task_name)
    )
    if limit:
        query = query.limit(limit)
    columns = [c.name.replace("_", " ").title() for c in table.columns]
    with task_flows_db().engine.begin() as conn:
        rows = [dict(zip(columns, row)) for row in conn.execute(query).fetchall()]
    table = Table(title="Task History", box=box.SIMPLE)
    if all(row["Retries"] == 0 for row in rows):
        columns.remove("Retries")
    for c in columns:
        table.add_column(c, style=column_color(c), justify="center")
    for row in rows:
        table.add_row(*[str(row[c]) for c in columns])
    console.print(table, justify="center")


@cli.command(name="list")
@click.option("--state", "-s", multiple=True, help="List services in state.")
@click.option("--match", "-m", help="Match service name or service name pattern.")
def list_services(state, match):
    """List services."""
    files = get_unit_files(states=state, match=match, unit_type="service")
    if files:
        for f in files:
            click.echo(
                click.style(
                    re.sub(f"^{_SYSTEMD_FILE_PREFIX}", "", Path(f).stem), fg="cyan"
                )
            )
    else:
        click.echo(click.style("No services found.", fg="yellow"))


@cli.command
@click.option(
    "-m", "--match", help="Only show for this service name or service name pattern."
)
def status(match: str):
    """Get status of service(s)."""
    file_states = get_unit_file_states(unit_type="service", match=match)
    if not file_states:
        click.echo(click.style("No services found.", fg="yellow"))
        return
    units_meta = defaultdict(dict)
    for file_path, enabled_status in file_states.items():
        unit_file = os.path.basename(file_path)
        unit_meta = units_meta[unit_file]
        unit_meta["Enabled"] = enabled_status
    for unit_name, data in units_meta.items():
        data.update(get_schedule_info(unit_name))
    units = get_units(
        unit_type="service",
        match=match,
        states=None,
    )
    for unit in units:
        units_meta[unit["unit_name"]].update(unit)
    for unit_name, data in units_meta.items():
        data["Service"] = unit_name.replace(".service", "").replace(
            _SYSTEMD_FILE_PREFIX, ""
        )
    columns = [
        "Service",
        "Description",
        "Enabled",
        "Load State",
        "Active State",
        "Sub State",
        "Last Start",
        "Last Finish",
        "Next Start",
        "Timers",
    ]
    table = Table(box=box.SQUARE_DOUBLE_HEAD)
    column_color = table_column_colors()
    for col in columns:
        table.add_column(
            col.replace("_", " ").title(),
            style=column_color(col),
            justify="center",
            no_wrap=False,
            overflow="fold",
        )
    for row in units_meta.values():
        row["Timers"] = "".join(
            [f"{t['base']}({t['spec']})" for t in row["Timers Calendar"]]
            + [f"{t['base']}({t['offset']})" for t in row["Timers Monotonic"]]
        )
        for dt_col in (
            "Last Start",
            "Last Finish",
            "Next Start",
        ):
            if isinstance(row[dt_col], datetime):
                row[dt_col] = row[dt_col].strftime("%Y-%m-%d %H:%M:%S")
        for k, v in row.items():
            if v is None:
                row[k] = "-"
        table.add_row(
            *[Text(str(row.get(c, "-")), overflow="fold") for c in columns],
            Rule(style="dim"),
        )
    Console().print(table, justify="center")


@cli.command
@click.argument("service_name")
def logs(service_name: str):
    """Show logs for a service."""
    click.echo(
        click.style(
            f"Run `journalctl --user -r -u {_SYSTEMD_FILE_PREFIX}{service_name}` for more.",
            fg="yellow",
        )
    )
    subprocess.run(
        f"journalctl --user -f -u {_SYSTEMD_FILE_PREFIX}{service_name}".split()
    )


@cli.command
@click.argument("search-in")
@click.option(
    "-i",
    "--include",
    type=str,
    help="Name or glob pattern of services that should be included.",
)
@click.option(
    "-e",
    "--exclude",
    type=str,
    help="Name or glob pattern of services that should be excluded.",
)
def create(
    search_in,
    include,
    exclude,
):
    """Create services found in a Python file or package."""
    services = []
    for class_t in (DockerService, Service):
        services.extend(class_inst(class_type=class_t, search_in=search_in))
    if include:
        services = [s for s in services if fnmatchcase(include, s.name)]
    if exclude:
        services = [s for s in services if not fnmatchcase(exclude, s.name)]
    services_str = "\n\n".join([str(s) for s in services])
    click.echo(
        click.style(
            f"Creating {len(services)} service(s) from {search_in}",
            fg="green",
            bold=True,
        )
    )
    click.echo(click.style(f"\n{services_str}", fg="cyan"))
    for srv in services:
        srv.create()
    # systemd_manager().Reload()
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match")
def start(match: str):
    """Start services(s).

    Args:
        match (str): Name or pattern of services(s) to start.
    """
    _start_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match")
def stop(match: str):
    """Stop running service(s).

    Args:
        match (str): Name or name pattern of service(s) to stop.
    """
    _stop_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match")
def restart(match: str):
    """Restart running service(s).

    Args:
        match (str): Name or name pattern of service(s) to restart.
    """
    _restart_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def enable(match: str):
    """Enable currently disabled services(s).
    Equivalent to `systemctl --user enable --now my.timer`

    Args:
        match (str): Name or pattern of services(s) to enable.
    """
    _enable_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def disable(match: str):
    """Disable services(s).

    Args:
        match (str): Name or pattern of services(s) to disable.
    """
    _disable_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match")
def remove(match: str):
    """Remove service(s).

    Args:
        match (str): Name or name pattern of service(s) to remove.
    """
    _remove_service(
        service_files=get_unit_files(unit_type="service", match=match),
        timer_files=get_unit_files(unit_type="timer", match=match),
    )
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def show(match: str):
    """Show services file contents."""
    files = defaultdict(list)
    for f in get_unit_files(unit_type="service", match=match):
        files[f.split("/")[-1]].append(f)
    for f in get_unit_files(unit_type="timer", match=match):
        files[f.split("/")[-1]].append(f)
    colors_gen = cycle(["white", "cyan"])
    for i, srvs in enumerate(files.values()):
        if i > 0:
            click.echo("\n")
        click.echo(
            click.style(
                "\n\n".join([Path(s).read_text() for s in srvs]), fg=next(colors_gen)
            )
        )


def table_column_colors():
    colors_gen = cycle(["orange3", "green", "cyan", "magenta", "dodger_blue1", "red"])

    @lru_cache
    def column_color(col_name: str) -> str:
        return next(colors_gen)

    return column_color
