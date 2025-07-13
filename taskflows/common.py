import asyncio
import inspect
import signal
import sys
import traceback
from functools import cache
from pprint import pformat
from typing import Any, Callable, Dict, List
from textdistance import lcsseq

from taskflows import logger
from taskflows import _SYSTEMD_FILE_PREFIX

def sort_service_names(services: List[str]) -> List[str]:
    """
    Sort service names to display in a list.

    This function takes a list of service names and sorts them intelligently,
    grouping stop services with their corresponding main services. The sorting
    uses text similarity to order related services together.

    Args:
        services (List[str]): A list of service names to sort.

    Returns:
        List[str]: A sorted list where stop services appear immediately after
                  their corresponding main services, ordered by similarity.

    The sorting algorithm:
    1. Separates services into stop services (prefixed with "stop-{prefix}") and regular services
    2. Normalizes service names by replacing hyphens and underscores with spaces
    3. Orders services by text similarity using longest common subsequence
    4. Places stop services immediately after their corresponding main services
    """
    # Define the prefix used for stopped services
    stop_prefix = f"stop-{_SYSTEMD_FILE_PREFIX}"
    
    # Separate services into two categories: those that start with the stop prefix and those that do not
    stop_services, non_stop_services = [], []
    for srv in services:
        if srv.startswith(stop_prefix):
            stop_services.append(srv)
        else:
            non_stop_services.append(srv)

    # Normalize non-stop service names by replacing hyphens and underscores with spaces for similarity comparison
    non_stop_services = [
        (s, s.replace("-", " ").replace("_", " ")) for s in non_stop_services
    ]
    
    # Start the ordering process with the first non-stop service
    srv, filt_srv = non_stop_services.pop(0)
    ordered = [srv]
    
    # Continue ordering the remaining non-stop services
    while non_stop_services:
        # Find the service with the greatest similarity to the current service
        best = max(non_stop_services, key=lambda o: lcsseq.similarity(filt_srv, o[1]))
        
        # Update the current service and filtered service to the best match found
        srv, filt_srv = best
        
        # Remove the matched service from the list and append it to the ordered list
        non_stop_services.remove(best)
        ordered.append(srv)
        
        # Check if the corresponding stop service exists and append it if found
        if (stp_srv := f"{stop_prefix}{srv}") in stop_services:
            ordered.append(stp_srv)
    
    # Return the fully ordered list of services
    return ordered


@cache
def get_shutdown_handler():
    """
    Return an instance of ShutdownHandler.

    This function is memoized.

    :return: An instance of ShutdownHandler.
    """
    return ShutdownHandler()


class ShutdownHandler:
    def __init__(self, shutdown_on_exception: bool = False):
        """
        Initialize the ShutdownHandler.

        Sets up the event loop and signal handlers for managing graceful
        shutdowns in response to specific signals or exceptions.

        Args:
            shutdown_on_exception (bool): If True, initiate shutdown on
                uncaught exceptions. Defaults to False.
        """
        self.shutdown_on_exception = shutdown_on_exception
        self.loop = asyncio.get_event_loop_policy().get_event_loop()
        self.callbacks = []
        self._shutdown_task = None
        self.loop.set_exception_handler(self._loop_exception_handle)
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.loop.add_signal_handler(
                s,
                lambda s=s: self.loop.create_task(self._on_signal_interrupt(s)),
            )

    def add_callback(self, cb: Callable[[], None]):
        """
        Registers a coroutine function to be called on shutdown.

        The function takes no arguments and returns nothing. It is called in
        the event loop thread.

        Raises:
            ValueError: if the callback is not a coroutine function
        """
        if not inspect.iscoroutinefunction(cb):
            raise ValueError("Callback must be coroutine function")
        self.callbacks.append(cb)

    async def shutdown(self, exit_code: int):
        """
        Initiate shutdown of the event loop.

        Starts the shutdown process by scheduling the :meth:`_shutdown` task
        with the given `exit_code`. If the shutdown task is already running,
        this method simply returns the existing task.

        Args:
            exit_code (int): The code to exit with when shutting down.

        Returns:
            The shutdown task.
        """
        if self._shutdown_task is None:
            self._create_shutdown_task(exit_code)
        return await self._shutdown_task

    def _loop_exception_handle(self, loop: Any, context: Dict[str, Any]):
        """
        Exception handler for the event loop.

        This function is called when an uncaught exception is raised in a
        coroutine. It logs the exception and its traceback, and if
        `shutdown_on_exception` is True, it initiates shutdown by calling
        `self._create_shutdown_task(1)`.

        :param loop: The event loop.
        :param context: A dictionary containing information about the
            exception.
        """
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

        if self.shutdown_on_exception and (self._shutdown_task is None):
            self._create_shutdown_task(1)

    async def _on_signal_interrupt(self, signum: int):
        """
        Handle a signal interrupt.

        This function is called when a signal interrupt is received. It logs a
        message indicating the signal that was received and shuts down the event
        loop.

        Args:
            signum (int): The signal number that was received.
        """
        signame = signal.Signals(signum).name if signum is not None else "Unknown"
        logger.warning("Caught signal %i (%s). Shutting down.", signum, signame)
        await self.shutdown(0)

    def _create_shutdown_task(self, exit_code: int):
        """
        Create and schedule the shutdown task.

        This function creates and schedules a shutdown task by calling
        `self._shutdown(exit_code)` with the given `exit_code` argument. The
        task is scheduled to run in the event loop.

        Args:
            exit_code (int): The exit code to use when shutting down.

        Returns:
            None
        """
        self._shutdown_task = self.loop.create_task(self._shutdown(exit_code))

    async def _shutdown(self, exit_code: int):
        """
        Perform the shutdown procedure.

        This method executes the shutdown process in the following steps:

        1. Execute all registered shutdown callbacks.
        2. Cancel all outstanding tasks in the event loop.
        3. Stop the event loop.
        4. Exit the program with the specified exit code.

        Args:
            exit_code (int): The exit code to use when terminating the program.
        """
        logger.info("Shutting down.")
        # Execute all registered shutdown callbacks
        for cb in self.callbacks:
            logger.info("Calling shutdown callback: %s", cb)
            try:
                # Wait up to 5 seconds for each callback to complete
                await asyncio.wait_for(cb(), timeout=5)
            except Exception as err:
                # Log any exceptions that occur in the callbacks
                logger.exception(
                    "%s error in shutdown callback %s: %s",
                    type(err),
                    cb,
                    err,
                )
        # Cancel all outstanding tasks in the event loop
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        logger.info("Cancelling %i outstanding tasks", len(tasks))
        for task in tasks:
            # Cancel the task to prevent it from running after we've stopped
            # the event loop
            task.cancel()
        # Stop the event loop to prevent any new tasks from being scheduled
        self.loop.stop()
        # Exit the program with the specified exit code
        logger.info("Exiting %s", exit_code)
        sys.exit(exit_code)
