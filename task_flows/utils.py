import json
import re
from subprocess import run
from typing import Callable, Dict, List, Literal, Optional, Sequence

import click
from alert_msgs import MsgDst
from dynamic_imports import import_module_attr
from ezloggers import get_logger
from pydantic import BaseModel

logger = get_logger("task-flows", stdout=True)

_FILE_PREFIX = "task_flow_"


class Alerts(BaseModel):
    send_to: Sequence[MsgDst]
    send_on: Sequence[Literal["start", "error", "finish"]]

    def model_post_init(self, __context) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]


def parse_systemctl_tables(command: List[str]) -> List[Dict[str, str]]:
    res = run(command, capture_output=True)
    lines = res.stdout.decode().split("\n\n")[0].splitlines()
    fields = list(re.finditer(r"[A-Z]+", lines.pop(0)))
    lines_data = []
    for line in lines:
        line_data = {}
        for next_idx, match in enumerate(fields, start=1):
            char_start_idx = match.start()
            if next_idx == len(fields):
                field_text = line[char_start_idx:]
            else:
                field_text = line[char_start_idx : fields[next_idx].start()]
            line_data[match.group()] = field_text.strip()
        lines_data.append(line_data)
    return lines_data


def func_call_cmd(func: Callable, *args, **kwargs) -> str:
    """Generate command to call function with optional args and kwargs."""
    # TODO env arg with non-poetry stuff.
    cmd = f"poetry run _tasks_flows_call {func.__module__} {func.__name__}"
    if args:
        cmd += f" --args {json.dumps(args)}"
    if kwargs:
        cmd += f" --kwargs {json.dumps(kwargs)}"
    return cmd


@click.command()
@click.argument("module")
@click.argument("func")
@click.option("--args")
@click.option("--kwargs")
def _task_flows_call(
    module: str, func: str, args: Optional[str] = None, kwargs: Optional[str] = None
):
    """This is installed."""
    args = json.loads(args) if args else []
    kwargs = json.loads(kwargs) if kwargs else {}
    func = import_module_attr(module, func)
    func(*args, **kwargs)
