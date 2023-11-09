from pathlib import Path
from typing import Literal, Sequence, Union

from .database import create_missing_tables
from .docker.container import Container
from .systemd.core import (
    create_scheduled_task,
    disable_scheduled_task,
    enable_scheduled_task,
    remove_scheduled_task,
)
from .systemd.models import Timer


class ScheduledTask:
    def __init__(
        self, task_name: str, command: str, timer: Union[Timer, Sequence[Timer]]
    ) -> None:
        self.task_name = task_name
        self.command = command
        self.timer = timer

    def create(self):
        create_missing_tables()
        create_scheduled_task(self.task_name, self.timer, self.command)

    def enable(self):
        enable_scheduled_task(task_name=self.task_name)

    def disable(self):
        disable_scheduled_task(task_name=self.task_name)

    def remove(self):
        remove_scheduled_task(task_name=self.task_name)


class ScheduledDockerTask(ScheduledTask):
    """A scheduled Docker task."""

    def __init__(
        self,
        task_name: str,
        timer: Union[Timer, Sequence[Timer]],
        container: Container,
        docker_action: Literal["start", "stop"] = "start",
    ) -> None:
        super().__init__(task_name, f"docker {docker_action} {task_name}", timer)
        self.container = container
        self.docker_action = docker_action

    def create(self):
        super().create()
        self.container.create()

    def remove(self):
        super().remove()
        self.container.remove()


class ScheduledMambaTask(ScheduledTask):
    """Metadata for a scheduled Mamba task."""

    def __init__(
        self,
        task_name: str,
        command: str,
        timer: Union[Timer, Sequence[Timer]],
        env_name: str,
    ) -> None:
        mamba_exe = Path.home().joinpath("mambaforge", "bin", "mamba")
        super().__init__(
            task_name, f"bash -c '{mamba_exe} run -n {env_name} {command}'", timer
        )
