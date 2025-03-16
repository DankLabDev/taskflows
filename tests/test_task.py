import asyncio
from time import sleep

import pytest

from taskflows import task


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
def test_good_task(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
    )
    def return_100() -> int:
        return 100

    result = return_100()
    assert result == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])

async def test_good_async_task(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        
    )
    async def return_100() -> int:
        return 100

    result = await return_100()
    assert result == 100


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])

def test_task_exception(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        
    )
    def throws_exception():
        raise RuntimeError("This task failed.")

    if required:
        with pytest.raises(RuntimeError):
            throws_exception()
    else:
        assert throws_exception() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])

async def test_async_task_exception(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
        
    )
    async def throws_exception():
        raise RuntimeError("This task failed.")

    if required:
        with pytest.raises(RuntimeError):
            await throws_exception()
    else:
        assert await throws_exception() is None


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])

def test_task_timeout(required, retries):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
        
    )
    def do_sleep():
        sleep(0.5)

    if required:
        with pytest.raises(TimeoutError):
            do_sleep()
    else:
        assert do_sleep() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])

async def test_async_task_timeout(required, retries):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
        
    )
    async def do_sleep():
        await asyncio.sleep(0.5)

    if required:
        with pytest.raises(TimeoutError):
            await do_sleep()
    else:
        assert await do_sleep() is None
