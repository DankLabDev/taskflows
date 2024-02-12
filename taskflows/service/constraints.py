from typing import Literal

from pydantic import BaseModel


# TODO handle: Failing conditions or asserts will not result in the unit being moved into the "failed" state.
class HardwareConstraint(BaseModel):
    amount: int
    constraint: Literal["<", "<=", "=", "!=", ">=", ">"] = ">="
    # abort without an error message
    silent: bool = False

    def unit_entries(self) -> str:
        action = "Constraint" if self.silent else "Assert"
        return [f"{action}{self.__class__.__name__}={self.constraint}{self.amount}"]


class Memory(HardwareConstraint):
    """Verify that the specified amount of system memory (in bytes) adheres to the constraint."""

    ...


class CPUs(HardwareConstraint):
    """Verify that the system's CPU count adheres to the provided constraint."""

    ...


class SystemLoadConstraint(BaseModel):
    """
    Verify that the overall system (memory, CPU or IO) pressure is below or equal to a threshold.
    The pressure will be measured as an average over the last `timespan` minutes before the attempt to start the unit is performed.
    """

    max_percent: int
    timespan: Literal["10sec", "1min", "5min"] = "5min"
    # abort without an error message
    silent: bool = False

    def unit_entries(self) -> str:
        action = "Constraint" if self.silent else "Assert"
        return [
            f"{action}{self.__class__.__name__}={self.max_percent}%/{self.timespan}"
        ]


class MemoryPressure(SystemLoadConstraint):
    ...


class CPUPressure(SystemLoadConstraint):
    ...


class IOPressure(SystemLoadConstraint):
    ...
