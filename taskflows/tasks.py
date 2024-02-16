import asyncio
import inspect
import sys
from datetime import datetime, timezone
from functools import partial
from logging import Logger
from typing import Any, Callable, List, Literal, Optional, Sequence

import sqlalchemy as sa
from alert_msgs import ContentType, Emoji, FontSize, MsgDst, Text, send_alert
from func_timeout import func_timeout
from func_timeout.exceptions import FunctionTimedOut

from .db import task_flows_db
from .utils import Alerts
from .utils import logger as default_logger


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


class TaskLogger:
    """Utility class for handing database logging, sending alerts, etc."""

    def __init__(
        self,
        name: str,
        required: bool,
        exit_on_complete: bool,
        alerts: Optional[Sequence[Alerts]] = None,
    ):
        self.name = name
        self.required = required
        self.exit_on_complete = exit_on_complete
        self.alerts = alerts or []
        if isinstance(self.alerts, Alerts):
            self.alerts = [self.alerts]
        self.db = task_flows_db()
        self.engine = self.db.engine
        self.errors = []

    def on_task_start(self):
        self.start_time = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                sa.insert(self.db.task_runs_table).values(
                    task_name=self.name, started=self.start_time
                )
            )
        if send_to := self._event_alerts("start"):
            components = [
                Text(
                    f"{Emoji.rocket} Starting: {self.name}",
                    font_size=FontSize.LARGE,
                    content_type=ContentType.IMPORTANT,
                )
            ]
            send_alert(content=components, send_to=send_to)

    def on_task_error(self, error: Exception):
        self.errors.append(error)
        with self.engine.begin() as conn:
            statement = sa.insert(self.db.task_errors_table).values(
                task_name=self.name,
                type=str(type(error)),
                message=str(error),
            )
            conn.execute(statement)
        if send_to := self._event_alerts("error"):
            subject = f"{type(error)} Error executing task {self.name}"
            components = [
                Text(
                    f"{Emoji.red_x} {subject}: {error}",
                    font_size=FontSize.LARGE,
                    content_type=ContentType.ERROR,
                )
            ]
            send_alert(content=components, send_to=send_to, subject=subject)

    def on_task_finish(
        self,
        success: bool,
        return_value: Any = None,
        retries: int = 0,
    ) -> datetime:
        finish_time = datetime.now(timezone.utc)
        status = "success" if success else "failed"
        with self.engine.begin() as conn:
            conn.execute(
                sa.update(self.db.task_runs_table)
                .where(
                    self.db.task_runs_table.c.task_name == self.name,
                    self.db.task_runs_table.c.started == self.start_time,
                )
                .values(
                    finished=finish_time,
                    retries=retries,
                    status=status,
                )
            )
        if send_to := self._event_alerts("finish"):
            components = [
                Text(
                    f"{Emoji.green_check if success else Emoji.red_x} {self.name} {self.start_time} - {finish_time} ({finish_time-self.start_time})",
                    font_size=FontSize.LARGE,
                    content_type=(
                        ContentType.IMPORTANT if success else ContentType.ERROR
                    ),
                )
            ]
            if return_value is not None:
                components.append(
                    Text(
                        f"Result: {return_value}",
                        font_size=FontSize.MEDIUM,
                        content_type=ContentType.IMPORTANT,
                    )
                )
            if self.errors:
                components.append(
                    Text(
                        f"ERRORS{Emoji.red_exclamation}",
                        font_size=FontSize.LARGE,
                        content_type=ContentType.ERROR,
                    )
                )
                for e in self.errors:
                    components.append(
                        Text(
                            f"{type(e)}: {e}",
                            font_size=FontSize.MEDIUM,
                            content_type=ContentType.INFO,
                        )
                    )
            send_alert(content=components, send_to=send_to)
        if self.errors and self.required:
            if self.exit_on_complete:
                sys.exit(1)
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
        if self.exit_on_complete:
            sys.exit(0 if success else 1)

    def _event_alerts(self, event: Literal["start", "error", "finish"]) -> List[MsgDst]:
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
        logger.error(msg)
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
            logger.error(msg)
            task_logger.on_task_error(exp)
    task_logger.on_task_finish(success=False, retries=retries)
