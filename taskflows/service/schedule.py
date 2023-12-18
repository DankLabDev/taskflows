from datetime import datetime
from typing import List, Literal

from pydantic.dataclasses import dataclass


@dataclass
class Schedule:
    def unit_entries(self) -> List[str]:
        raise NotImplementedError("unit_entries not implemented in Schedule")


@dataclass
class Calendar(Schedule):
    """Defines realtime (i.e. wallclock) timers with calendar event expressions.

    Format: DayOfWeek Year-Month-Day Hour:Minute:Second TimeZone
    Time zone is optional.
    Day of week. Possible values are Sun,Mon,Tue,Wed,Thu,Fri,Sat
    Example: Sun 17:00 America/New_York
    """

    schedule: str

    @classmethod
    def from_datetime(cls, dt: datetime):
        return cls(schedule=dt.strftime("%a %y-%m-%d %H:%M:%S %Z").strip())

    def unit_entries(self) -> List[str]:
        return [f"OnCalendar={self.schedule}"]


@dataclass
class Periodic(Schedule):
    # 'boot': Start service when machine is booted.
    # 'login': Start service when user logs in.
    # 'command': Don't automatically start service. Only start on explicit command from user.
    start_on: Literal["boot", "login", "command"]
    # Run the service every `period` seconds.
    period: int
    # Measure period from
    relative_to: Literal["period", "finish", "start"]

    def unit_entries(self) -> List[str]:
        entries = []
        if self.start_on == "boot":
            # start 1 second after boot.
            entries.append("OnBootSec=1")
        elif self.start_on == "login":
            # start 1 second after the service manager is started (which is on login).
            entries.append("OnStartupSec=1")
        if self.relative_to == "period":
            # defines a timer relative to the moment the timer unit itself is activated.
            entries.append(f"OnActiveSec={self.period}")
        elif self.relative_to == "start":
            # defines a timer relative to when the unit the timer unit is activating was last activated.
            entries.append(f"OnUnitActiveSec={self.period}")
        elif self.relative_to == "finish":
            # defines a timer relative to when the unit the timer unit is activating was last deactivated.
            entries.append(f"OnUnitInactiveSec={self.period}")
        return entries
