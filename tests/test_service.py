from datetime import UTC, datetime, timedelta
from pathlib import Path
from shutil import rmtree
from time import sleep, time

import pytest
from quicklogs import get_logger

from taskflows.service import Calendar, Service
from taskflows.service.service import systemd_dir
from taskflows.utils import _FILE_PREFIX


@pytest.fixture
def log_dir():
    d = Path(__file__).parent / "logs"
    d.mkdir(exist_ok=True)
    yield d
    rmtree(d)


@pytest.fixture
def test_name():
    return f"test_{int(time())}"


@pytest.fixture
def logger(test_name):
    return get_logger(
        name=test_name,
        level="INFO",
        stdout=True,
        file_dir=log_dir,
    )


def test_service_management(test_name, log_dir):
    # create a minimal service.
    log_file = (log_dir / f"{test_name}.log").resolve()
    srv = Service(name=test_name, command=f"bash -c 'echo {test_name} >> {log_file}'")
    srv.create()
    service_file = systemd_dir / f"{_FILE_PREFIX}{test_name}.service"
    assert service_file.is_file()
    assert len(service_file.read_text())
    srv.run()
    sleep(0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    srv.remove()
    assert not service_file.exists()


def test_schedule(test_name, log_dir):
    log_file = (log_dir / f"{test_name}.log").resolve()
    run_time = datetime.now(UTC) + timedelta(seconds=5)
    srv = Service(
        name=test_name,
        command=f"bash -c 'echo {test_name} >> {log_file}'",
        schedule=Calendar.from_datetime(run_time),
    )
    srv.create()
    timer_file = systemd_dir / f"{_FILE_PREFIX}{test_name}.timer"
    assert timer_file.is_file()
    assert len(timer_file.read_text())
    srv.run()
    assert not log_file.is_file()
    sleep((run_time - datetime.now(UTC)).total_seconds() + 0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    srv.remove()
    assert not timer_file.exists()
