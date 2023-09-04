import json
import re
from subprocess import run
from typing import Callable, Dict, List, Optional

import click
from dynamic_imports import import_module_attr
from paramiko import AutoAddPolicy, SSHClient

from ezloggers import get_logger

logger = get_logger("task-flows", stdout=True)

_FILE_PREFIX = "task_flow_"


def ssh_client():
    client = SSHClient()
    client.set_missing_host_key_policy(AutoAddPolicy())
    client.connect()
    return client


def ftp_client():
    # ftp_client.put(local / file / path, remote / file / path)
    # ftp_client.close()
    return ssh_client().open_sftp()


def func_call_cmd(func: Callable, *args, **kwargs) -> str:
    """Generate command to call function with optional args and kwargs."""
    # TODO env arg with non-poetry stuff.
    cmd = f"poetry run _tasks_flows_call {func.__module__} {func.__name__}"
    if args:
        cmd += f" --args {json.dumps(args)}"
    if kwargs:
        cmd += f" --kwargs {json.dumps(kwargs)}"
    return cmd


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
