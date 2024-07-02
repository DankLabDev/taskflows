"""
dbus docs:
https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
https://pkg.go.dev/github.com/coreos/go-systemd/dbus
"""

import os
import re
from datetime import datetime
from functools import cache
from pathlib import Path
from pprint import pformat
from typing import Dict, List, Literal, Optional, Sequence, Set, Union

from pydantic import PositiveInt
from pydantic.dataclasses import dataclass

from taskflows.utils import _SYSTEMD_FILE_PREFIX, logger, systemd_dir

from .constraints import HardwareConstraint, SystemLoadConstraint
from .docker import DockerContainer
from .schedule import Schedule

try:
    import dbus
except ImportError:
    logger.warning(
        "Could not import dbus. Service functionality will not be available."
    )


from .docker import delete_docker_container

ServiceT = Union[str, "Service"]
ServicesT = Union[ServiceT, Sequence[ServiceT]]


@dataclass
class RestartPolicy:
    """Service restart policy."""

    policy: Literal[
        "always",
        "on-success",
        "on-failure",
        "on-abnormal",
        "on-abort",
        "on-watchdog",
    ] = "always"
    restarts_per_period: PositiveInt = 100
    restart_period_sec: PositiveInt = 1

    def unit_entries(self) -> Set[str]:
        return {
            f"Restart={self.policy}",
            f"StartLimitIntervalSec={self.restart_period_sec}",
            f"StartLimitBurst={self.restarts_per_period}",
        }


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
    restart_policy: Optional[RestartPolicy] = None
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

    def __post_init__(self):
        self.service_files = []
        self.timer_files = []

    @property
    def unit_files(self) -> List[str]:
        """Get all service and timer files for this service."""
        return self.timer_files + self.service_files

    def create(self):
        """Create this service."""
        logger.info("Creating service %s", self.name)
        self._write_timer_units()
        self._write_service_units()
        mgr = systemd_manager()
        files = self.unit_files
        for file in files:
            file = os.path.basename(file)
            # ReloadOrTryRestartUnit attempts a reload if the unit supports it and use a "Try" flavored restart otherwise.
            logger.info("Reloading %s", file)
            mgr.ReloadOrTryRestartUnit(file, "replace")
        _enable_service(files)

    def start(self):
        """Start this service."""
        _start_service(self.unit_files)

    def stop(self):
        """Stop this service."""
        _stop_service(self.unit_files)

    def restart(self):
        """Restart this service."""
        _restart_service(self.service_files)

    def enable(self):
        """Enable this service."""
        _enable_service(self.unit_files)

    def disable(self):
        """Disable this service."""
        _disable_service(self.unit_files)

    def remove(self):
        """Remove this service."""
        _remove_service(service_files=self.service_files, timer_files=self.timer_files)

    def _write_timer_units(self):
        self.timer_files = []
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
            self.timer_files.append(
                self._write_systemd_file("timer", "\n".join(content), is_stop_timer)
            )

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
        if self.restart_policy:
            unit.update(self.restart_policy.unit_entries)
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
        srv_file = self._write_service_file(unit=unit, service=service)
        self.service_files = [srv_file]
        # TODO ExecCondition, ExecStartPre, ExecStartPost?
        if self.stop_schedule:
            service = [f"ExecStart=systemctl --user stop {os.path.basename(srv_file)}"]
            self.service_files.append(
                self._write_service_file(service=service, is_stop_unit=True)
            )

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
    ) -> str:
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
        return str(file)

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


@cache
def session_dbus():
    # SessionBus is for user session (like systemctl --user)
    return dbus.SessionBus()


@cache
def systemd_manager():
    bus = session_dbus()
    # Access the systemd D-Bus object
    systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
    return dbus.Interface(systemd, dbus_interface="org.freedesktop.systemd1.Manager")


def escape_path(path) -> str:
    """Escape a path so that it can be used in a systemd file."""
    return systemd_manager().EscapePath(path)


def _start_service(files: Sequence[str]):
    mgr = systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        logger.info("Running: %s", sf)
        mgr.StartUnit(sf, "replace")


def _stop_service(files: Sequence[str]):
    mgr = systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        logger.info("Stopping: %s", sf)
        mgr.StopUnit(sf, "replace")
        # remove any failed status caused by stopping service.
        # mgr.ResetFailedUnit(sf)


def _restart_service(files: Sequence[str]):
    mgr = systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        logger.info("Restarting: %s", sf)
        mgr.RestartUnit(sf, "replace")


def _enable_service(files: Sequence[str]):
    mgr = systemd_manager()
    logger.info("Enabling: %s", pformat(files))
    # the first bool controls whether the unit shall be enabled for runtime only (true, /run), or persistently (false, /etc).
    # The second one controls whether symlinks pointing to other units shall be replaced if necessary.
    mgr.EnableUnitFiles(files, False, True)


def _disable_service(files: Sequence[str]):
    mgr = systemd_manager()
    files = [os.path.basename(f) for f in files]
    logger.info("Disabling: %s", pformat(files))
    for meta in mgr.DisableUnitFiles(files, False):
        # meta has: the type of the change (one of symlink or unlink), the file name of the symlink and the destination of the symlink.
        logger.info("%s %s %s", *meta)


