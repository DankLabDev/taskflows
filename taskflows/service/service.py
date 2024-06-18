"""
dbus docs:
https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
https://pkg.go.dev/github.com/coreos/go-systemd/dbus
"""

from dataclasses import dataclass

from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Union

from taskflows.utils import _SYSTEMD_FILE_PREFIX, logger, systemd_dir

from .constraints import HardwareConstraint, SystemLoadConstraint
from .docker import DockerContainer
from .schedule import Schedule
from .utils import (
    enable,
    start_service,
    stop_service,
    restart_service,
    disable,
    remove_service,
)


ServiceT = Union[str, "Service"]
ServicesT = Union[ServiceT, Sequence[ServiceT]]


@dataclass
class Service:
    """A service to run a command on a specified schedule."""

    name: str
    start_command: str
    start_command_blocking: bool = True
    stop_command: Optional[str] = None
    start_schedule: Optional[Union[Schedule, Sequence[Schedule]]] = None
    stop_schedule: Optional[Union[Schedule, Sequence[Schedule]]] = None
    kill_signal: str = "SIGTERM"
    description: Optional[str] = None
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
    start_before: Optional[ServicesT] = None
    # make sure these services are fully started before begining startup of this service.
    start_after: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the listed units fail to start, this unit will still be started anyway. Multiple units may be specified.
    wants: Optional[ServicesT] = None
    # Configures dependencies similar to `Wants`, but as long as this unit is up,
    # all units listed in `Upholds` are started whenever found to be inactive or failed, and no job is queued for them.
    # While a Wants= dependency on another unit has a one-time effect when this units started,
    # a `Upholds` dependency on it has a continuous effect, constantly restarting the unit if necessary.
    # This is an alternative to the Restart= setting of service units, to ensure they are kept running whatever happens.
    upholds: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If one of the other units fails to activate, and an ordering dependency `After` on the failing unit is set, this unit will not be started.
    # This unit will be stopped (or restarted) if one of the other units is explicitly stopped (or restarted) via systemctl command (not just normal exit on process finished).
    requires: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the units listed here are not started already, they will not be started and the starting of this unit will fail immediately.
    # Note: this setting should usually be combined with `After`, to ensure this unit is not started before the other unit.
    requisite: Optional[ServicesT] = None
    # Same as `Requires`, but in order for this unit will be stopped (or restarted), if a listed unit is stopped (or restarted), explicitly or not.
    binds_to: Optional[ServicesT] = None
    # one or more units that are activated when this unit enters the "failed" state.
    # A service unit using Restart= enters the failed state only after the start limits are reached.
    on_failure: Optional[ServicesT] = None
    # one or more units that are activated when this unit enters the "inactive" state.
    on_success: Optional[ServicesT] = None
    # When systemd stops or restarts the units listed here, the action is propagated to this unit.
    # Note that this is a one-way dependency — changes to this unit do not affect the listed units.
    part_of: Optional[ServicesT] = None
    # A space-separated list of one or more units to which stop requests from this unit shall be propagated to,
    # or units from which stop requests shall be propagated to this unit, respectively.
    # Issuing a stop request on a unit will automatically also enqueue stop requests on all units that are linked to it using these two settings.
    propagate_stop_to: Optional[ServicesT] = None
    propagate_stop_from: Optional[ServicesT] = None
    # other units where starting the former will stop the latter and vice versa.
    conflicts: Optional[ServicesT] = None
    # Specifies a timeout (in seconds) that starts running when the queued job is actually started.
    # If limit is reached, the job will be cancelled, the unit however will not change state or even enter the "failed" mode.
    timeout: Optional[int] = None
    env_file: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[Union[str, Path]] = None

    def create(self):
        logger.info("Creating service %s", self.name)
        self._write_timer_units()
        self._write_service_units()
        self.enable()

    def enable(self):
        enable(self.name)

    def start(self):
        start_service(self.name)

    def stop(self):
        stop_service(self.name)

    def restart(self):
        restart_service(self.name)

    def disable(self):
        disable(self.name)

    def remove(self):
        remove_service(self.name)

    def _write_timer_units(self):
        for is_stop_timer, schedule in (
            (False, self.start_schedule),
            (True, self.stop_schedule),
        ):
            if schedule is None:
                continue
            timer = set()
            if isinstance(schedule, (list, tuple)):
                for sched in schedule:
                    timer.update(sched.unit_entries)
            else:
                timer.update(schedule.unit_entries)
            content = [
                "[Unit]",
                f"Description={'stop' if is_stop_timer else ''}timer for {self.name}",
                "[Timer]",
                *timer,
                "[Install]",
                "WantedBy=timers.target",
            ]
            self._write_systemd_file("timer", "\n".join(content), is_stop_timer)

    def _write_service_units(self):
        def join(args):
            if not isinstance(args, (list, tuple)):
                args = [args]
            return " ".join(
                [
                    v if isinstance(v, str) else f"{v.base_file_stem}.service"
                    for v in args
                ]
            )

        unit = set()
        service = {
            f"ExecStart={self.start_command}",
            f"KillSignal={self.kill_signal}",
        }
        if not self.start_command_blocking:
            # service.add("Type=simple")
            service.add("RemainAfterExit=yes")
        ##else:
        # service.add("Type=simple")
        if self.stop_command:
            service.add(f"ExecStop={self.stop_command}")
        if self.working_directory:
            service.add(f"WorkingDirectory={self.working_directory}")
        if self.restart_policy:
            service.add(f"Restart={self.restart_policy}")
        if self.timeout:
            service.add(f"RuntimeMaxSec={self.timeout}")
        if self.env_file:
            service.add(f"EnvironmentFile={self.env_file}")
        if self.env:
            # TODO is this correct syntax?
            env = ",".join([f"{k}={v}" for k, v in self.env.items()])
            service.add(f"Environment={env}")
        if self.description:
            unit.add(f"Description={self.description}")
        if self.start_after:
            unit.add(f"After={join(self.start_after)}")
        if self.start_before:
            unit.add(f"Before={join(self.start_before)}")
        if self.conflicts:
            unit.add(f"Conflicts={join(self.conflicts)}")
        if self.on_success:
            unit.add(f"OnSuccess={join(self.on_success)}")
        if self.on_failure:
            unit.add(f"OnFailure={join(self.on_failure)}")
        if self.part_of:
            unit.add(f"PartOf={join(self.part_of)}")
        if self.wants:
            unit.add(f"Wants={join(self.wants)}")
        if self.upholds:
            unit.add(f"Upholds={join(self.upholds)}")
        if self.requires:
            unit.add(f"Requires={join(self.requires)}")
        if self.requisite:
            unit.add(f"Requisite={join(self.requisite)}")
        if self.conflicts:
            unit.add(f"Conflicts={join(self.conflicts)}")
        if self.binds_to:
            unit.add(f"BindsTo={join(self.binds_to)}")
        if self.propagate_stop_to:
            unit.add(f"PropagatesStopTo={join(self.propagate_stop_to)}")
        if self.propagate_stop_from:
            unit.add(f"StopPropagatedFrom={join(self.propagate_stop_from)}")
        if self.hardware_constraints:
            if isinstance(self.hardware_constraints, (list, tuple)):
                for hc in self.hardware_constraints:
                    unit.update(hc.unit_entries)
            else:
                unit.update(self.hardware_constraints.unit_entries)
        if self.system_load_constraints:
            if isinstance(self.system_load_constraints, (list, tuple)):
                for slc in self.system_load_constraints:
                    unit.update(slc.unit_entries)
            else:
                unit.update(self.system_load_constraints.unit_entries)
        service_file = self._write_service_file(unit=unit, service=service)
        # TODO ExecCondition, ExecStartPre, ExecStartPost?
        if self.stop_schedule:
            service = [f"ExecStart=systemctl --user stop {service_file.name}"]
            self._write_service_file(service=service, is_stop_unit=True)

    @property
    def base_file_stem(self) -> str:
        return f"{_SYSTEMD_FILE_PREFIX}{self.name.replace(' ', '_')}"

    def _write_service_file(
        self,
        unit: Optional[List[str]] = None,
        service: Optional[List[str]] = None,
        is_stop_unit: bool = False,
    ):
        content = []
        if unit:
            content += ["[Unit]", *unit]
        content += [
            "[Service]",
            *service,
            "[Install]",
            "WantedBy=default.target",
        ]
        return self._write_systemd_file(
            "service", "\n".join(content), is_stop_unit=is_stop_unit
        )

    def _write_systemd_file(
        self,
        unit_type: Literal["timer", "service"],
        content: str,
        is_stop_unit: bool = False,
    ) -> Path:
        systemd_dir.mkdir(parents=True, exist_ok=True)
        file_stem = f"{_SYSTEMD_FILE_PREFIX}{self.name.replace(' ', '_')}"
        if is_stop_unit:
            file_stem = f"stop-{file_stem}"
        file = systemd_dir / f"{file_stem}.{unit_type}"
        if file.exists():
            logger.warning("Replacing existing unit: %s", file)
        else:
            logger.info("Creating new unit: %s", file)
        file.write_text(content)
        return file

    def __repr__(self):
        return str(self)

    def __str__(self):
        meta = {
            "name": self.name,
            "command": self.start_command,
        }
        if self.description:
            meta["description"] = self.description
        if self.start_schedule:
            meta["schedule"] = self.start_schedule
        meta = ", ".join(f"{k}={v}" for k, v in meta.items())
        return f"{self.__class__.__name__}({meta})"


class DockerService(Service):
    """A service to start and stop a Docker container."""

    def __init__(self, container: DockerContainer | str, **kwargs):
        cname = container if isinstance(container, str) else container.name
        self.container = container
        # for key in ("requires", "start_after"):
        #    kwargs[key] = []
        # kwargs["requires"].append("docker.service")
        # kwargs["start_after"].append("docker.service")
        super().__init__(
            name=kwargs.get("name", cname),
            start_command=f"docker start {cname}",
            stop_command=f"docker stop {cname}",
            start_command_blocking=False,
            **kwargs,
        )

    def create(self):
        if isinstance(self.container, DockerContainer):
            if not self.container.name:
                logger.info("Setting container name to service name: %s", self.name)
                self.container.name = self.name
            self.container.create()
        super().create()
