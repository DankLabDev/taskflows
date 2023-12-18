"""Systemd units. 
https://manpages.debian.org/testing/systemd/systemd.unit.5.en.html
https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
Systemd conditions. https://manpages.debian.org/testing/systemd/systemd.unit.5.en.html
Systemd timers. Reference:
https://www.freedesktop.org/software/systemd/man/systemd.timer.html#Options.
https://documentation.suse.com/smart/systems-management/html/systemd-working-with-timers/index.html
"""

from pathlib import Path
from subprocess import run
from typing import Any, Dict, Literal, Optional, Sequence, Union

from pydantic import BaseModel

from taskflows.utils import _FILE_PREFIX, logger

from .constraints import HardwareConstraint, SystemLoadConstraint
from .schedule import Schedule

systemd_dir = Path.home().joinpath(".config", "systemd", "user")

ServiceNames = Optional[Union[str, Sequence[str]]]


# TODO db log service on_success on_failure


class Service(BaseModel):
    name: str
    command: str
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

    def create(self):
        logger.info("Creating service %s", self.name)
        # create_missing_tables()
        self._write_timer_unit()
        self._write_service_unit()
        self.enable()

    def enable(self):
        enable_service(self.name)

    def run(self):
        run_service(service_name=self.name)

    def stop(self):
        stop_service(service_name=self.name)

    def restart(self):
        restart_service(service_name=self.name)

    def disable(self):
        disable_service(service_name=self.name)

    def remove(self):
        remove_service(service_name=self.name)

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
        unit = set()
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
            "[Unit]",
            f"Description={self.name}",
            *unit,
            "[Install]",
            "WantedBy=multi-user.target",
        ]
        self._write_systemd_file("service", "\n".join(content))

    def _write_systemd_file(self, unit_type: Literal["timer", "service"], content: str):
        systemd_dir.mkdir(parents=True, exist_ok=True)
        file = systemd_dir / f"{_FILE_PREFIX}{self.name.replace(' ', '_')}.{unit_type}"
        if file.exists():
            logger.warning("Replacing existing unit: %s", file)
        else:
            logger.info("Creating new unit: %s", file)
        file.write_text(content)


def enable_service(service_name: str):
    """Enable a service."""
    logger.info("Enabling scheduled service %s", service_name)
    user_systemctl("enable", "--now", f"{_FILE_PREFIX}{service_name}.timer")


def run_service(service_name: str):
    """Run a service.

    Args:
        service_name (str): Name of service to run.
    """
    logger.info("Running service %s", service_name)
    service_cmd(service_name, "start")


def restart_service(service_name: str):
    """Restart a running service.

    Args:
        service_name (str): Name of service to restart.
    """
    logger.info("Restarting service %s", service_name)
    service_cmd(service_name, "restart")


def stop_service(service_name: str):
    """Stop a running service.

    Args:
        service_name (str): Name of service to stop.
    """
    logger.info("Stopping service %s", service_name)
    service_cmd(service_name, "stop")


def disable_service(service_name: Path):
    """Disable a service."""
    srvs = {f.stem for f in systemd_dir.glob(f"{_FILE_PREFIX}{service_name}*")}
    for srv in srvs:
        user_systemctl("disable", "--now", srv)
        logger.info("Stopped and disabled unit: %s", srv)
    # remove any failed status caused by stopping service.
    user_systemctl("reset-failed")


def remove_service(service_name: Path):
    """Completely remove a service's services and timers."""
    logger.info("Removing scheduled service %s", service_name)
    disable_service(service_name)
    files = list(systemd_dir.glob(f"{_FILE_PREFIX}{service_name}.*"))
    srvs = {f.stem for f in files}
    for srv in srvs:
        logger.info("Cleaning cache and runtime directories: %s.", srv)
        user_systemctl("clean", srv)
    for file in files:
        logger.info("Deleting %s", file)
        file.unlink()


def user_systemctl(*args):
    """Run a systemd command as current user."""
    return run(["systemctl", "--user", *args], capture_output=True)


def service_cmd(service_name: str, command: str):
    if not service_name.startswith(_FILE_PREFIX):
        service_name = f"{_FILE_PREFIX}{service_name}"
    user_systemctl(command, service_name)
