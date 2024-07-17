import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatchcase
from functools import lru_cache
from itertools import cycle
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

import click
import sqlalchemy as sa
from click.core import Group
from dynamic_imports import class_inst
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textdistance import lcsseq

from taskflows import _SYSTEMD_FILE_PREFIX

from .config import config
from .db import task_flows_db
from .service.service import (
    Service,
    _disable_service,
    _enable_service,
    _remove_service,
    _restart_service,
    _start_service,
    _stop_service,
    get_schedule_info,
    get_unit_file_states,
    get_unit_files,
    get_units,
    reload_unit_files,
    systemd_manager,
)

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
    with db.engine.begin() as conn:
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
@click.argument("match", required=False)
def list_services(match):
    """List services."""
    files = get_unit_files(match=match, unit_type="service")
    if files:
        srv_names = sort_service_names([extract_service_name(f) for f in files])
        for srv in srv_names:
            click.echo(click.style(srv, fg="cyan"))
    else:
        click.echo(click.style("No services found.", fg="yellow"))


@cli.command
@click.option(
    "-m", "--match", help="Only show history for this task name or task name pattern."
)
@click.option("-r", "--running", is_flag=True, help="Only show running services.")
def status(match: str, running: bool):
    """Get status of service(s)."""
    file_states = get_unit_file_states(unit_type="service", match=match)
    if not file_states:
        click.echo(click.style("No services found.", fg="yellow"))
        return
    manager = systemd_manager()
    units_meta = defaultdict(dict)
    for file_path, enabled_status in file_states.items():
        unit_file = os.path.basename(file_path)
        unit_meta = units_meta[unit_file]
        unit_meta["Enabled"] = enabled_status
        # TODO not load?
        manager.LoadUnit(unit_file)
    units = get_units(
        unit_type="service",
        match=match,
        states=None,
    )
    for unit in units:
        units_meta[unit["unit_name"]].update(unit)
    for unit_name, data in units_meta.items():
        data.update(get_schedule_info(unit_name))
    for unit_name, data in units_meta.items():
        data["Service"] = extract_service_name(unit_name)
    units_meta = {
        k: v for k, v in units_meta.items() if v.get("load_state") != "not-found"
    }
    columns = [
        "Service",
        "description",
        "Enabled",
        "load_state",
        "active_state",
        "sub_state",
        "Last Start",
        "Uptime",
        "Last Finish",
        "Next Start",
        "Timers",
    ]
    column_value_colors = {
        "Enabled": {"enabled": "green", "enabled-runtime": "yellow", "disabled": "red"},
        "load_state": {
            # loaded: The unit file has been successfully read and parsed by systemd, and the unit is ready to be started.
            "loaded": "green",
            # error: There was an error while loading the unit file, making the unit unusable.
            "error": "red",
            # merged: The unit file has been merged with another unit file of the same name (common for drop-in configurations).
            "merged": "yellow",
            # stub: The unit has been created dynamically and has no backing unit file.
            "stub": "yellow",
            # not-found: The unit file could not be found by systemd.
            "not-found": "red",
            # bad-setting: The unit file contains invalid or unsupported settings.
            "bad-setting": "red",
            # masked: The unit is masked, meaning it is linked to /dev/null and cannot be started.
            "masked": "red",
        },
        "active_state": {
            # active: The unit is active and running as expected.
            "active": "green",
            # activating: The unit is in the process of starting up.
            "activating": "yellow",
            # deactivating: The unit is in the process of shutting down.
            "deactivating": "yellow",
            # inactive: The unit is not active.
            "inactive": "yellow",
            # failed: The unit has failed.
            "failed": "red",
            # reloading: The unit is reloading its configuration.
            "reloading": "yellow",
        },
        "sub_state": {
            # running: The service is running and operational.
            "running": "green",
            # exited: The service has successfully completed its work and exited.
            "exited": "green",
            # waiting: The service is waiting for an event (often used with oneshot services).
            "waiting": "yellow",
            # start-pre: The service is in the process of executing the ExecStartPre command.
            "start-pre": "green",
            # start: The service is in the process of starting up.
            "start": "green",
            # start-post: The service is in the process of executing the ExecStartPost command.
            "start-post": "green",
            # reloading: The service is reloading its configuration.
            "reloading": "yellow",
            # stop: The service is in the process of stopping.
            "stop": "yellow",
            # stop-sigterm: The service is being terminated with the SIGTERM signal.
            "stop-sigterm": "yellow",
            # stop-sigkill: The service is being forcibly killed with the SIGKILL signal.
            "stop-sigkill": "yellow",
            # stop-post: The service is in the process of executing the ExecStopPost command.
            "stop-post": "yellow",
            # failed: The service has failed.
            "failed": "red",
            # auto-restart: The service is in the process of restarting automatically.
            "auto-restart": "orange1",
            # dead: The service is not running.
            "dead": "yellow",
        },
    }
    table = Table(
        box=box.SQUARE_DOUBLE_HEAD,
        show_lines=True,
        title=f"Service Status (times in {config.display_timezone})",
    )
    for col in columns:
        table.add_column(
            col.replace("_", " ").title(),
            style="cyan" if col not in column_value_colors else None,
            justify="center",
            no_wrap=False,
            overflow="fold",
        )
    srv_data = {row["Service"]: row for row in units_meta.values()}
    assert len(srv_data) == len(units_meta)
    for srv in sort_service_names(srv_data.keys()):
        row = srv_data[srv]
        if running and row.get("active_state") != "active":
            continue
        row["Timers"] = (
            "\n".join(
                [f"{t['base']}({t['spec']})" for t in row.get("Timers Calendar", [])]
                + [
                    f"{t['base']}({t['offset']})"
                    for t in row.get("Timers Monotonic", [])
                ]
            )
            or "-"
        )
        if row.get("active_state") == "active" and (
            last_start := row.get("Last Start")
        ):
            row["Uptime"] = str(datetime.now() - last_start).split(".")[0]
        for dt_col in (
            "Last Start",
            "Last Finish",
            "Next Start",
        ):
            if isinstance(row.get(dt_col), datetime):
                row[dt_col] = (
                    row[dt_col]
                    .astimezone(ZoneInfo(config.display_timezone))
                    .strftime("%Y-%m-%d %I:%M:%S %p")
                )
        row_text = []
        for col in columns:
            if (val := row.get(col)) is None:
                val = "-"
            row_text.append(
                Text(
                    str(val),
                    overflow="fold",
                    style=column_value_colors.get(col, {}).get(val),
                )
            )
        table.add_row(*row_text)
    Console().print(table, justify="center")


