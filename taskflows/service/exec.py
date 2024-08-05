import asyncio
import base64
import inspect
from typing import Callable

import click
import cloudpickle

from taskflows import logger
from taskflows.config import taskflows_data_dir


@click.command()
@click.argument("b64_pickle_func")
def _run_function(b64_pickle_func: str):
    func = cloudpickle.loads(base64.b64decode(b64_pickle_func))
    if inspect.iscoroutinefunction(func):
        asyncio.run(func())
    else:
        func()


def deserialize_and_call(func: Callable, name: str, attr: str) -> str:
    taskflows_data_dir.joinpath(f"{name}_{attr}.pickle").write_bytes(
        cloudpickle.dumps(func)
    )
    return f"_deserialize_and_call {name} {attr}"


@click.command()
@click.argument("name")
@click.argument("attr")
def _deserialize_and_call(name: str, attr: str):
    func = cloudpickle.loads(
        taskflows_data_dir.joinpath(f"{name}_{attr}.pickle").read_bytes()
    )
    if inspect.iscoroutinefunction(func):
        asyncio.run(func())
    else:
        func()


@click.command()
@click.argument("name")
def _run_docker_service(name: str):
    """Import Docker container and run it. (This is an installed function)"""
    path = taskflows_data_dir / f"{name}_docker_run_srv.pickle"
    logger.info("Loading service from %s", path)
    service = cloudpickle.loads(path.read_bytes())
    container = service.container
    logger.info("Running docker container %s", container.name)
    container.run()