def _remove_service(service_files: Sequence[str], timer_files: Sequence[str]):
    service_files = [Path(f) for f in service_files]
    timer_files = [Path(f) for f in timer_files]
    files = service_files + timer_files
    _stop_service(files)
    _disable_service(files)
    container_names = set()
    mgr = systemd_manager()
    for srv_file in service_files:
        logger.info("Cleaning cache and runtime directories: %s.", srv_file)
        try:
            # the possible values are "configuration", "state", "logs", "cache", "runtime", "fdstore", and "all".
            mgr.CleanUnit(srv_file.name, ["all"])
        except dbus.exceptions.DBusException as err:
            logger.warning("Could not clean %s: (%s) %s", srv_file, type(err), err)
        container_name = re.search(
            r"docker (?:start|stop) ([\w-]+)", srv_file.read_text()
        )
        if container_name:
            container_names.add(container_name.group(1))
    for cname in container_names:
        delete_docker_container(cname)
    for file in files:
        logger.info("Deleting %s", file)
        file.unlink()


def get_schedule_info(timer: str):
    """Get the schedule information for a unit."""
    # make sure this is the timer unit.
    timer = timer.replace(".service", ".timer")
    if not timer.endswith(".timer"):
        timer = f"{timer}.timer"
    if not timer.startswith(_SYSTEMD_FILE_PREFIX):
        timer = f"{_SYSTEMD_FILE_PREFIX}{timer}"
    manager = systemd_manager()
    bus = session_dbus()
    # service_path = manager.GetUnit(timer)
    service_path = manager.LoadUnit(timer)
    service = bus.get_object("org.freedesktop.systemd1", service_path)
    properties = dbus.Interface(
        service, dbus_interface="org.freedesktop.DBus.Properties"
    )
    schedule = {
        # timestamp of the last time a unit entered the active state.
        "Last Start": properties.Get(
            "org.freedesktop.systemd1.Unit", "ActiveEnterTimestamp"
        ),
        # timestamp of the last time a unit exited the active state.
        "Last Finish": properties.Get(
            "org.freedesktop.systemd1.Unit", "ActiveExitTimestamp"
        ),
        "Next Start": properties.Get(
            "org.freedesktop.systemd1.Timer", "NextElapseUSecRealtime"
        ),
    }
    # "org.freedesktop.systemd1.Timer", "LastTriggerUSec"
    missing_dt = datetime(1970, 1, 1, 0, 0, 0)

    def timestamp_to_dt(timestamp):
        try:
            dt = datetime.fromtimestamp(timestamp / 1_000_000)
            if dt == missing_dt:
                return None
            return dt
        except ValueError:
            # "year 586524 is out of range"
            return None

    schedule = {field: timestamp_to_dt(val) for field, val in schedule.items()}
    # TimersCalendar contains an array of structs that contain information about all realtime/calendar timers of this timer unit. The structs contain a string identifying the timer base, which may only be "OnCalendar" for now; the calendar specification string; the next elapsation point on the CLOCK_REALTIME clock, relative to its epoch.
    timers_cal = []
    # for timer_type in ("TimersMonotonic", "TimersCalendar"):
    for timer in properties.Get("org.freedesktop.systemd1.Timer", "TimersCalendar"):
        base, spec, next_start = timer
        timers_cal.append(
            {
                "base": base,
                "spec": spec,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Calendar"] = timers_cal
    if (not schedule["Next Start"]) and (
        next_start := [t["next_start"] for t in timers_cal if t["next_start"]]
    ):
        schedule["Next Start"] = min(next_start)
    # TimersMonotonic contains an array of structs that contain information about all monotonic timers of this timer unit. The structs contain a string identifying the timer base, which is one of "OnActiveUSec", "OnBootUSec", "OnStartupUSec", "OnUnitActiveUSec", or "OnUnitInactiveUSec" which correspond to the settings of the same names in the timer unit files; the microsecond offset from this timer base in monotonic time; the next elapsation point on the CLOCK_MONOTONIC clock, relative to its epoch.
    timers_mono = []
    for timer in properties.Get("org.freedesktop.systemd1.Timer", "TimersMonotonic"):
        base, offset, next_start = timer
        timers_mono.append(
            {
                "base": base,
                "offset": offset,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Monotonic"] = timers_mono
    return schedule


def get_unit_files(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
) -> List[str]:
    """Get a list of paths of taskflow unit files."""
    file_states = get_unit_file_states(unit_type=unit_type, match=match, states=states)
    return list(file_states.keys())


def get_unit_file_states(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
) -> Dict[str, str]:
    """Map taskflow unit file path to unit state."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    files = list(systemd_manager().ListUnitFilesByPatterns(states, [pattern]))
    if not files:
        logger.error("No taskflow unit files found matching: %s", pattern)
    return {str(file): str(state) for file, state in files}


def get_units(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
) -> List[Dict[str, str]]:
    """Get metadata for taskflow units."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    files = list(systemd_manager().ListUnitsByPatterns(states, [pattern]))
    fields = [
        "unit_name",
        "description",
        "load_state",
        "active_state",
        "sub_state",
        "followed",
        "unit_path",
        "job_id",
        "job_type",
        "job_path",
    ]
    return [{k: str(v) for k, v in zip(fields, f)} for f in files]


def _make_unit_match_pattern(
    unit_type: Optional[Literal["service", "timer"]] = None, match: Optional[str] = None
) -> str:
    pattern = match or ""
    if unit_type and not pattern.endswith(f".{unit_type}"):
        pattern += f".{unit_type}"
    if _SYSTEMD_FILE_PREFIX not in pattern:
        pattern = f"*{_SYSTEMD_FILE_PREFIX}*{pattern}"
    pattern += "*"
    return re.sub(r"\*+", "*", pattern)
