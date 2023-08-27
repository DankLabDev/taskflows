import os
import re
from pathlib import Path
from subprocess import run
from typing import Literal, Sequence, Set, Union

from jinja2 import Environment, FileSystemLoader

from task_flows.utils import _FILE_PREFIX, logger

from .models import Timer

systemd_dir = Path.home().joinpath(".config", "systemd", "user")


def run_task(name: str):
    """Run a task.

    Args:
        name (str): Name of task to run.
    """
    _task_cmd(name, "start")


def stop_task(name: str):
    """Stop a running task.

    Args:
        name (str): Name of task to stop.
    """
    _task_cmd(name, "stop")


def restart_task(name: str):
    """Restart a running task.

    Args:
        name (str): Name of task to restart.
    """
    _task_cmd(name, "restart")


def create_scheduled_task(
    task_name: str, timers: Union[Timer, Sequence[Timer]], command: str
):
    """Install and enable a systemd service and timer.

    Args:
        task_name (str): Name of task service should be created for.
    """
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates")
    )

    if isinstance(timers, Timer):
        timers = [timers]
    systemd_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_FILE_PREFIX}{task_name}"

    systemd_dir.joinpath(f"{stem}.timer").write_text(
        environment.get_template("timer.jinja2").render(
            task_name=task_name,
            timers=[(t.__class__.__name__, t.value) for t in timers],
        )
    )
    logger.info("Installed Systemd timer for %s.", task_name)

    # TODO systemd-escape command
    # TODO arg for systemd After=
    systemd_dir.joinpath(f"{stem}.service").write_text(
        environment.get_template("service.jinja2").render(
            task_name=task_name, path=os.environ["PATH"], command=command
        )
    )
    logger.info("Installed Systemd service for %s.", task_name)
    user_systemctl("enable", "--now", f"{stem}.timer")


def disable_scheduled_task(task_name: Path):
    """Disable a task's services and timers."""
    srvs = {f.stem for f in systemd_dir.glob(f"{_FILE_PREFIX}{task_name}*")}
    for srv in srvs:
        user_systemctl("disable", "--now", srv)
        logger.debug("Disabled unit: %s", srv)
    # remove any failed status caused by stopping service.
    user_systemctl("reset-failed")


def enable_scheduled_task(task_name: str):
    """Enable a task's services and timers."""
    user_systemctl("enable", "--now", f"{_FILE_PREFIX}{task_name}.timer")


def remove_scheduled_task(task_name: Path):
    """Complete remove a task's services and timers."""
    disable_scheduled_task(task_name)
    files = list(systemd_dir.glob(f"{_FILE_PREFIX}{task_name}*"))
    srvs = {f.stem for f in files}
    for srv in srvs:
        user_systemctl("clean", srv)
    for file in files:
        logger.debug("Removing %s", file)
        file.unlink()


def user_systemctl(*args):
    """Run a systemd command as current user."""
    run(["systemctl", "--user", *args])


def names_from_files(
    name_type: Literal["task", "unit"], include_stop_tasks: bool = True
) -> Set[str]:
    """Parse task systemd file stems."""
    names = [
        m
        for f in systemd_dir.glob("{_FILE_PREFIX}*")
        if (m := re.match(_FILE_PREFIX + r"([\w-]+$)", f.stem))
    ]
    if name_type == "task":
        names = {m.group(1) for m in names}
    elif name_type == "unit":
        names = {m.group() for m in names}
    if not include_stop_tasks:
        names = {n for n in names if not n.endswith("_stop")}
    return names


def _task_cmd(name: str, command: str):
    if not name.startswith(_FILE_PREFIX):
        name = f"{_FILE_PREFIX}{name}"
    user_systemctl(command, name)
