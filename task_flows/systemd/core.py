import os
import re
from pathlib import Path
from subprocess import run
from typing import Literal, Sequence, Set, Union

from task_flows.utils import _FILE_PREFIX, logger

from .models import Timer
from .templates import load_template

systemd_dir = Path.home().joinpath(".config", "systemd", "user")


def run_task(task_name: str):
    """Run a task.

    Args:
        task_name (str): Name of task to run.
    """
    logger.info("Running task %s", task_name)
    _task_cmd(task_name, "start")


def stop_task(task_name: str):
    """Stop a running task.

    Args:
        task_name (str): Name of task to stop.
    """
    logger.info("Stopping task %s", task_name)
    _task_cmd(task_name, "stop")


def restart_task(task_name: str):
    """Restart a running task.

    Args:
        task_name (str): Name of task to restart.
    """
    logger.info("Restarting task %s", task_name)
    _task_cmd(task_name, "restart")


def create_scheduled_task(
    task_name: str, timers: Union[Timer, Sequence[Timer]], command: str
):
    """Install and enable a systemd service and timer.

    Args:
        task_name (str): Name of task service should be created for.
    """
    logger.info("Creating scheduled task %s (%s)", task_name, timers)

    if isinstance(timers, Timer):
        timers = [timers]
    systemd_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_FILE_PREFIX}{task_name}"

    systemd_dir.joinpath(f"{stem}.timer").write_text(
        load_template("timer").render(
            task_name=task_name,
            timers=[(t.__class__.__name__, t.value) for t in timers],
        )
    )
    # TODO systemd-escape command
    # TODO arg for systemd After=
    systemd_dir.joinpath(f"{stem}.service").write_text(
        load_template("service").render(
            task_name=task_name, path=os.environ["PATH"], command=command
        )
    )
    enable_scheduled_task(task_name)


def disable_scheduled_task(task_name: Path):
    """Disable a task's services and timers."""
    srvs = {f.stem for f in systemd_dir.glob(f"{_FILE_PREFIX}{task_name}*")}
    for srv in srvs:
        _user_systemctl("disable", "--now", srv)
        logger.info("Stopped and disabled unit: %s", srv)
    # remove any failed status caused by stopping service.
    _user_systemctl("reset-failed")


def enable_scheduled_task(task_name: str):
    """Enable a task's services and timers."""
    logger.info("Enabling scheduled task %s", task_name)
    _user_systemctl("enable", "--now", f"{_FILE_PREFIX}{task_name}.timer")


def remove_scheduled_task(task_name: Path):
    """Completely remove a task's services and timers."""
    logger.info("Removing scheduled task %s", task_name)
    disable_scheduled_task(task_name)
    files = list(systemd_dir.glob(f"{_FILE_PREFIX}{task_name}*"))
    srvs = {f.stem for f in files}
    for srv in srvs:
        logger.info("Cleaning cache and runtime directories: %s.", srv)
        _user_systemctl("clean", srv)
    for file in files:
        logger.info("Deleting %s", file)
        file.unlink()


def _user_systemctl(*args):
    """Run a systemd command as current user."""
    return run(["systemctl", "--user", *args], capture_output=True)


def _names_from_files(
    name_type: Literal["task", "unit"], include_stop_tasks: bool = True
) -> Set[str]:
    """Parse task systemd file stems."""
    names = [
        m
        for f in systemd_dir.glob(f"{_FILE_PREFIX}*")
        if (m := re.match(_FILE_PREFIX + r"([\w-]+$)", f.stem))
    ]
    if name_type == "task":
        names = {m.group(1) for m in names}
    elif name_type == "unit":
        names = {m.group() for m in names}
    if not include_stop_tasks:
        names = {n for n in names if not n.endswith("_stop")}
    return names


def _task_cmd(task_name: str, command: str):
    if not task_name.startswith(_FILE_PREFIX):
        task_name = f"{_FILE_PREFIX}{task_name}"
    _user_systemctl(command, task_name)
