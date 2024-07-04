import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import click
from dynamic_imports import import_module_attr


@dataclass
class Venv(ABC):
    env_name: str

    @abstractmethod
    def create_env_command(self, command: str) -> str:
        pass


@dataclass
class MambaEnv(Venv):
    def create_env_command(self, command: str) -> str:
        """Generate mamba command."""
        for dist_t in ("mambaforge", "miniforge3"):
            mamba_exe = Path.home().joinpath(dist_t, "bin", "mamba")
            if mamba_exe.is_file():
                # return f"bash -c '{mamba_exe} run -n {self.env_name} {command}'"
                return f"{mamba_exe} run -n {self.env_name} {command}"
        raise FileNotFoundError("mamba executable not found!")


def call_function(func: Callable, *args, **kwargs) -> str:
    """Generate command to call function with optional args and kwargs."""
    cmd = f"_import_and_call_function {func.__module__} {func.__name__}"
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
def _import_and_call_function(
    module: str, func: str, args: Optional[str] = None, kwargs: Optional[str] = None
):
    """Import function and call it. (This is an installed function)"""
    args = json.loads(args) if args else []
    kwargs = json.loads(kwargs) if kwargs else {}
    func = import_module_attr(module, func)
    func(*args, **kwargs)


@click.command()
@click.argument("module")
@click.argument("var_name")
def _import_and_run_docker_service(module: str, var_name: str):
    """Import Docker container and run it. (This is an installed function)"""
    service = import_module_attr(module, var_name)
    service.container.run()
