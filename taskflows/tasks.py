import asyncio
import inspect
import sys
from datetime import datetime, timezone
from functools import partial
from logging import Logger
from typing import Any, Callable, List, Literal, Optional, Sequence

import sqlalchemy as sa
from dl_alerts import ContentType, Emoji, FontSize, MsgDst, Text, send_alert
from func_timeout import func_timeout
from func_timeout.exceptions import FunctionTimedOut
from pydantic import BaseModel

from taskflows import logger as default_logger

from .db import engine, get_tasks_db


class Alerts(BaseModel):
    # where to send the alerts (e.g. email, slack, etc.)
    send_to: Sequence[MsgDst]
    # when to send the alerts (start, error, finish)
    send_on: Sequence[Literal["start", "error", "finish"]]

    def model_post_init(self, __context) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]


def task(
    name: Optional[str] = None,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[int] = None,
    db_record: bool = False,
    alerts: Optional[Sequence[Alerts]] = None,
    logger: Optional[Logger] = None,
):
    """Decorator for task functions.

    Args:
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times to retry the task on failure. Defaults to 0.
        timeout (Optional[int], optional): Timeout (seconds) for function execution. Defaults to None.
        alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations.
    """
    logger = logger or default_logger

    def task_decorator(func):
        # @functools.wraps(func)
        task_logger = TaskLogger(
            name=name or func.__name__,
            required=required,
            db_record=db_record,
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


class TaskLogger:
    """Utility class for handing database logging, sending alerts, etc."""

    def __init__(
        self,
        name: str,
        required: bool,
        db_record: bool = False,
        alerts: Optional[Sequence[Alerts]] = None,
    ):
        """
        Initialize a TaskLogger instance.

        Args:
            name (str): Name of the task.
            required (bool): Whether the task is required.
            db_record (bool, optional): Whether to record the task in the database. Defaults to False.
            alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations. Defaults to None.
        """
        self.name = name
        self.required = required
        self.db_record = db_record
        self.alerts = alerts or []
        if isinstance(self.alerts, Alerts):
            self.alerts = [self.alerts]
        if db_record:
            self.db = get_tasks_db()
        self.errors = []

    def on_task_start(self):
        """
        Handles actions to be performed when a task starts.

        Records the start time of the task, logs it to the database if `db_record`
        is enabled, and sends start alerts if configured.

        Raises:
            SQLAlchemyError: If any database operation fails.
        """
        # record the start time of the task
        self.start_time = datetime.now(timezone.utc)

        # if db_record is enabled, log the start of the task to the database
        if self.db_record:
            with engine.begin() as conn:
                # construct the SQL query to insert the task start time
                statement = sa.insert(self.db.task_runs_table).values(
                    # the name of the task
                    task_name=self.name,
                    # the time the task started
                    started=self.start_time,
                )
                # execute the query
                conn.execute(statement)

        # if there are any start alerts configured, send them
        if send_to := self._event_alerts("start"):
            # construct the start alert message
            components = [
                Text(
                    # the text to be displayed in the alert
                    f"{Emoji.rocket} Starting: {self.name}",
                    # the font size of the text
                    font_size=FontSize.LARGE,
                    # the level of the alert
                    level=ContentType.IMPORTANT,
                )
            ]
            # send the alert
            send_alert(content=components, send_to=send_to)

    def on_task_error(self, error: Exception):
        """
        Handles actions to be performed when a task encounters an error.

        1. Adds the error to the list of errors encountered by the task.
        2. If `db_record` is enabled, records the error in the database.
        3. If there are any error alerts configured, sends them.

        Args:
            error (Exception): The exception that was raised.

        Raises:
            SQLAlchemyError: If any database operation fails.
        """
        # 1. add the error to the list of errors encountered by the task
        self.errors.append(error)

        # 2. if db_record is enabled, record the error in the database
        if self.db_record:
            with engine.begin() as conn:
                # construct the SQL query to insert the error into the task
                # errors table
                statement = sa.insert(self.db.task_errors_table).values(
                    # the name of the task
                    task_name=self.name,
                    # the type of the exception
                    type=str(type(error)),
                    # the message from the exception
                    message=str(error),
                )
                # execute the query
                conn.execute(statement)

        # 3. if there are any error alerts configured, send them
        if send_to := self._event_alerts("error"):
            # construct the error alert message
            subject = f"{type(error)} Error executing task {self.name}"
            components = [
                Text(
                    # the text to be displayed in the alert
                    f"{Emoji.red_x} {subject}: {error}",
                    # the font size of the text
                    font_size=FontSize.LARGE,
                    # the level of the alert
                    level=ContentType.ERROR,
                )
            ]
            # send the alert
            send_alert(content=components, send_to=send_to, subject=subject)

    def on_task_finish(
        self,
        success: bool,
        return_value: Any = None,
        retries: int = 0,
    ) -> datetime:
        """
        Handles actions to be performed when a task finishes execution.

        1. Records the task run in the database, if `db_record` is enabled.
        2. If there are any finish alerts configured, sends them.

        Args:
            success (bool): Whether the task executed successfully.
            return_value (Any): The value returned by the task, if any.
            retries (int): The number of retries performed by the task, if any.
        """

        # record the finish time
        finish_time = datetime.now(timezone.utc)

        # determine the status of the task
        status = "success" if success else "failed"

        # if db_record is enabled, record the task run in the database
        if self.db_record:
            with engine.begin() as conn:
                # construct the SQL query to update the task runs table with
                # the finish status, retries, and finish time
                statement = sa.update(self.db.task_runs_table).where(
                    # the task name and start time must match the current task
                    self.db.task_runs_table.c.task_name == self.name,
                    self.db.task_runs_table.c.started == self.start_time,
                ).values(
                    # set the finish time
                    finished=finish_time,
                    # set the number of retries
                    retries=retries,
                    # set the status
                    status=status,
                )
                # execute the query
                conn.execute(statement)

        # if there are any finish alerts configured, send them
        if send_to := self._event_alerts("finish"):
            # construct the finish alert message
            components = [
                Text(
                    # the text to be displayed in the alert
                    f"{Emoji.green_check if success else Emoji.red_x} {self.name} {self.start_time} - {finish_time} ({finish_time-self.start_time})",
                    # the font size of the text
                    font_size=FontSize.LARGE,
                    # the level of the alert
                    level=(ContentType.IMPORTANT if success else ContentType.ERROR),
                )
            ]
            # if the task returned a value, include it in the alert
            if return_value is not None:
                components.append(
                    Text(
                        # the text to be displayed in the alert
                        f"Result: {return_value}",
                        # the font size of the text
                        font_size=FontSize.MEDIUM,
                        # the level of the alert
                        level=ContentType.IMPORTANT,
                    )
                )
            # if there were any errors, include them in the alert
            if self.errors:
                components.append(
                    Text(
                        # the text to be displayed in the alert
                        f"ERRORS{Emoji.red_exclamation}",
                        # the font size of the text
                        font_size=FontSize.LARGE,
                        # the level of the alert
                        level=ContentType.ERROR,
                    )
                )
                for e in self.errors:
                    components.append(
                        Text(
                            # the text to be displayed in the alert
                            f"{type(e)}: {e}",
                            # the font size of the text
                            font_size=FontSize.MEDIUM,
                            # the level of the alert
                            level=ContentType.INFO,
                        )
                    )
            # send the alert
            send_alert(content=components, send_to=send_to)

        # if there were any errors and the task is required, raise an error
        if self.errors and self.required:
            if len(self.errors) > 1:
                error_types = {type(e) for e in self.errors}
                if len(error_types) == 1:
                    errors_str = "\n\n".join([str(e) for e in self.errors])
                    raise error_types.pop()(
                        f"{len(self.errors)} errors executing task {self.name}:\n{errors_str}"
                    )
                raise RuntimeError(
                    f"{len(self.errors)} errors executing task {self.name}: {self.errors}"
                )
            raise type(self.errors[0])(str(self.errors[0]))

    def _event_alerts(self, event: Literal["start", "error", "finish"]) -> List[MsgDst]:
        """
        Get the list of destinations to send alerts for the given event.

        Args:
            event: The event (start, error, or finish) for which to get the
                alert destinations.

        Returns:
            A list of destinations to send the alert to.
        """
        send_to = []
        for alert in self.alerts:
            if event in alert.send_on:
                send_to += alert.send_to
        return send_to


def _task_wrapper(
    *,
    func: Callable,
    retries: int,
    timeout: float,
    task_logger: TaskLogger,
    logger: Logger,
    **kwargs,
):
    """
    Wrap a task function with error handling, retries, and logging.

    Calls a task function with the given keyword arguments, and handles any
    exceptions that are raised. If an exception is raised, it will be logged
    and the task will be retried up to the given number of times.

    Logs the start and finish of the task, and any errors that occur.

    Args:
        func: The task function to be called.
        retries: The number of times to retry the task on error.
        timeout: The maximum amount of time to allow the task to run.
        task_logger: The logger to use for logging the task.
        logger: The logger to use for logging errors.
        **kwargs: The keyword arguments to pass to the task function.

    Returns:
        The result of calling the task function, or None if the task failed
        after all retries.
    """
    task_logger.on_task_start()
    for i in range(retries + 1):
        exp = None
        try:
            if timeout:
                # throws FunctionTimedOut if timeout is exceeded.
                result = func_timeout(timeout, func, kwargs=kwargs)
            else:
                result = func(**kwargs)
            task_logger.on_task_finish(success=True, retries=i, return_value=result)
            return result

        except FunctionTimedOut as e:
            # standardize timeout exception for both task and async task.
            exp = TimeoutError(e.msg)
        except Exception as e:
            exp = e
        msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
        logger.exception(msg)
        task_logger.on_task_error(exp)
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
    """
    Async wrapper for a task function.

    Wraps a task function with retry and timeout logic, and logs the result
    of the task using the provided logger.

    Args:
        func: The task function to wrap.
        retries: The number of times to retry the task on failure.
        timeout: The timeout (in seconds) for the task, or None for no timeout.
        task_logger: The logger to use for logging the task.
        logger: The logger to use for logging errors.
        **kwargs: The keyword arguments to pass to the task function.

    Returns:
        The result of calling the task function, or None if the task failed
        after all retries.
    """
    task_logger.on_task_start()
    for i in range(retries + 1):
        try:
            if timeout:
                result = await asyncio.wait_for(func(**kwargs), timeout=timeout)
            else:
                result = await func(**kwargs)
            task_logger.on_task_finish(success=True, retries=i, return_value=result)
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.exception(msg)
            task_logger.on_task_error(exp)
    task_logger.on_task_finish(success=False, retries=retries)
