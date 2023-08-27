from dataclasses import dataclass


# https://www.freedesktop.org/software/systemd/man/systemd.timer.html#Options
@dataclass
class Timer:
    value: str


# TODO adopt calendar abstractions/formats that Prefect uses.
class OnCalendar(Timer):
    """Defines realtime (i.e. wallclock) timers with calendar event expressions."""

    ...


class OnActiveSec(Timer):
    """Defines a timer relative to the moment the timer unit itself is activated."""

    ...


class OnBootSec(Timer):
    """Defines a timer relative to when the machine was booted up.
    In containers, for the system manager instance, this is mapped to OnStartupSec=, making both equivalent.
    """

    ...


class OnStartupSec(Timer):
    """Defines a timer relative to when the service manager was first started.
    For system timer units this is very similar to OnBootSec= as the system service manager is generally started very early at boot.
    It's primarily useful when configured in units running in the per-user service manager,
    as the user service manager is generally started on first login only, not already during boot.
    """

    ...


class OnUnitActiveSec(Timer):
    """Defines a timer relative to when the unit the timer unit is activating was last activated."""

    ...


class OnUnitInactiveSec(Timer):
    """Defines a timer relative to when the unit the timer unit is activating was last deactivated."""

    ...
