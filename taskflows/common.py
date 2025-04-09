import asyncio
import inspect
import signal
import sys
import traceback
from dataclasses import dataclass, field
from functools import cache
from pprint import pformat
from typing import Any, Callable, Dict, Optional

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from taskflows import logger


@cache
def get_shutdown_handler():
    """
    Return an instance of ShutdownHandler.

    This function is memoized.

    :return: An instance of ShutdownHandler.
    """
    return ShutdownHandler()

@cache
def get_http_client(default_timeout: int = 120):
    """
    Return an HTTPClient with the given default timeout.

    This function is memoized.

    :param default_timeout: The default timeout to use for all requests.
    :return: An HTTPClient instance.
    """
    return HTTPClient(default_timeout=default_timeout)

# TODO frozen?
@dataclass
class HTTPResponse:
    ok: bool = False
    content: Dict[str, Any] = field(default_factory=dict)
    status_code: int = -1
    headers: Dict[str, Any] = field(default_factory=dict)


class HTTPClient:
    def __init__(self, default_timeout: int):
        """
        Create a new HTTPClient instance.

        :param default_timeout: The default timeout to use for all requests.
        """
        self.session = ClientSession(timeout=ClientTimeout(total=default_timeout))

    async def get(self, url: str, **kwargs) -> HTTPResponse:
        """
        Make a GET request to the given URL.

        :param url: The URL to get.
        :param kwargs: Any additional keyword arguments will be passed to
            `ClientSession.request`.
        :return: An HTTPResponse object containing the result of the request.
        """
        return await self._request(url=url, method="GET", **kwargs)

    async def post(self, url: str, **kwargs) -> HTTPResponse:
        """
        Make a POST request to the given URL.

        :param url: The URL to post to.
        :param kwargs: Any additional keyword arguments will be passed to
            `ClientSession.request`.
        :return: An HTTPResponse object containing the result of the request.
        """
        return await self._request(url=url, method="POST", **kwargs)

    async def delete(self, url: str, **kwargs) -> HTTPResponse:
        """
        Make a DELETE request to the given URL.

        :param url: The URL to delete.
        :param kwargs: Any additional keyword arguments will be passed to
            `ClientSession.request`.
        :return: An HTTPResponse object containing the result of the request.
        """
        return await self._request(url=url, method="DELETE", **kwargs)

    async def close(self):
        """
        Close the HTTP client's session.

        This method should be called to properly close the session and release
        any resources associated with it.
        """
        await self.session.close()

    async def _request(
        self,
        url: str,
        method: str,
        retries: int = 1,
        on_retry: Optional[Callable] = None,
        **kwargs
    ):
        """
        Make a request to the given URL.

        This method will retry the request `retries` times if it fails. If an
        `on_retry` function is provided, it will be called after each failure.

        :param url: The URL to make the request to.
        :param method: The HTTP method to use.
        :param retries: The number of times to retry the request.
        :param on_retry: A function to call after each failure.
        :param kwargs: Any additional keyword arguments will be passed to
            `ClientSession.request`.
        :return: An HTTPResponse object containing the result of the request.
        """
        # get the parameters that were passed to the request
        params = kwargs.get("params", kwargs.get("data", kwargs.get("json")))
        # create a new HTTPResponse object to store the result of the request
        resp = HTTPResponse()
        try:
            # use the client session to make the request
            async with self.session.request(
                method=method, url=url, **kwargs
            ) as response:
                # store the status code of the response
                resp.status_code = response.status
                # if the status code is less than 400, the request was successful
                resp.ok = resp.status_code < 400
                # log the result of the request
                if resp.ok:
                    logger.info(
                        "[%i] %s(%s, %s))",
                        resp.status_code,
                        method,
                        url,
                        params,
                    )
                # store the headers of the response
                resp.headers = dict(response.headers)
                try:
                    # try to parse the response as json
                    resp.content = await response.json()
                except aiohttp.client_exceptions.ContentTypeError:
                    # if parsing as json fails, store the response text
                    text = await response.text()
                    if text:
                        resp.content["response"] = text
                # if the request was not successful, log the error
                if not resp.ok:
                    logger.error(
                        "[%i] %s(%s, %s)): %s",
                        resp.status_code,
                        method,
                        url,
                        params,
                        resp.content,
                    )
        except Exception as e:
            # if an exception occurs, log the error
            logger.exception("%s(%s, %s)): %s %s", method, url, params, type(e), e)
            # set the response status to False
            resp.ok = False
        # if the request was not successful and there are retries left, retry the request
        if not resp.ok and retries > 0:
            logger.warning("Retrying %s %s", method, url)
            # call the on retry function if it was provided
            if on_retry:
                if asyncio.iscoroutinefunction(on_retry):
                    await on_retry()
                else:
                    on_retry()
            # recursively call the _request method with the updated number of retries
            return await self._request(
                url=url, method=method, retries=retries - 1, **kwargs
            )
        # return the response
        return resp
    
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
