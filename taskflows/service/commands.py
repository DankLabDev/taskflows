import json
from pathlib import Path
from typing import Callable, Optional

import click
from dynamic_imports import import_module_attr


def mamba_command(env_name: str, command: str) -> str:
    """Generate mamba command."""
    for dist_t in ("mambaforge", "miniforge3"):
        mamba_exe = Path.home().joinpath(dist_t, "bin", "mamba")
        if mamba_exe.is_file():
            return f"bash -c '{mamba_exe} run -n {env_name} {command}'"
    raise FileNotFoundError("mamba executable not found!")


def func_call(func: Callable, *args, **kwargs) -> str:
    """Generate command to call function with optional args and kwargs."""
    cmd = f"_taskflows_call {func.__module__} {func.__name__}"
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
def _taskflows_call(
    module: str, func: str, args: Optional[str] = None, kwargs: Optional[str] = None
):
    """Import function and call it. (This is installed)"""
    args = json.loads(args) if args else []
    kwargs = json.loads(kwargs) if kwargs else {}
    func = import_module_attr(module, func)
    func(*args, **kwargs)
