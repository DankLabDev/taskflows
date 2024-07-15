from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from time import sleep, time

import pytest

from taskflows import _SYSTEMD_FILE_PREFIX
from taskflows.service import Calendar, Periodic, Service, constraints
from taskflows.service.service import systemd_dir


@pytest.fixture
def log_dir():
    d = Path(__file__).parent / "logs"
    d.mkdir(exist_ok=True)
    yield d
    rmtree(d)


def create_test_name():
    return f"test_{time()}".replace(".", "")


def test_config():
    v = Calendar("Sun 17:00 America/New_York")
    assert isinstance(v.unit_entries, set)

    v = Periodic(start_on="boot", period=10, relative_to="start")
    assert isinstance(v.unit_entries, set)

    v = Periodic("login", 1, "start")
    assert isinstance(v.unit_entries, set)

    v = constraints.Memory(amount=1000000, constraint=">=", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.Memory(amount=908902, constraint="=", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUs(amount=9, constraint=">=", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUPressure(max_percent=80, timespan="5min", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.MemoryPressure(max_percent=90, timespan="5min", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUPressure(max_percent=80, timespan="1min", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.IOPressure(max_percent=80, timespan="10sec", silent=True)
    assert isinstance(v.unit_entries, set)


def test_service_management(log_dir):
    # create a minimal service.
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    srv = Service(
        name=test_name, start_command=f"bash -c 'echo {test_name} >> {log_file}'"
    )
    srv.create()
    service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{test_name}.service"
    assert service_file.is_file()
    assert len(service_file.read_text())
    srv.start()
    sleep(0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    srv.remove()
    assert not service_file.exists()


def test_schedule(log_dir):
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    run_time = datetime.now(timezone.utc) + timedelta(seconds=1)
    srv = Service(
        name=test_name,
        start_command=f"bash -c 'echo {test_name} >> {log_file}'",
        start_schedule=Calendar.from_datetime(run_time),
    )
    srv.create()
    timer_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{test_name}.timer"
    assert timer_file.is_file()
    assert len(timer_file.read_text())
    assert not log_file.is_file()
    sleep((run_time - datetime.now(timezone.utc)).total_seconds() + 0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    srv.remove()
    assert not timer_file.exists()