@cli.command
@click.argument("service_name")
def logs(service_name: str):
    """Show logs for a service."""
    # TODO check if arg has extension.
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
    services = class_inst(class_type=Service, search_in=search_in)
    if include:
        services = [s for s in services if fnmatchcase(include, s.name)]
    if exclude:
        services = [s for s in services if not fnmatchcase(exclude, s.name)]
    click.echo(
        click.style(
            f"Creating {len(services)} service(s) from {search_in}",
            fg="green",
            bold=True,
        )
    )
    for srv in services:
        srv.create(defer_reload=True)
    reload_unit_files()
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def start(match: str):
    """Start services(s).

    Args:
        match (str): Name or pattern of services(s) to start.
    """
    _start_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def stop(match: str):
    """Stop running service(s).

    Args:
        match (str): Name or name pattern of service(s) to stop.
    """
    _stop_service(get_unit_files(match=match))
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
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
@click.argument("match", required=False)
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
    srv_files = defaultdict(list)
    for unit_type in ("service", "timer"):
        for file in get_unit_files(unit_type=unit_type, match=match):
            file = Path(file)
            srv_files[
                re.sub(f"^(?:stop-)?{_SYSTEMD_FILE_PREFIX}", "", file.stem)
            ].append(file)
    console = Console()
    for srv_name in sort_service_names(srv_files.keys()):
        files = srv_files[srv_name]
        console.rule(f"[bold green]{srv_name}")
        for file in files:
            console.print(
                Panel.fit(file.read_text(), title=str(file)),
                justify="center",
                style="cyan",
            )


def table_column_colors():
    colors_gen = cycle(
        [
            "cyan",
            "light_steel_blue",
            "orchid",
            "magenta",
            "dodger_blue1",
        ]
    )

    @lru_cache
    def column_color(col_name: str) -> str:
        return next(colors_gen)

    return column_color


def sort_service_names(services):
    stop_prefix = f"stop-{_SYSTEMD_FILE_PREFIX}"
    stop_services, non_stop_services = [], []
    for srv in services:
        if srv.startswith(stop_prefix):
            stop_services.append(srv)
        else:
            non_stop_services.append(srv)
    non_stop_services = [
        (s, s.replace("-", " ").replace("_", " ")) for s in non_stop_services
    ]
    srv, filt_srv = non_stop_services.pop(0)
    ordered = [srv]
    while non_stop_services:
        best = max(non_stop_services, key=lambda o: lcsseq.similarity(filt_srv, o[1]))
        srv, filt_srv = best
        non_stop_services.remove(best)
        ordered.append(srv)
        if (stp_srv := f"{stop_prefix}{srv}") in stop_services:
            ordered.append(stp_srv)
    return ordered


def extract_service_name(unit: str | Path) -> List[str]:
    return re.sub(f"^{_SYSTEMD_FILE_PREFIX}", "", Path(unit).stem)
