import sys
from datetime import datetime
from typing import Any, Literal, Optional, Sequence, List

import sqlalchemy as sa
from alert_msgs import ContentType, FontSize, Map, Text, send_alert, SendCfg

from task_flows.database.core import create_missing_tables, engine_from_env
from task_flows.database.tables import task_errors_table, task_runs_table
from task_flows.utils import Alerts


class TaskLogger:
    """Utility class for handing database logging, sending alerts, etc."""

    create_missing_tables()

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
        self.engine = engine_from_env()
        self.errors = []

    def on_task_start(self):
        self.start_time = datetime.utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                sa.insert(task_runs_table).values(
                    {"task_name": self.name, "started": self.start_time}
                )
            )
        if send_to := self._event_alerts("start"):
            msg = f"Started task {self.name} {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            components = [
                Text(
                    msg,
                    font_size=FontSize.LARGE,
                    content_type=ContentType.IMPORTANT,
                )
            ]
            send_alert(components=components, send_to=send_to)

    def on_task_error(self, error: Exception):
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
        if send_to := self._event_alerts("error"):
            subject = f"Error executing task {self.name}: {type(error)}"
            components = [
                Text(
                    f"{subject} -- {error}",
                    font_size=FontSize.LARGE,
                    content_type=ContentType.ERROR,
                )
            ]
            send_alert(components=components, send_to=send_to)

    def on_task_finish(
        self,
        success: bool,
        return_value: Any = None,
        retries: int = 0,
    ) -> datetime:
        finish_time = datetime.utcnow()
        status = "success" if success else "failed"
        with self.engine.begin() as conn:
            conn.execute(
                sa.update(task_runs_table)
                .where(
                    task_runs_table.c.task_name == self.name,
                    task_runs_table.c.started == self.start_time,
                )
                .values(
                    finished=finish_time,
                    retries=retries,
                    status=status,
                    return_value=return_value,
                )
            )
        if send_to := self._event_alerts("finish"):
            subject = f"{status}: {self.name}"
            components = [
                Text(
                    subject,
                    font_size=FontSize.LARGE,
                    content_type=ContentType.IMPORTANT
                    if success
                    else ContentType.ERROR,
                ),
                Map(
                    {
                        "Start": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Finish": finish_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Return Value": return_value,
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
            send_alert(components=components, send_to=send_to)
        if self.errors and self.required:
            if self.exit_on_complete:
                sys.exit(1)
            if len(self.errors) > 1:
                raise RuntimeError(f"Error executing task {self.name}: {self.errors}")
            raise type(self.errors[0])(str(self.errors[0]))
        if self.exit_on_complete:
            sys.exit(0 if success else 1)

    def _event_alerts(
        self, event: Literal["start", "error", "finish"]
    ) -> List[SendCfg]:
        send_to = []
        for alert in self.alerts:
            if event in alert.send_on:
                send_to += alert.send_to
        return send_to
