import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatchcase
from functools import lru_cache
from itertools import cycle
from pathlib import Path
from typing import List, Optional
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
from .db import engine, get_tasks_db
from .service.service import (Service, _disable_service, _enable_service,
                              _remove_service, _restart_service,
                              _start_service, _stop_service,
                              extract_service_name, get_schedule_info,
                              get_unit_file_states, get_unit_files, get_units,
                              reload_unit_files, systemd_manager)

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
    
    # Import the task runs table from the database
    table = get_tasks_db().task_runs_table
    
    # Initialize a console to print the output
    console = Console()
    
    # Define the color scheme for table columns
    column_color = table_column_colors()
    
    # Create a query to select distinct task names from the task runs table
    task_names_query = sa.select(table.c.task_name).distinct()
    
    # If a match pattern is provided, filter the task names using the pattern
    if match:
        task_names_query = task_names_query.where(table.c.task_name.like(f"%{match}%"))
    
    # Create a query to select all columns from the table, filtered by task names
    # Order the results by the most recent start time and task name
    query = (
        sa.select(table)
        .where(table.c.task_name.in_(task_names_query))
        .order_by(table.c.started.desc(), table.c.task_name)
    )
    
    # Limit the number of results if a limit is provided
    if limit:
        query = query.limit(limit)
    
    # Format column names to be more readable in the table (replace underscores and title-case)
    columns = [c.name.replace("_", " ").title() for c in table.columns]
    
    # Execute the query and fetch all results in a transaction
    with engine.begin() as conn:
        rows = [dict(zip(columns, row)) for row in conn.execute(query).fetchall()]
    
    # Create a table with a simple box style and a title
    table = Table(title="Task History", box=box.SIMPLE)
    
    # Remove the 'Retries' column if all its values are zero
    if all(row["Retries"] == 0 for row in rows):
        columns.remove("Retries")
    
    # Add columns to the table with specified styles
    for c in columns:
        table.add_column(c, style=column_color(c), justify="center")
    
    # Add rows of data to the table
    for row in rows:
        table.add_row(*[str(row[c]) for c in columns])
    
    # Print the table to the console, centered
    console.print(table, justify="center")


@cli.command(name="list")
@click.argument("match", required=False)
def list_services(match):
    """List services."""
    # Get a list of all service files matching the provided pattern
    files = get_unit_files(match=match, unit_type="service")
    
    # If there are no matching files, print a message and exit
    if not files:
        click.echo(click.style("No services found.", fg="yellow"))
        return
    
    # Extract the service names from the file names
    srv_names = [extract_service_name(f) for f in files]
    
    # Sort the service names
    srv_names = sort_service_names(srv_names)
    
    # Print the sorted service names to the console
    for srv in srv_names:
        click.echo(click.style(srv, fg="cyan"))


@cli.command
@click.option(
    "-m",
    "--match",
    help="Only show history for this task name or task name pattern.",
)
@click.option(
    "-r",
    "--running",
    is_flag=True,
    help="Only show running services.",
)
def status(match: str, running: bool):
    """Get status of service(s).

    This command shows information about services managed by Taskflows.

    The output is a table with the following columns:

        Service: The name of the service.
        Description: A human-readable description of the service.
        Enabled: Whether the service is enabled to run by systemd.
        Load State: The state of the service's unit file.
        Active State: The state of the service.
        Sub State: A more detailed state of the service.
        Last Start: The time the service was last started.
        Uptime: The time the service has been running, if it is currently running.
        Last Finish: The time the service last finished.
        Next Start: The next time the service is scheduled to start, if applicable.
        Timers: The timers that trigger the service, if applicable.

    The output is sorted by service name.

    If the `--running` flag is provided, only services that are currently running are shown.
    """
    # Get all service files matching the provided pattern
    file_states = get_unit_file_states(unit_type="service", match=match)
    # If there are no matching files, print a message and exit
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

def create(
    search_in: str, include: Optional[str] = None, exclude: Optional[str] = None
) -> None:
    """
    Create taskflow services from a given source.

    Args:
        search_in (str): A directory path or module name to search for taskflow services.
        include (str, optional): A glob pattern of service names to include. Defaults to None.
        exclude (str, optional): A glob pattern of service names to exclude. Defaults to None.
    """
    # search for all Services in the given search_in path.
    services = class_inst(class_type=Service, search_in=search_in)

    # if include is given, filter the services to only include those that match the pattern.
    if include:
        services = [
            s  # type: ignore
            for s in services
            if fnmatchcase(name=s.name, pat=include)  # type: ignore
        ]

    # if exclude is given, filter the services to exclude those that match the pattern.
    if exclude:
        services = [
            s  # type: ignore
            for s in services
            if not fnmatchcase(name=s.name, pat=exclude)  # type: ignore
        ]

    # print the number of services found after filtering.
    click.echo(
        click.style(
            f"Creating {len(services)} service(s) from {search_in}",
            fg="green",
            bold=True,
        )
    )

    # create each service. defer_reload=True means that the service will be created but not started.
    for srv in services:
        srv.create(defer_reload=True)

    # reload the systemd daemon to pick up the new service files.
    reload_unit_files()

