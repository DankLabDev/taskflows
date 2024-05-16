import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from subprocess import run
from time import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from taskflows.utils import _SYSTEMD_FILE_PREFIX, logger

from .constraints import HardwareConstraint, SystemLoadConstraint
from .schedule import Schedule


def systemd_manager():
    import dbus

    bus = dbus.SessionBus()
    systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
    return dbus.Interface(systemd, "org.freedesktop.systemd1.Manager")


systemd_dir = Path.home().joinpath(".config", "systemd", "user")
# systemd_dir = Path("/etc/systemd/system")

ServiceNames = Optional[Union[str, Sequence[str]]]


@dataclass
class Service:
    """A service to run a command on a specified schedule."""

    name: str
    command: str
    description: Optional[str] = None
    schedule: Optional[Union[Schedule, Sequence[Schedule]]] = None
    restart_policy: Optional[
        Literal[
            "always",
            "on-success",
            "on-failure",
            "on-abnormal",
            "on-abort",
            "on-watchdog",
        ]
    ] = None
    hardware_constraints: Optional[
        Union[HardwareConstraint, Sequence[HardwareConstraint]]
    ] = None
    system_load_constraints: Optional[
        Union[SystemLoadConstraint, Sequence[SystemLoadConstraint]]
    ] = None
    # make sure this service is fully started before begining startup of these services.
    start_before: Optional[ServiceNames] = None
    # make sure these services are fully started before begining startup of this service.
    start_after: Optional[ServiceNames] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the listed units fail to start, this unit will still be started anyway. Multiple units may be specified.
    wants: Optional[ServiceNames] = None
    # Configures dependencies similar to `Wants`, but as long as this unit is up,
    # all units listed in `Upholds` are started whenever found to be inactive or failed, and no job is queued for them.
    # While a Wants= dependency on another unit has a one-time effect when this units started,
    # a `Upholds` dependency on it has a continuous effect, constantly restarting the unit if necessary.
    # This is an alternative to the Restart= setting of service units, to ensure they are kept running whatever happens.
    upholds: Optional[ServiceNames] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If one of the other units fails to activate, and an ordering dependency `After` on the failing unit is set, this unit will not be started.
    # This unit will be stopped (or restarted) if one of the other units is explicitly stopped (or restarted) via systemctl command (not just normal exit on process finished).
    requires: Optional[ServiceNames] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the units listed here are not started already, they will not be started and the starting of this unit will fail immediately.
    # Note: this setting should usually be combined with `After`, to ensure this unit is not started before the other unit.
    requisite: Optional[ServiceNames] = None
    # Same as `Requires`, but in order for this unit will be stopped (or restarted), if a listed unit is stopped (or restarted), explicitly or not.
    binds_to: Optional[ServiceNames] = None
    # one or more units that are activated when this unit enters the "failed" state.
    # A service unit using Restart= enters the failed state only after the start limits are reached.
    on_failure: Optional[ServiceNames] = None
    # one or more units that are activated when this unit enters the "inactive" state.
    on_success: Optional[ServiceNames] = None
    # When systemd stops or restarts the units listed here, the action is propagated to this unit.
    # Note that this is a one-way dependency — changes to this unit do not affect the listed units.
    part_of: Optional[ServiceNames] = None
    # A space-separated list of one or more units to which stop requests from this unit shall be propagated to,
    # or units from which stop requests shall be propagated to this unit, respectively.
    # Issuing a stop request on a unit will automatically also enqueue stop requests on all units that are linked to it using these two settings.
    propagate_stop_to: Optional[ServiceNames] = None
    propagate_stop_from: Optional[ServiceNames] = None
    # other units where starting the former will stop the latter and vice versa.
    conflicts: Optional[ServiceNames] = None
    # Specifies a timeout (in seconds) that starts running when the queued job is actually started.
    # If limit is reached, the job will be cancelled, the unit however will not change state or even enter the "failed" mode.
    timeout: Optional[int] = None
    env_file: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[Union[str, Path]] = None

    def create(self):
        logger.info("Creating service %s", self.name)
        self._write_timer_unit()
        self._write_service_unit()
        self.enable()

    def enable(self):
        enable_service(self.name)

    def run(self):
        start_service(self.name)

    def stop(self):
        stop_service(self.name)

    def restart(self):
        restart_service(self.name)

    def disable(self):
        disable_service(self.name)

    def remove(self):
        remove_service(self.name)

    def _join_values(self, values: Any):
        if isinstance(values, str):
            return values
        elif isinstance(values, (list, tuple)):
            return " ".join(values)
        raise ValueError(f"Unexpected type for values: {type(values)}")

    def _write_timer_unit(self):
        if not self.schedule:
            return
        timer = {"Persistent=true"}
        if isinstance(self.schedule, (list, tuple)):
            for sched in self.schedule:
                timer.update(sched.unit_entries())
        else:
            timer.update(self.schedule.unit_entries())
        content = [
            "[Unit]",
            f"Description=Timer for {self.name}",
            "[Timer]",
            *timer,
            "[Install]",
            "WantedBy=timers.target",
        ]
        self._write_systemd_file("timer", "\n".join(content))

    def _write_service_unit(self):
        # TODO systemd-escape command
        unit, service = set(), set()
        if self.working_directory:
            service.add(f"WorkingDirectory={self.working_directory}")
        if self.restart_policy:
            service.add(f"Restart={self.restart_policy}")
        if self.description:
            unit.add(f"Description={self.description}")
        if self.start_after:
            # TODO add "After=network.target"
            unit.add(f"After={self._join_values(self.start_after)}")
        if self.start_before:
            unit.add(f"Before={self._join_values(self.start_before)}")
        if self.conflicts:
            unit.add(f"Conflicts={self._join_values(self.conflicts)}")
        if self.on_success:
            unit.add(f"OnSuccess={self._join_values(self.on_success)}")
        if self.on_failure:
            unit.add(f"OnFailure={self._join_values(self.on_failure)}")
        if self.part_of:
            unit.add(f"PartOf={self._join_values(self.part_of)}")
        if self.wants:
            unit.add(f"Wants={self._join_values(self.wants)}")
        if self.upholds:
            unit.add(f"Upholds={self._join_values(self.upholds)}")
        if self.requires:
            unit.add(f"Requires={self._join_values(self.requires)}")
        if self.requisite:
            unit.add(f"Requisite={self._join_values(self.requisite)}")
        if self.conflicts:
            unit.add(f"Conflicts={self._join_values(self.conflicts)}")
        if self.binds_to:
            unit.add(f"BindsTo={self._join_values(self.binds_to)}")
        if self.propagate_stop_to:
            unit.add(f"PropagatesStopTo={self._join_values(self.propagate_stop_to)}")
        if self.propagate_stop_from:
            unit.add(
                f"StopPropagatedFrom={self._join_values(self.propagate_stop_from)}"
            )
        if self.timeout:
            service.add(f"RuntimeMaxSec={self.timeout}")
        if self.env_file:
            service.add(f"EnvironmentFile={self.env_file}")
        if self.env:
            # TODO is this correct syntax?
            env = ",".join([f"{k}={v}" for k, v in self.env.items()])
            service.add(f"Environment={env}")
        if self.hardware_constraints:
            if isinstance(self.hardware_constraints, (list, tuple)):
                for hc in self.hardware_constraints:
                    unit.update(hc.unit_entries())
            else:
                unit.update(self.hardware_constraints.unit_entries())
        if self.system_load_constraints:
            if isinstance(self.system_load_constraints, (list, tuple)):
                for slc in self.system_load_constraints:
                    unit.update(slc.unit_entries())
            else:
                unit.update(self.system_load_constraints.unit_entries())
        content = [
            "[Service]",
            "Type=simple",
            f"ExecStart={self.command}",
            *service,
            "[Unit]",
            *unit,
            "[Install]",
            "WantedBy=default.target",
        ]
        self._write_systemd_file("service", "\n".join(content))

    def _write_systemd_file(self, unit_type: Literal["timer", "service"], content: str):
        systemd_dir.mkdir(parents=True, exist_ok=True)
        file = (
            systemd_dir
            / f"{_SYSTEMD_FILE_PREFIX}{self.name.replace(' ', '_')}.{unit_type}"
        )
        if file.exists():
            logger.warning("Replacing existing unit: %s", file)
        else:
            logger.info("Creating new unit: %s", file)
        file.write_text(content)

    def __repr__(self):
        return str(self)

    def __str__(self):
        meta = {
            "name": self.name,
            "command": self.command,
        }
        if self.description:
            meta["description"] = self.description
        if self.schedule:
            meta["schedule"] = self.schedule
        meta = ", ".join(f"{k}={v}" for k, v in meta.items())
        return f"{self.__class__.__name__}({meta})"


