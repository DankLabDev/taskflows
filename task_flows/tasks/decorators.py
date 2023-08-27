import asyncio
import inspect
import os
from functools import partial
from logging import Logger
from threading import Timer
from typing import Callable, Literal, Optional, Sequence

from task_flows.utils import logger as default_logger

from .logger import TaskLogger


def task(
    name: str,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[int] = None,
    alert_methods: Optional[Sequence[Literal["slack", "email"]]] = os.getenv(
        "TASK_FLOWS_ALERT_METHODS"
    ),
    alert_events: Optional[Sequence[Literal["start", "error", "finish"]]] = os.getenv(
        "TASK_FLOWS_ALERT_EVENTS"
    ),
    exit_on_complete: bool = False,
    logger: Optional[Logger] = None,
):
    """Decorator for task functions.

    Args:
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times the task can be retried on failure. Defaults to 0.
        timeout (Optional[int], optional): Timeout for function execution. Defaults to None.s
        alert_methods (Optional[Sequence[Literal["slack", "email"]]], optional): Types of alerts to send: email and/or Slack. Defaults to os.getenv('TASK_FLOWS_ALERT_METHODS').
        alert_events (Optional[Sequence[Literal["start", "error", "finish"]]], optional): Tasks events when alert(s) should be sent. Defaults to os.getenv('TASK_FLOWS_ALERT_EVENTS').
        exit_on_complete (bool, optional): Exit Python interpreter with task result status code when task is finished. Defaults to False.
    """
    # split string from environment variable.
    if isinstance(alert_methods, str):
        alert_methods = alert_methods.split(",")
    alert_methods = [t.strip().lower() for t in alert_methods] if alert_methods else []
    if isinstance(alert_events, str):
        alert_events = alert_events.split(",")
    alert_events = [t.strip().lower() for t in alert_events] if alert_events else []
    logger = logger or default_logger

    def task_decorator(func):
        # @functools.wraps(func)
        task_logger = TaskLogger(
            name=name,
            required=required,
            exit_on_complete=exit_on_complete,
            alert_methods=alert_methods,
            alert_events=alert_events,
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
    task_logger.record_task_start()
    for i in range(retries + 1):
        try:
            if timeout:
                timer = Timer(
                    timeout,
                    lambda: TimeoutError(f"Timeout executing task {task_logger.name}"),
                )
                timer.start()
                result = func(**kwargs)
                timer.cancel()
            else:
                result = func(**kwargs)
            task_logger.record_task_finish(success=True, retries=i, return_value=result)
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.error(msg)
            task_logger.record_task_error(msg)
    task_logger.record_task_finish(success=False, retries=retries)


async def _async_task_wrapper(
    *,
    func: Callable,
    retries: int,
    timeout: float,
    task_logger: TaskLogger,
    logger: Logger,
    **kwargs,
):
    task_logger.record_task_start()
    for i in range(retries + 1):
        try:
            if timeout:
                result = await asyncio.wait_for(func(**kwargs), timeout)
            else:
                result = await func(**kwargs)
            task_logger.record_task_finish(success=True, retries=i, return_value=result)
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.error(msg)
            task_logger.record_task_error(msg)
    task_logger.record_task_finish(success=False, retries=retries)
