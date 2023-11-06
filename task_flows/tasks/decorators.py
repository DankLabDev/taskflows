import asyncio
import inspect
from functools import partial
from logging import Logger
from typing import Callable, Optional, Sequence

from func_timeout import func_timeout

from task_flows.utils import logger as default_logger

from .logger import TaskLogger
from task_flows.utils import Alerts


def task(
    name: str,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[int] = None,
    alerts: Optional[Sequence[Alerts]] = None,
    exit_on_complete: bool = False,
    logger: Optional[Logger] = None,
):
    """Decorator for task functions.

    Args:
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times to retry the task on failure. Defaults to 0.
        timeout (Optional[int], optional): Timeout for function execution. Defaults to None.
        alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations.
        exit_on_complete (bool, optional): Exit Python interpreter with task result status code when task is finished. Defaults to False.
    """
    logger = logger or default_logger

    def task_decorator(func):
        # @functools.wraps(func)
        task_logger = TaskLogger(
            name=name,
            required=required,
            exit_on_complete=exit_on_complete,
            alerts=alerts,
        )
        wrapper = (
            _async_task_wrapper if inspect.iscoroutinefunction(func) else _task_wrapper
        )
        return partial(
            wrapper,
            func=func,
            retries=retries,
            timeout=timeout,
            task_logger=task_logger,
            logger=logger,
        )

    return task_decorator


def _task_wrapper(
    *,
    func: Callable,
    retries: int,
    timeout: float,
    task_logger: TaskLogger,
    logger: Logger,
    **kwargs,
):
    task_logger.on_task_start()
    for i in range(retries + 1):
        try:
            if timeout:
                # throws FunctionTimedOut if timeout is exceeded.
                result = func_timeout(timeout, func, kwargs=kwargs)
            else:
                result = func(**kwargs)
            task_logger.on_task_finish(success=True, retries=i, return_value=result)
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.error(msg)
            task_logger.on_task_error(msg)
    task_logger.on_task_finish(success=False, retries=retries)


async def _async_task_wrapper(
    *,
    func: Callable,
    retries: int,
    timeout: float,
    task_logger: TaskLogger,
    logger: Logger,
    **kwargs,
):
    task_logger.on_task_start()
    for i in range(retries + 1):
        try:
            if timeout:
                result = await asyncio.wait_for(func(**kwargs), timeout)
            else:
                result = await func(**kwargs)
            task_logger.on_task_finish(success=True, retries=i, return_value=result)
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.error(msg)
            task_logger.on_task_error(msg)
    task_logger.on_task_finish(success=False, retries=retries)