def enable_service(service: str):
    """Enable currently disabled service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    for sf in get_service_files(service):
        logger.info("Enabling service: %s", sf)
        systemd_manager().EnableUnitFiles([str(sf)], True, True)
        # user_systemctl("enable", "--now", f"{_SYSTEMD_FILE_PREFIX}{sf}.timer")


def is_service_enabled(service):
    """
    is_service_enabled method will check if service is already enabled that is passed in this method.
    It raise exception if there is error.
    Return value, True if service is already enabled otherwise False.

    :param str service: name of the service
    """
    try:
        return systemd_manager().GetUnitFileState(service) == "enabled"
    except:
        return False


def start_service(service: str):
    """
    start method will start service that is passed in this method.
    If service is already started then it will ignore it.
    It raise exception if there is error

    :param str service: name of the service
    """
    for sf in get_service_files(service):
        logger.info("Running service: %s", sf.name)
        # service_cmd(sf, "start")
        systemd_manager().StartUnit(sf.name, "replace")


def restart_service(service: str):
    """Restart running service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    for sf in get_service_files(service):
        logger.info("Restarting service: %s", sf)
        # service_cmd(sf, "restart")
        systemd_manager().RestartUnit(sf.name, "replace")


def stop_service(service: str):
    """Stop running service(s).

    Args:
        service (str): Name or name pattern of service(s) to stop.
    """
    for sf in get_service_files(service):
        logger.info("Stopping service: %s", sf)
        # service_cmd(sf, "stop")
        # TODO a way to not use sigkill?
        systemd_manager().StopUnit(sf.name, "replace")


