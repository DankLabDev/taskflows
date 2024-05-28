import re
import subprocess
from collections import defaultdict
from fnmatch import fnmatchcase
from functools import lru_cache
from itertools import cycle
from pprint import pformat
from typing import List, Union

import click
import sqlalchemy as sa
from click.core import Group
from dynamic_imports import class_inst
from rich import box
from rich.console import Console
from rich.table import Table

from .db import task_flows_db
from .service import (
    DockerService,
    Service,
    disable_service,
    enable_service,
    get_service_files,
    get_timer_files,
    remove_service,
    restart_service,
    service_cmd,
    service_runs,
    start_service,
    stop_service,
    systemd_dir,
    systemd_manager,
)
from .utils import _SYSTEMD_FILE_PREFIX


def discover_services(search_in: str) -> List[Union[DockerService, Service]]:
    """Search for services in a Python module or package."""
    services = []
    for class_t in (DockerService, Service):
        services.extend(class_inst(class_type=class_t, search_in=search_in))
    return services


def get_service_names():
    """Get names of all services that have been created."""
    return [f.stem.replace(_SYSTEMD_FILE_PREFIX, "") for f in get_service_files()]


cli = Group("taskflows", chain=True)


@cli.command()
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
def list_services():
    """List services."""
    services = get_service_names()
    if services:
        click.echo(pformat(services))
    else:
        click.echo(click.style("No services found.", fg="yellow"))


@cli.command
@click.argument("service_name", required=False)
def status(service_name: str):
    """Get status of service(s)."""
    if service_name:
        service_names = [service_name]
    else:
        service_names = get_service_names()
    for sn in service_names:
        proc = service_cmd(service_name=sn, command="status")
        err = proc.stderr.decode().strip()
        info = proc.stdout.decode().strip()
        state = systemd_manager().GetUnitFileState(f"taskflow_{sn}.service").strip()
        print(f"----------{sn} status----------\n{state}\n{err}\n{info}\n\n")


@cli.command()
@click.option(
    "-m", "--match", help="Only show for this service name or service name pattern."
)
def schedule(match: str = None):
    """List service schedules."""
    table = _service_schedules_table(running_only=False, match=match)
    if table is not None:
        Console().print(table, justify="center")
    else:
        click.echo(click.style("No services found.", fg="yellow"))


@cli.command()
def running():
    """List running services."""
    table = _service_schedules_table(running_only=True)
    if table is not None:
        Console().print(table, justify="center")
    else:
        click.echo(click.style("No services running.", fg="yellow"))


@cli.command()
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


@cli.command()
@click.argument("search-in")
@click.option(
    "-c",
    "--command",
    type=str,
    help="Command that should be ran on discovered services (e.g. create, enable, disable, remove, restart, run, stop).",
)
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
def search(
    search_in,
    command,
    include,
    exclude,
):
    """Search for and run a command on services from a Python file or package."""
    services = discover_services(search_in)
    if include:
        services = [s for s in services if fnmatchcase(include, s.name)]
    if exclude:
        services = [s for s in services if not fnmatchcase(exclude, s.name)]
    services_str = "\n\n".join([str(s) for s in services])
    if command:
        click.echo(
            click.style(
                f"{command.title()}ing {len(services)} service(s) from {search_in}:\n{services_str}",
                fg="cyan",
            )
        )
        for srv in services:
            getattr(srv, command)()
        systemd_manager().Reload()
    else:
        click.echo(
            click.style(
                f"Found {len(services)} service(s) from {search_in}:\n{services_str}",
                fg="cyan",
            )
        )
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def start(service: str):
    """Start service(s).

    Args:
        service (str): Name or name pattern of service(s) to start.
    """
    start_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def stop(service: str):
    """Stop running service(s).

    Args:
        service (str): Name or name pattern of service(s) to stop.
    """
    stop_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def restart(service: str):
    """Restart running service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    restart_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def enable(service: str):
    """Enable currently disabled service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    enable_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def disable(service: str):
    """Disable service(s).

    Args:
        service (str): Name or name pattern of service(s) to disable.
    """
    disable_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command()
@click.argument("service")
def remove(service: str):
    """Remove service(s).

    Args:
        service (str): Name or name pattern of service(s) to remove.
    """
    remove_service(service)
    click.echo(click.style("Done!", fg="green"))


@cli.command
@click.argument("service", required=False)
def show(service: str):
    """Show services file contents."""
    files = defaultdict(list)
    for f in systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}*.service"):
        files[f.stem].append(f)
    for f in systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}*.timer"):
        files[f.stem].append(f)
    files = {re.sub('^taskflow-','',k): v for k,v in files.items()}
    if service:
        files = {k: v for k, v in files.items() if fnmatchcase(service, k)}
    colors_gen = cycle(['white','cyan'])
    for i, srvs in enumerate(files.values()):
        if i > 0:
            click.echo("\n")
        click.echo(click.style("\n\n".join([s.read_text() for s in srvs]), fg=next(colors_gen)))


def table_column_colors():
    colors_gen = cycle(["orange3", "green", "cyan", "magenta", "dodger_blue1", "red"])

    @lru_cache
    def column_color(col_name: str) -> str:
        return next(colors_gen)

    return column_color


def _service_schedules_table(running_only: bool, match: str = None) -> Table:
    timer_files = get_timer_files(match)
    srv_schedules = {
        re.search(r"^taskflow_([\w-]+)", f.stem)
        .group(1): re.search(r"\[Timer\]((.|\n)+)\[", f.read_text(), re.MULTILINE)
        .group(1)
        .replace("Persistent=true", "")
        .strip()
        for f in timer_files
    }
    srv_runs = service_runs(match)
    if running_only:
        srv_runs = {
            srv_name: runs
            for srv_name, runs in srv_runs.items()
            if runs.get("Last Run", "").endswith("(running)")
        }
        srv_schedules = {
            srv_name: sched
            for srv_name, sched in srv_schedules.items()
            if srv_name in srv_runs
        }
    srv_schedules = {k: v for k, v in srv_schedules.items() if v}
    if not srv_schedules:
        return
    table = Table(box=box.SIMPLE)
    column_color = table_column_colors()
    for col in ("Service", "Schedule", "Next Run", "Last Run"):
        table.add_column(col, style=column_color(col), justify="center")
    for srv_name, sched in srv_schedules.items():
        runs = srv_runs.get(srv_name, {})
        table.add_row(
            srv_name, sched, runs.get("Next Run", ""), runs.get("Last Run", "")
        )
    return table
