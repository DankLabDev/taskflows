from datetime import datetime
from typing import Literal, Tuple

from pydantic.dataclasses import dataclass

DEFAULT_MAX_RESTART_RATE = (1000, 1)


class Schedule:
    def __init__(self, max_restart_rate: Tuple[int,int] = DEFAULT_MAX_RESTART_RATE):
        n_restarts, n_seconds = max_restart_rate
        self.unit_entries = {
            f"StartLimitIntervalSec={n_seconds}",
            f"StartLimitBurst={n_restarts}",
        }


@dataclass
class Calendar(Schedule):
    """Defines realtime (i.e. wallclock) timers with calendar event expressions.

    Format: DayOfWeek Year-Month-Day Hour:Minute:Second TimeZone
    Time zone is optional.
    Day of week. Possible values are Sun,Mon,Tue,Wed,Thu,Fri,Sat
    Example: Sun 17:00 America/New_York
    """

    schedule: str
    persistent: bool = True

    def __post_init__(self):
        super().__init__()
        self.unit_entries.add(f"OnCalendar={self.schedule}")
        if self.persistent:
            self.unit_entries.add("Persistent=true")

    @classmethod
    def from_datetime(cls, dt: datetime):
        return cls(schedule=dt.strftime("%a %y-%m-%d %H:%M:%S %Z").strip())


@dataclass
class Periodic(Schedule):
    # 'boot': Start service when machine is booted.
    # 'login': Start service when user logs in.
    # 'command': Don't automatically start service. Only start on explicit command from user.
    start_on: Literal["boot", "login", "command"]
    # Run the service every `period` seconds.
    period: int
    # 'start': Measure period from when the service started.
    # 'finish': Measure period from when the service last finished.
    relative_to: Literal["finish", "start"]

    def __post_init__(self):
        super().__init__()
        self.unit_entries.add("AccuracySec=1ms")
        if self.start_on == "boot":
            # start 1 second after boot.
            self.unit_entries.add("OnBootSec=1")
        elif self.start_on == "login":
            # start 1 second after the service manager is started (which is on login).
            self.unit_entries.add("OnStartupSec=1")
        elif self.relative_to == "start":
            # defines a timer relative to when the unit the timer unit is activating was last activated.
            self.unit_entries.add(f"OnUnitActiveSec={self.period}s")
        elif self.relative_to == "finish":
            # defines a timer relative to when the unit the timer unit is activating was last deactivated.
            self.unit_entries.add(f"OnUnitInactiveSec={self.period}s")
