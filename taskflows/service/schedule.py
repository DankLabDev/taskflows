from datetime import datetime
from typing import Literal

from pydantic.dataclasses import dataclass


class Schedule:
    """Base class for schedules."""
    def __init__(self, accuracy: str):
        self.unit_entries = {f"AccuracySec={accuracy}"}

@dataclass
class Calendar(Schedule):
    """Run a service at specified time(s)."""

    # when to start the service.
    # Format: DayOfWeek Year-Month-Day Hour:Minute:Second TimeZone
    # Time zone is optional. Day of week possible values are Sun,Mon,Tue,Wed,Thu,Fri,Sat
    # Examples:
    # Sun 17:00 America/New_York
    # Mon-Fri 16:00
    # Mon,Wed,Fri 16:30:30
    schedule: str
    # if machine is down at `schedule` time, start the service as soon as machine is back up.
    persistent: bool = True
    # max allowed deviation from declared start time.
    accuracy: str = "1ms"

    def __post_init__(self):
        super().__init__(self.accuracy)
        self.unit_entries.add(f"OnCalendar={self.schedule}")
        if self.persistent:
            self.unit_entries.add("Persistent=true")

    @classmethod
    def from_datetime(cls, dt: datetime):
        return cls(schedule=dt.strftime("%a %y-%m-%d %H:%M:%S %Z").strip())


@dataclass
class Periodic(Schedule):
    """Run a service periodically."""

    # 'boot': Start service when machine is booted.
    # 'login': Start service when user logs in.
    # 'command': Don't automatically start service. Only start on explicit command from user.
    start_on: Literal["boot", "login", "command"]
    # Run the service every `period` seconds.
    period: int
    # 'start': Measure period from when the service started.
    # 'finish': Measure period from when the service last finished.
    relative_to: Literal["finish", "start"]
    # max allowed deviation from declared start time.
    accuracy: str = "1ms"

    def __post_init__(self):
        super().__init__(self.accuracy)
        # start on
        if self.start_on == "boot":
            # start 1 second after boot.
            self.unit_entries.add("OnBootSec=1")
        elif self.start_on == "login":
            # start 1 second after the service manager is started (which is on login).
            self.unit_entries.add("OnStartupSec=1")
        # relative_to
        if self.relative_to == "start":
            # defines a timer relative to when the unit the timer unit is activating was last activated.
            self.unit_entries.add(f"OnUnitActiveSec={self.period}s")
        elif self.relative_to == "finish":
            # defines a timer relative to when the unit the timer unit is activating was last deactivated.
            self.unit_entries.add(f"OnUnitInactiveSec={self.period}s")
