import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from subprocess import run
from time import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

import sqlalchemy as sa
from pydantic import BaseModel

from taskflows.db import task_flows_db
from taskflows.utils import _SYSTEMD_FILE_PREFIX, logger

from .constraints import HardwareConstraint, SystemLoadConstraint
from .schedule import Schedule

systemd_dir = Path.home().joinpath(".config", "systemd", "user")

ServiceNames = Optional[Union[str, Sequence[str]]]


class Service(BaseModel):
    name: str
    command: str
    description: Optional[str] = None
    schedule: Optional[Union[Schedule, Sequence[Schedule]]] = None
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
    # all units listed in `Upholds` are started whenever found to be inactive or failed,
    # and no job is queued for them. While a Wants= dependency on another unit has a one-time effect when this units started,
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
        self._db = task_flows_db()
        self._write_timer_unit()
        self._write_service_unit()
        self._save_db_metadata()
        self.enable()

    def enable(self):
        enable_service(self.name)

    def run(self):
        run_service(self.name)

    def stop(self):
        stop_service(self.name)

    def restart(self):
        restart_service(self.name)

    def disable(self):
        disable_service(self.name)

    def remove(self):
        remove_service(self.name)

    def as_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if self.schedule:
            data["schedule"] = asdict(self.schedule)
        data = {k: v for k, v in data.items() if v is not None}
        if "working_directory" in data:
            data["working_directory"] = str(data["working_directory"])
        return data

    def _join_values(self, values: Any):
        if isinstance(values, str):
            return values
        elif isinstance(values, (list, tuple)):
            return " ".join(values)
        raise ValueError(f"Unexpected type for values: {type(values)}")

    def _save_db_metadata(self):
        data = self.as_dict()
        name = data.pop("name")
        command = data.pop("command")
        schedule = data.pop("schedule", None)
        self._db.upsert(
            self._db.services_table,
            name=name,
            command=command,
            schedule=schedule,
            config=data,
        )

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
            unit.add(f"RuntimeMaxSec={self.timeout}")
        if self.env_file:
            unit.add(f"EnvironmentFile={self.env_file}")
        if self.env:
            # TODO is this correct syntax?
            env = ",".join([f"{k}={v}" for k, v in self.env.items()])
            unit.add(f"Environment={env}")
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
            "WantedBy=multi-user.target",
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


def enable_service(service: str):
    """Enable currently disabled service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    for service_name in get_service_names(service):
        logger.info("Enabling service: %s", service_name)
        user_systemctl("enable", "--now", f"{_SYSTEMD_FILE_PREFIX}{service_name}.timer")


def run_service(service: str):
    """Run service(s).

    Args:
        service_name (str): Name or name pattern of service(s) to run.
    """
    for service_name in get_service_names(service):
        logger.info("Running service: %s", service_name)
        service_cmd(service_name, "start")


def restart_service(service: str):
    """Restart running service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    for service_name in get_service_names(service):
        logger.info("Restarting service: %s", service_name)
        service_cmd(service_name, "restart")


def stop_service(service: str):
    """Stop running service(s).

    Args:
        service (str): Name or name pattern of service(s) to stop.
    """
    for service_name in get_service_names(service):
        logger.info("Stopping service: %s", service_name)
        service_cmd(service_name, "stop")


def disable_service(service: str):
    """Disable service(s).

    Args:
        service (str): Name or name pattern of service(s) to disable.
    """
    for service_name in get_service_names(service):
        user_systemctl(
            "disable", "--now", f"{_SYSTEMD_FILE_PREFIX}{service_name}.timer"
        )
        logger.info("Stopped and disabled service: %s", service_name)
    # remove any failed status caused by stopping service.
    user_systemctl("reset-failed")


def remove_service(service: str):
    """Remove service(s).

    Args:
        service (str): Name or name pattern of service(s) to remove.
    """
    db = task_flows_db()
    for service_name in get_service_names(service):
        logger.info("Removing service %s", service_name)
        disable_service(service_name)
        files = list(systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}{service_name}.*"))
        srvs = {f.stem for f in files}
        for srv in srvs:
            logger.info("Cleaning cache and runtime directories: %s.", srv)
            user_systemctl("clean", srv)
        # remove files.
        for file in files:
            logger.info("Deleting %s", file)
            file.unlink()
        # remove from database.
        with db.engine.begin() as conn:
            conn.execute(
                sa.delete(db.services_table).where(
                    db.services_table.c.name == service_name
                )
            )


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
        if task_name := re.search(r"^taskflow_([\w-]+)\.service", info["UNIT"]):
            if info["ACTIVE"] == "active":
                srv_runs[task_name.group(1)]["Last Run"] += " (running)"
    if match:
        srv_runs = {k: v for k, v in srv_runs.items() if fnmatch(k, match)}
    srv_runs = dict(
        sorted(
            srv_runs.items(),
            key=lambda row: (
                time()
                if (
                    "(running)" in row[1]["Last Run"]
                    or not (
                        dt := re.search(
                            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", row[1]["Last Run"]
                        )
                    )
                )
                else datetime.fromisoformat(dt.group(0)).timestamp()
            ),
        )
    )
    return srv_runs


def get_service_names(match: Optional[str] = None) -> List[str]:
    """Get names of all services."""
    # TODO save in private sqlite db.
    srvs = {f.stem for f in systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}*")}
    names = [
        re.search(re.escape(_SYSTEMD_FILE_PREFIX) + r"(.*)$", s).group(1) for s in srvs
    ]
    if match:
        names = [n for n in names if fnmatch(n, match)]
    if not names:
        if match:
            logger.error("No service found matching: %s", match)
        else:
            logger.error("No service found")
    return names


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


def user_systemctl(*args):
    """Run a systemd command as current user."""
    return run(["systemctl", "--user", *args], capture_output=True)


def service_cmd(service_name: str, command: str):
    if not service_name.startswith(_SYSTEMD_FILE_PREFIX):
        service_name = f"{_SYSTEMD_FILE_PREFIX}{service_name}"
    user_systemctl(command, service_name)
