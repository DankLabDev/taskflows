import asyncio
from time import sleep

import pytest

from taskflows import task


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
@pytest.mark.parametrize("exit_on_complete", [True, False])
def test_good_task(required, retries, timeout, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        exit_on_complete=exit_on_complete,
    )
    def return_100() -> int:
        return 100

    if exit_on_complete:
        with pytest.raises(SystemExit):
            return_100()
    else:
        result = return_100()
        assert result == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
@pytest.mark.parametrize("exit_on_complete", [True, False])
async def test_good_async_task(required, retries, timeout, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        exit_on_complete=exit_on_complete,
    )
    async def return_100() -> int:
        return 100

    if exit_on_complete:
        with pytest.raises(SystemExit):
            await return_100()
    else:
        result = await return_100()
        assert result == 100


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
@pytest.mark.parametrize("exit_on_complete", [True, False])
def test_task_exception(required, retries, timeout, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        exit_on_complete=exit_on_complete,
    )
    def throws_exception():
        raise RuntimeError("This task failed.")

    if exit_on_complete:
        with pytest.raises(SystemExit):
            throws_exception()
    elif required:
        with pytest.raises(RuntimeError):
            throws_exception()
    else:
        assert throws_exception() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
@pytest.mark.parametrize("exit_on_complete", [True, False])
async def test_async_task_exception(required, retries, timeout, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        exit_on_complete=exit_on_complete,
    )
    async def throws_exception():
        raise RuntimeError("This task failed.")

    if exit_on_complete:
        with pytest.raises(SystemExit):
            await throws_exception()
    elif required:
        with pytest.raises(RuntimeError):
            await throws_exception()
    else:
        assert await throws_exception() is None


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("exit_on_complete", [True, False])
def test_task_timeout(required, retries, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
        exit_on_complete=exit_on_complete,
    )
    def do_sleep():
        sleep(0.5)

    if exit_on_complete:
        with pytest.raises(SystemExit):
            do_sleep()
    elif required:
        with pytest.raises(TimeoutError):
            do_sleep()
    else:
        assert do_sleep() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("exit_on_complete", [True, False])
async def test_async_task_timeout(required, retries, exit_on_complete):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
        exit_on_complete=exit_on_complete,
    )
    async def do_sleep():
        await asyncio.sleep(0.5)

    if exit_on_complete:
        with pytest.raises(SystemExit):
            await do_sleep()
    elif required:
        with pytest.raises(TimeoutError):
            await do_sleep()
    else:
        assert await do_sleep() is None
