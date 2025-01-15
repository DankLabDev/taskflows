import asyncio
import sys
from functools import wraps

from click import Group
from dynamic_imports import import_module_attr

from taskflows import logger
from taskflows.common import get_shutdown_handler


def async_command(blocking: bool = False, shutdown_on_exception: bool = True):
    def decorator(f):
        loop = asyncio.get_event_loop()
        sdh = get_shutdown_handler()
        sdh.shutdown_on_exception = shutdown_on_exception

        async def async_command_async(*args, **kwargs):
            logger.info("Running main task: %s", f)
            try:
                await f(*args, **kwargs)
                if blocking:
                    await sdh.shutdown(0)
            except Exception as err:
                logger.exception("Error running main task: %s", err)
                await sdh.shutdown(1)

        @wraps(f)
        def wrapper(*args, **kwargs):
            task = loop.create_task(async_command_async(*args, **kwargs))
            try:
                if blocking:
                    loop.run_until_complete(task)

                else:
                    loop.run_forever()
            finally:
                logger.info("Closing event loop")
                loop.close()
                logger.info("Exiting (%i)", sdh.exit_code)
                sys.exit(sdh.exit_code)

        return wrapper

    return decorator


class CLIGroup:
    """Combine and optionaly lazy load multiple click CLIs."""
    def __init__(self):
        self.cli = Group()
        self.commands = {}

    def add_sub_cli(self, cli: Group):
        self.cli.add_command(cli)

    def add_lazy_sub_cli(self, name: str, cli_module: str, cli_variable: str):
        self.commands[name] = lambda: import_module_attr(cli_module, cli_variable)

    def run(self):
        if len(sys.argv) > 1 and (cmd_name := sys.argv[1]) in self.commands:
            # construct sub-command only as needed.
            self.cli.add_command(self.commands[cmd_name](), name=cmd_name)
        else:
            # For user can list all sub-commands.
            for cmd_name, cmd_importer in self.commands.items():
                self.cli.add_command(cmd_importer(), name=cmd_name)
        self.cli()
        

