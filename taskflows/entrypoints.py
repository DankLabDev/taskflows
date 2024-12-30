import asyncio
import inspect
import signal
import sys
import traceback
from functools import cache, wraps
from pprint import pformat
from typing import Any, Optional

from dynamic_imports import import_module_attr

from taskflows import logger


def async_command(blocking: bool = False):
    def decorator(f):
        loop = asyncio.get_event_loop()
        sdh = get_shutdown_handler()

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


class LazyCLI:
    def __init__(self):
        self.cli = None
        self.command = {}

    def add_sub_cli(self, name: str, cli_module: str, cli_variable: str):
        self.command[name] = lambda: import_module_attr(cli_module, cli_variable)

    def run(self):
        if len(sys.argv) > 1 and (cmd_name := sys.argv[1]) in self.commands:
            # construct sub-command only as needed.
            self.cli.add_command(self.commands[cmd_name](), name=cmd_name)
        else:
            # For user can list all sub-commands.
            for cmd_name, cmd_importer in self.commands.items():
                self.cli.add_command(cmd_importer(), name=cmd_name)
        self.cli()
        

class ShutdownHandler:
    def __init__(self, loop: Optional[Any] = None):
        self.loop = loop or asyncio.get_event_loop()
        self.callbacks = []
        self.exit_code = None
        self._shutdown_task = None

        self.loop.set_exception_handler(self._loop_exception_handle)
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.loop.add_signal_handler(
                s,
                lambda s=s: self.loop.create_task(self._on_signal_interrupt(s)),
            )

    def add_callback(self, cb):
        if not inspect.iscoroutinefunction(cb):
            raise ValueError("Callback must be coroutine function")
        self.callbacks.append(cb)

    async def shutdown(self, exit_code: int):
        if self._shutdown_task is None:
            self._create_shutdown_task(exit_code)
        return await self._shutdown_task

    def _loop_exception_handle(self, loop, context):
        logger.error("Uncaught coroutine exception: %s", pformat(context))
        # Log the context information
        logger.error("Uncaught coroutine exception: %s", pformat(context))

        # Extract the exception object from the context
        exception = context.get("exception")
        if exception:
            # Log the exception traceback
            tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
            logger.error("Exception traceback:\n%s", tb)
        else:
            # Log the message if no exception is provided
            message = context.get("message", "No exception object found in context")
            logger.error("Error message: %s", message)
        if self._shutdown_task is None:
            self._create_shutdown_task(1)

    async def _on_signal_interrupt(self, signum, frame=None):
        signame = signal.Signals(signum).name if signum is not None else "Unknown"
        logger.warning("Caught signal %i (%s). Shutting down.", signum, signame)
        await self.shutdown(0)

    def _create_shutdown_task(self, exit_code: int):
        self._shutdown_task = self.loop.create_task(self._shutdown(exit_code))

    async def _close_pg_pool_conn(self):
        pool_conn = await cached_sa_conn()
        await pool_conn.close()

    async def _shutdown(self, exit_code: int):
        logger.info("Shutting down (exit code: %i)", exit_code)
        for cb in self.callbacks + [self._close_pg_pool_conn]:
            logger.info("Calling shutdown callback: %s", cb)
            try:
                await asyncio.wait_for(cb(), timeout=5)
            except Exception as err:
                logger.error("%s error in shutdown callback %s: %s", type(err), cb, err)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        logger.info("Cancelling %i outstanding tasks", len(tasks))
        for task in tasks:
            task.cancel()
        logger.info("Cancelled %i outstanding tasks", len(tasks))
        self.exit_code = exit_code
        self.loop.stop()
        logger.info("Shutdown complete (exit code: %i)", exit_code)


@cache
def get_shutdown_handler(loop=None):
    return ShutdownHandler(loop=loop)