@cli.command(name="create")
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
def _create(
    search_in,
    include,
    exclude,
):
    """Create services found in a Python file or package."""
    create(search_in=search_in, include=include, exclude=exclude)
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("match", required=False)
def start(match: str):
    """Start services(s).

    Args:
        match (str): Name or pattern of services(s) to start.
    """
    if not match:
        click.echo("Must provide glob pattern")
        return
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
@click.option(
    "--timers-only",
    is_flag=True,
    help="Only enable service timers.",
)
def enable(match: str, timers_only: bool):
    """Enable currently disabled timers(s)/services(s).
    Equivalent to `systemctl --user enable --now my.timer`

    Args:
        match (str): Name or pattern of services(s) to enable.
    """
    _enable_service(get_unit_files(match=match, unit_type="timer" if timers_only else None))
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
    # Get a dict of the form {service_name: [file1, file2, ...]}
    # where each file is either a service file or a timer file
    # that belongs to the given service.
    srv_files = defaultdict(list)
    for unit_type in ("service", "timer"):
        # For each file that matches the given unit type and
        # glob pattern, add it to the list of files for the
        # service that owns it.
        for file in get_unit_files(unit_type=unit_type, match=match):
            file = Path(file)
            # The stem of the file is the name without the
            # extension. We remove the prefix that we added
            # when we created the file so that we can
            # identify the service name.
            srv_name = re.sub(
                f"^(?:stop-)?{_SYSTEMD_FILE_PREFIX}", "", file.stem
            )
            srv_files[srv_name].append(file)
    # We use the rich library to print the file contents
    # with a nice title and border.
    console = Console()
    # We sort the service names so that they are printed in
    # a consistent order.
    for srv_name in sort_service_names(srv_files.keys()):
        files = srv_files[srv_name]
        # Print a title with the service name and a line
        # underneath it.
        console.rule(f"[bold green]{srv_name}")
        # For each file, print its contents in a panel.
        for file in files:
            console.print(
                # The Panel class is a rich widget that
                # prints a box around the given text.
                Panel.fit(
                    # The contents of the file.
                    file.read_text(),
                    # The title of the panel is the name of
                    # the file.
                    title=str(file),
                ),
                # The panel should be centered horizontally.
                justify="center",
                # The style of the panel should be cyan.
                style="cyan",
            )


def table_column_colors():
    """
    Returns a function that assigns colors to table columns.

    This function uses a cycle of predefined colors and a least-recently-used
    cache to generate a consistent color for each column name. The colors are
    cycled through as column names are provided.

    Returns:
        A function that takes a column name as input and returns a color string.
    """

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


def sort_service_names(services: List[str]) -> List[str]:
    """
    Sort service names to display in a list.

    This function takes a list of strings, where each string is a service name.
    It returns a list of strings, sorted such that a service with a name that
    starts with "stop-" will come after its corresponding service without the
    "stop-" prefix.

    The sorting is done by finding the longest common substring between
    consecutive service names, and ordering them based on that substring.
    """
    # Define the prefix used for stopped services
    stop_prefix = f"stop-{_SYSTEMD_FILE_PREFIX}"
    
    # Separate services into two categories: those that start with the stop prefix and those that do not
    stop_services, non_stop_services = [], []
    for srv in services:
        if srv.startswith(stop_prefix):
            stop_services.append(srv)
        else:
            non_stop_services.append(srv)

    # Normalize non-stop service names by replacing hyphens and underscores with spaces for similarity comparison
    non_stop_services = [
        (s, s.replace("-", " ").replace("_", " ")) for s in non_stop_services
    ]
    
    # Start the ordering process with the first non-stop service
    srv, filt_srv = non_stop_services.pop(0)
    ordered = [srv]
    
    # Continue ordering the remaining non-stop services
    while non_stop_services:
        # Find the service with the greatest similarity to the current service
        best = max(non_stop_services, key=lambda o: lcsseq.similarity(filt_srv, o[1]))
        
        # Update the current service and filtered service to the best match found
        srv, filt_srv = best
        
        # Remove the matched service from the list and append it to the ordered list
        non_stop_services.remove(best)
        ordered.append(srv)
        
        # Check if the corresponding stop service exists and append it if found
        if (stp_srv := f"{stop_prefix}{srv}") in stop_services:
            ordered.append(stp_srv)
    
    # Return the fully ordered list of services
    return ordered
