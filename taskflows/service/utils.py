"""
dbus docs:
https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
https://pkg.go.dev/github.com/coreos/go-systemd/dbus (not Python, but same commands and has good docs)
"""

import re
import os
from functools import cache
from pprint import pformat
from typing import List, Literal, Optional, Sequence, Union

try:
    import dbus
except ImportError:
    pass
from taskflows.utils import logger, _SYSTEMD_FILE_PREFIX

from .docker import delete_docker_container


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


def escape_path(path):
    """Escape a path so that it can be used in a systemd file."""
    return systemd_manager().EscapePath(path)


def enable(unit: Optional[str] = None):
    """Enable currently disabled unit(s).

    Args:
        unit (str): Name or pattern of unit(s) to enable.
    """
    mgr = systemd_manager()
    files = get_unit_files(match=unit)
    logger.info("Enabling: %s", pformat(files))
    mgr.EnableUnitFiles(files, True, True)
    # user_systemctl("enable", "--now", f"{_SYSTEMD_FILE_PREFIX}{sf}.timer")


def is_enabled(unit: str):
    """Check if a unit is enabled."""
    try:
        return systemd_manager().GetUnitFileState(unit) == "enabled"
    except:
        return False


def disable(unit: Optional[str] = None):
    """Disable unit(s).

    Args:
        unit (str): Name or pattern of unit(s) to disable.
    """
    mgr = systemd_manager()
    files = get_unit_files(match=unit)
    logger.info("Disabling: %s", pformat(files))
    # user_systemctl("disable", "--now", f"{_SYSTEMD_FILE_PREFIX}{sf}.timer")
    # file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{sf}.timer"
    mgr.DisableUnitFiles(files, False)
    mgr.Reload()


def start_service(service: str):
    """
    start method will start service that is passed in this method.
    If service is already started then it will ignore it.
    It raise exception if there is error

    :param str service: name of the service
    """
    mgr = systemd_manager()
    files = get_unit_files(match=service)
    for sf in files:
        logger.info("Running service: %s", sf.name)
        mgr.StartUnit(sf, "replace")


def restart_service(service: str):
    """Restart running service(s).

    Args:
        service (str): Name or name pattern of service(s) to restart.
    """
    mgr = systemd_manager()
    for sf in get_unit_files(unit_type="service", match=service):
        logger.info("Restarting service: %s", sf)
        mgr.RestartUnit(sf, "replace")


def stop_service(service: str):
    """Stop running service(s).

    Args:
        service (str): Name or name pattern of service(s) to stop.
    """
    mgr = systemd_manager()
    for sf in get_unit_files(unit_type="service", match=service):
        logger.info("Stopping service: %s", sf)
        mgr.StopUnit(sf, "replace")
        # remove any failed status caused by stopping service.
        mgr.ResetFailedUnit(sf)


def remove_service(service: str):
    """Remove service(s).

    Args:
        service (str): Name or name pattern of service(s) to remove.
    """
    disable(service)
    container_names = set()
    mgr = systemd_manager()
    for srv_file in get_unit_files(unit_type="service", match=service):
        logger.info("Cleaning cache and runtime directories: %s.", srv_file)
        mgr.CleanUnit(srv_file.stem)
        container_name = re.search(
            r"docker (?:start|stop) ([\w-]+)", srv_file.read_text()
        )
        if container_name:
            container_names.add(container_name.group(1))
        # remove files.
        logger.info("Deleting %s", srv_file)
        os.remove(srv_file)
    for timer_file in get_unit_files(unit_type="timer", match=service):
        logger.info("Deleting %s", timer_file)
        os.remove(timer_file)
    for cname in container_names:
        delete_docker_container(cname)


def get_schedule_info(timer: str):
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
    schedule = {}
    for ts in ("ActiveEnterTimestamp", "InactiveExitTimestamp", "StateChangeTimestamp"):
        schedule[ts] = properties.Get("org.freedesktop.systemd1.Unit", ts)
    # NextElapseUSecRealtime = next run
    # LastTriggerUSec = last run
    # TimersCalendar contains an array of structs that contain information about all realtime/calendar timers of this timer unit. The structs contain a string identifying the timer base, which may only be "OnCalendar" for now; the calendar specification string; the next elapsation point on the CLOCK_REALTIME clock, relative to its epoch.

    # TimersMonotonic contains an array of structs that contain information about all monotonic timers of this timer unit. The structs contain a string identifying the timer base, which is one of "OnActiveUSec", "OnBootUSec", "OnStartupUSec", "OnUnitActiveUSec", or "OnUnitInactiveUSec" which correspond to the settings of the same names in the timer unit files; the microsecond offset from this timer base in monotonic time; the next elapsation point on the CLOCK_MONOTONIC clock, relative to its epoch.
    # The next trigger time is the second value in the tuple where the first value is the timer type (e.g., 'OnActive', 'OnBoot', etc.)
    # It's returned as a tuple of (type, value, next_elapse_usec_REALTIME)
    for ts in ("NextElapseUSecRealtime", "LastTriggerUSec"):
        schedule[ts] = properties.Get("org.freedesktop.systemd1.Timer", ts)
    # convert all timestamps from microseconds to datetime.
    for k, v in schedule.items():
        if v == 0:
            schedule[k] = None
        else:
            print(v)
            schedule[k] = v  # datetime.fromtimestamp(v // 1_000_000, tz=timezone.utc)
    schedule["TimersMonotonic"] = properties.Get(
        "org.freedesktop.systemd1.Timer", "TimersMonotonic"
    )
    return schedule


def get_unit_files(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
) -> List[str]:
    return _find_systemd_objects(
        return_type="files",
        unit_type=unit_type,
        match=match,
        states=states,
    )


def get_unit_file_states(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
):
    return _find_systemd_objects(
        return_type="file-state",
        unit_type=unit_type,
        match=match,
        states=states,
    )


def get_units(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
):
    return _find_systemd_objects(
        return_type="units",
        unit_type=unit_type,
        match=match,
        states=states,
    )


def _find_systemd_objects(
    return_type: Literal["units", "files", "file-state"],
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[Union[str, Sequence[str]]] = None,
):
    states = states or []
    pattern = match or ""
    if unit_type and not pattern.endswith(f".{unit_type}"):
        pattern += f".{unit_type}"
    if _SYSTEMD_FILE_PREFIX not in pattern:
        pattern = f"*{_SYSTEMD_FILE_PREFIX}*{pattern}"
    pattern = re.sub(r"\*+", "*", pattern)
    if return_type == "units":
        files = list(systemd_manager().ListUnitsByPatterns(states, [pattern]))
    else:
        files = list(systemd_manager().ListUnitFilesByPatterns(states, [pattern]))
    if not files:
        logger.error("No taskflow unit files found matching: %s", pattern)
        return []
    if return_type == "units":
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
    if return_type == "file-state":
        return {str(file): str(state) for file, state in files}
    if return_type == "files":
        return [str(file) for file, _ in files]
