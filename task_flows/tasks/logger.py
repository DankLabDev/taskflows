import sys
from datetime import datetime
from functools import partial
from typing import Any, Literal, Optional, Sequence

import sqlalchemy as sa
from alert_msgs import ContentType, FontSize, Map, Text, send_alert

from task_flows.database.core import create_missing_tables, engine_from_env
from task_flows.database.tables import task_errors_table, task_runs_table


class TaskLogger:
    """Utility class for handing database logging, sending alerts, etc."""

    create_missing_tables()

    def __init__(
        self,
        name: str,
        required: bool,
        exit_on_complete: bool,
        alert_methods: Optional[Sequence[Literal["slack", "email"]]] = None,
        alert_events: Optional[Sequence[Literal["start", "error", "finish"]]] = None,
    ):
        self.name = name
        self.required = required
        self.exit_on_complete = exit_on_complete
        self.alert_events = alert_events or []

        if self.alert_events:
            if not alert_methods:
                raise ValueError(
                    f"Can not send alerts for {self.alert_events} unless `alert_methods` is provided."
                )
            self._send_alerts = partial(send_alert, methods=alert_methods)
        self.engine = engine_from_env()
        self.errors = []

    def record_task_start(self):
        self.start_time = datetime.utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                sa.insert(task_runs_table).values(
                    {"task_name": self.name, "started": self.start_time}
                )
            )
        if "start" in self.alert_events:
            self._alert_task_start()

    def record_task_error(self, error: Exception):
        self.errors.append(error)
        with self.engine.begin() as conn:
            statement = sa.insert(task_errors_table).values(
                {
                    "task_name": self.name,
                    "type": str(type(error)),
                    "message": str(error),
                }
            )
            conn.execute(statement)
        if "error" in self.alert_events:
            self._alert_task_error(error)

    def record_task_finish(
        self,
        success: bool,
        return_value: Any = None,
        retries: int = 0,
    ) -> datetime:
        self.finish_time = datetime.utcnow()
        self.success = success
        self.return_value = return_value
        self.retries = retries
        self.status = "success" if success else "failed"
        with self.engine.begin() as conn:
            conn.execute(
                sa.update(task_runs_table)
                .where(
                    task_runs_table.c.task_name == self.name,
                    task_runs_table.c.started == self.start_time,
                )
                .values(
                    finished=self.finish_time,
                    retries=self.retries,
                    status=self.status,
                    return_value=self.return_value,
                )
            )
        if "finish" in self.alert_events:
            self._alert_task_finish()
        if self.errors and self.required:
            if self.exit_on_complete:
                sys.exit(1)
            if len(self.errors) > 1:
                raise RuntimeError(f"Error executing task {self.name}: {self.errors}")
            raise type(self.errors[0])(str(self.errors[0]))
        if self.exit_on_complete:
            sys.exit(0 if success else 1)

    def _alert_task_start(self):
        msg = (
            f"Started task {self.name} {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        components = [
            Text(
                msg,
                font_size=FontSize.LARGE,
                content_type=ContentType.IMPORTANT,
            )
        ]
        self._send_alerts(subject=msg, components=components)

    def _alert_task_error(self, error: Exception):
        subject = f"Error executing task {self.name}: {type(error)}"
        components = [
            Text(
                f"{subject} -- {error}",
                font_size=FontSize.LARGE,
                content_type=ContentType.ERROR,
            )
        ]
        self._send_alerts(subject=subject, components=components)

    def _alert_task_finish(self):
        subject = f"{self.status}: {self.name}"
        components = [
            Text(
                subject,
                font_size=FontSize.LARGE,
                content_type=ContentType.IMPORTANT
                if self.success
                else ContentType.ERROR,
            ),
            Map(
                {
                    "Start": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "Finish": self.finish_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "Return Value": self.return_value,
                }
            ),
        ]
        if self.errors:
            components.append(
                Text(
                    "ERRORS",
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
        self._send_alerts(subject=subject, components=components)
