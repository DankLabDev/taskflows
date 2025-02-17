import asyncio
import inspect
import signal
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
    return ShutdownHandler()

@cache
def get_http_client(default_timeout: int = 120):
    return HTTPClient(default_timeout=default_timeout)

@dataclass
class HTTPResponse:
    ok: bool = False
    content: Dict[str, Any] = field(default_factory=dict)
    status_code: int = -1
    headers: Dict[str, Any] = field(default_factory=dict)


class HTTPClient:
    def __init__(self, default_timeout: int):
        self.session = ClientSession(timeout=ClientTimeout(total=default_timeout))

    async def get(self, url: str, **kwargs) -> HTTPResponse:
        return await self._request(url=url, method="GET", **kwargs)

    async def post(self, url: str, **kwargs) -> HTTPResponse:
        return await self._request(url=url, method="POST", **kwargs)

    async def delete(self, url: str, **kwargs) -> HTTPResponse:
        return await self._request(url=url, method="DELETE", **kwargs)

    async def close(self):
        await self.session.close()

    async def _request(
        self,
        url: str,
        method: str,
        retries: int = 1,
        on_retry: Optional[Callable] = None,
        **kwargs
    ):
        params = kwargs.get("params", kwargs.get("data", kwargs.get("json")))
        resp = HTTPResponse()
        try:
            async with self.session.request(
                method=method, url=url, **kwargs
            ) as response:
                resp.status_code = response.status
                resp.ok = resp.status_code < 400
                if resp.ok:
                    logger.info(
                        "[%i] %s(%s, %s))",
                        resp.status_code,
                        method,
                        url,
                        params,
                    )
                resp.headers = dict(response.headers)
                try:
                    resp.content = await response.json()
                except aiohttp.client_exceptions.ContentTypeError:
                    text = await response.text()
                    if text:
                        resp.content["response"] = text
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
            logger.exception("%s(%s, %s)): %s %s", method, url, params, type(e), e)
            resp.ok = False
        if not resp.ok and retries > 0:
            logger.warning("Retrying %s %s", method, url)
            # set latest access token, as that might have created the need for retry.
            if on_retry:
                if asyncio.iscoroutinefunction(on_retry):
                    await on_retry()
                else:
                    on_retry()
            return await self._request(
                url=url, method=method, retries=retries - 1, **kwargs
            )
        return resp
    
class ShutdownHandler:
    def __init__(self, shutdown_on_exception: bool = False):
        self.shutdown_on_exception = shutdown_on_exception
        self.loop = asyncio.get_event_loop()
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

        if self.shutdown_on_exception and (self._shutdown_task is None):
            self._create_shutdown_task(1)

    async def _on_signal_interrupt(self, signum, frame=None):
        signame = signal.Signals(signum).name if signum is not None else "Unknown"
        logger.warning("Caught signal %i (%s). Shutting down.", signum, signame)
        await self.shutdown(0)

    def _create_shutdown_task(self, exit_code: int):
        self._shutdown_task = self.loop.create_task(self._shutdown(exit_code))

    async def _shutdown(self, exit_code: int):
        logger.info("Shutting down (exit code: %i)", exit_code)
        for cb in self.callbacks:
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