def disable_service(service: str):
    """Disable service(s).

    Args:
        service (str): Name or name pattern of service(s) to disable.
    """
    for sf in get_service_files(service):
        # user_systemctl(
        #    "disable", "--now", f"{_SYSTEMD_FILE_PREFIX}{sf}.timer"
        # )
        logger.info("Stopped and disabled service: %s", sf)
        # file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{sf}.timer"
        systemd_manager().DisableUnitFiles([sf.name], False)
    # remove any failed status caused by stopping service.
    # user_systemctl("reset-failed")
    systemd_manager().Reload()


def remove_service(service: str):
    """Remove service(s).

    Args:
        service (str): Name or name pattern of service(s) to remove.
    """
    disable_service(service)
    for srv_file in get_service_files(service):
        logger.info("Cleaning cache and runtime directories: %s.", srv_file)
        # TODO python-dbus
        user_systemctl("clean", srv_file.stem)
        # remove files.
        logger.info("Deleting %s", srv_file)
        srv_file.unlink()
    for timer_file in get_timer_files(service):
        logger.info("Deleting %s", timer_file)
        timer_file.unlink()


def service_runs(match: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Map service name to current schedule status."""
    srv_runs = defaultdict(dict)
    # get task status.
    for info in parse_systemctl_tables(["systemctl", "--user", "list-timers"]):
        if task_name := re.search(r"^taskflow_([\w-]+)\.timer", info["UNIT"]):
            srv_runs[task_name.group(1)].update(
                {
                    "Next Run": f"{info['NEXT']} ({info['LEFT']})",
                    "Last Run": f"{info['LAST']} ({info['PASSED']})",
                }
            )
    for info in parse_systemctl_tables(
        "systemctl --user list-units --type=service".split()
    ):
        task_name = re.search(r"^taskflow_([\w-]+)\.service", info["UNIT"])
        if task_name and info["ACTIVE"] == "active":
            if "Last Run" in (d := srv_runs[task_name.group(1)]):
                d["Last Run"] += " (running)"
    if match:
        srv_runs = {k: v for k, v in srv_runs.items() if fnmatch(k, match)}

    def sort_key(row):
        data = row[1]
        if not (last_run := data.get("Last Run")) or "(running)" in last_run:
            return time()
        dt = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", last_run)
        return datetime.fromisoformat(dt.group(0)).timestamp()

    return dict(sorted(srv_runs.items(), key=sort_key))


def get_service_files(match: Optional[str] = None) -> List[Path]:
    """Get names of all services."""
    return get_systemd_files("service", match)


def get_timer_files(match: Optional[str] = None) -> List[Path]:
    """Get names of all services."""
    return get_systemd_files("timer", match)


def get_systemd_files(
    file_type: Literal["timer", "service"], match: Optional[str] = None
) -> List[Path]:
    if match is not None:
        if not match.startswith(_SYSTEMD_FILE_PREFIX):
            match = f"{_SYSTEMD_FILE_PREFIX}{match}"
        if not match.endswith(file_type):
            match = f"{match}*.{file_type}"
        files = list(systemd_dir.glob(match))
    else:
        files = list(systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}*.{file_type}"))
    if not files:
        if match:
            logger.error("No %s found matching: %s", file_type, match)
        else:
            logger.error("No %s found", file_type)
    return files


def parse_systemctl_tables(command: List[str]) -> List[Dict[str, str]]:
    res = run(command, capture_output=True)
    lines = res.stdout.decode().split("\n\n")[0].splitlines()
    fields = list(re.finditer(r"[A-Z]+", lines.pop(0)))
    lines_data = []
    for line in lines:
        line_data = {}
        for next_idx, match in enumerate(fields, start=1):
            char_start_idx = match.start()
            if next_idx == len(fields):
                field_text = line[char_start_idx:]
            else:
                field_text = line[char_start_idx : fields[next_idx].start()]
            line_data[match.group()] = field_text.strip()
        lines_data.append(line_data)
    return lines_data


def is_service_active(service):
    """
    is_service_active method will check if service is running or not.
    It raise exception if there is service is not loaded
    Return value, True if service is running otherwise False.
    :param str service: name of the service
    """
    try:
        systemd_manager().GetUnit(service)
        return True
    except:
        return False


def user_systemctl(*args):
    """Run a systemd command as current user."""
    return run(["systemctl", "--user", *args], capture_output=True)
    # return run(["systemctl", *args], capture_output=True)


def service_cmd(service_name: str, command: str):
    if not service_name.startswith(_SYSTEMD_FILE_PREFIX):
        service_name = f"{_SYSTEMD_FILE_PREFIX}{service_name}"
    return user_systemctl(command, service_name)
