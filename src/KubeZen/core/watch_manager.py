"""Watch multiple K8s event streams without threads."""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Type, Generator
import asyncio
import socket
import logging

from kubernetes_asyncio import watch
from kubernetes_asyncio.client.exceptions import ApiException
from textual.signal import Signal

from aiohttp import (
    ClientConnectorError,
    ClientOSError,
    ServerDisconnectedError,
    ClientPayloadError,
)

if TYPE_CHECKING:
    from ..app import KubeZen
    from ..models.base import UIRow

log = logging.getLogger(__name__)


class WatchManagerSignal:
    def __init__(self, app: KubeZen, model_class: Type[UIRow]):
        kind: str = model_class.kind.lower()
        self._resource_added: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_added_{kind}"
        )
        self._resource_modified: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_modified_{kind}"
        )
        self._resource_deleted: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_deleted_{kind}"
        )
        self._resource_full_reset: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_full_reset_{kind}"
        )

    def __del__(self):
        log.debug("Deleting watch manager signal")

    @property
    def resource_added(self) -> Signal[dict[str, UIRow]]:
        return self._resource_added

    @property
    def resource_modified(self) -> Signal[dict[str, UIRow]]:
        return self._resource_modified

    @property
    def resource_deleted(self) -> Signal[dict[str, UIRow]]:
        return self._resource_deleted

    @property
    def resource_full_reset(self) -> Signal[list[UIRow]]:
        return self._resource_full_reset


class WatchManager:
    def __init__(self, app: "KubeZen", model_class: type[UIRow]):
        self._model_class = model_class
        self._api_client = app.kubernetes_client
        self._tasks: dict[str, asyncio.Task] = {}
        self._signals = WatchManagerSignal(app, model_class)

    async def stop(self) -> None:
        """Stops all running watch tasks gracefully."""
        if not self._tasks:
            return
        tasks = set(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def stop_namespace_watch(self, namespace: str) -> None:
        """Stops the watch task for a specific namespace."""
        if namespace in self._tasks:
            task = self._tasks.pop(namespace)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    log.debug(
                        "Successfully cancelled watch for namespace '%s'.", namespace
                    )

    @property
    def watching(self) -> set[str]:
        """Returns a list of namespaces currently being watched."""
        return set(self._tasks.keys())

    def _get_api_call_info(self, namespace: str) -> tuple[Callable, dict]:
        """
        Determines the correct API method and keyword arguments based on the
        provided namespace ("all" or a specific name).
        """
        return self._api_client.get_api_method_for_resource(
            model_class=self._model_class,
            action="list",
            namespace=namespace,
        )

    async def get_initial_list(
        self, namespace: str
    ) -> tuple[Generator[UIRow, None, None], str]:
        """
        Performs a LIST and returns a generator for the resources and the
        resource_version for a namespace.
        """
        list_call, list_kwargs = self._get_api_call_info(namespace)
        try:
            response = await list_call(**list_kwargs)
        except (ApiException, ClientConnectorError) as e:
            log.error(f"Error getting initial list for {namespace}: {e}")
            raise

        # Determine the items list and resource version based on response type
        if self._model_class.api_info.client_name == "CustomObjectsApi":
            items_list = response.get("items", [])
            resource_version = response.get("metadata", {}).get("resourceVersion", "")
        else:
            items_list = response.items
            resource_version = response.metadata.resource_version

        def resource_generator() -> Generator[UIRow, None, None]:
            """A generator that yields model instances one by one."""
            for item in items_list:
                yield self._model_class(raw=item)

        return resource_generator(), resource_version

    async def create_watch_task(self, namespace: str, resource_version: str) -> None:
        """Creates a watch task for a specific namespace and resource version."""
        if namespace in self._tasks and not self._tasks[namespace].done():
            log.info("Replacing existing watch task for namespace '%s'", namespace)
            self._tasks[namespace].cancel()
            try:
                await self._tasks[namespace]
            except asyncio.CancelledError:
                log.debug("Successfully cancelled existing watch for '%s'.", namespace)

        log.info(
            "Creating new watch task for namespace '%s' at RV %s",
            namespace,
            resource_version,
        )
        self._tasks[namespace] = asyncio.create_task(
            self._start_watch(namespace, resource_version)
        )

    async def _start_watch(self, namespace: str, resource_version: str) -> None:
        """The core watch loop using the high-level Watch class, with per-event timeout."""
        current_rv = resource_version

        while True:
            try:
                list_call, list_kwargs = self._get_api_call_info(namespace)
                list_kwargs["resource_version"] = current_rv
                list_kwargs["allow_watch_bookmarks"] = True
                list_kwargs["timeout_seconds"] = 240

                log.info(
                    "Starting watch for %s in namespace '%s' from RV: %s",
                    self._model_class.plural,
                    namespace,
                    current_rv,
                )

                watch_handler = watch.Watch()
                async with watch_handler.stream(list_call, **list_kwargs) as stream:
                    while True:
                        try:
                            event = await asyncio.wait_for(
                                stream.__anext__(), timeout=65
                            )
                        except asyncio.TimeoutError:
                            log.warning(
                                "Watch timed out due to inactivity (possible network loss). Reconnecting..."
                            )
                            break  # Exit inner loop to reconnect
                        except StopAsyncIteration:
                            log.info("Watch stream closed by API server after timeout_seconds.")
                            break

                        if watch_handler.resource_version:
                            current_rv = watch_handler.resource_version

                        event_type = event["type"]
                        k8s_object = event["object"]

                        if event_type == "BOOKMARK":
                            log.debug(
                                "Received BOOKMARK, updating resource_version to %s",
                                current_rv,
                            )
                            continue

                        model_instance = self._model_class(raw=k8s_object)
                        event_data = {"resource": model_instance}

                        if event_type == "ADDED":
                            self._signals.resource_added.publish(event_data)
                        elif event_type == "MODIFIED":
                            self._signals.resource_modified.publish(event_data)
                        elif event_type == "DELETED":
                            self._signals.resource_deleted.publish(event_data)

            except ApiException as e:
                if e.status == 410:
                    log.warning(
                        "Watch RV %s for %s in ns '%s' is too old. Re-listing.",
                        current_rv,
                        self._model_class.kind,
                        namespace,
                    )
                    try:
                        _items, new_rv = await self.get_initial_list(namespace)
                        current_rv = new_rv
                        log.info(
                            "Re-listed. Restarting watch for %s in ns '%s' from RV: %s",
                            self._model_class.kind,
                            namespace,
                            new_rv,
                        )
                        self._signals.resource_full_reset.publish(_items)
                        continue
                    except Exception as relist_exc:
                        log.exception(
                            "Failed to re-list after 410. Retrying in 15s.",
                            exc_info=relist_exc,
                        )
                        await asyncio.sleep(15)
                        continue
                else:
                    log.exception(
                        "API error in watch loop for %s, retrying in 15s.",
                        self._model_class.kind,
                        exc_info=e,
                    )
                    await asyncio.sleep(15)
                    continue
            except asyncio.CancelledError:
                # Task was cancelled, exit cleanly
                log.debug("Watch task for %s in ns '%s' was cancelled", self._model_class.kind, namespace)
                break
            except (
                ClientConnectorError,
                ClientOSError,
                ServerDisconnectedError,
                ClientPayloadError,
                socket.gaierror,
                OSError,
            ) as net_exc:
                log.warning(
                    "Client-side network error: %s — reconnecting in 10s.", net_exc
                )
                await asyncio.sleep(10)
                continue

    @property
    def signals(self) -> WatchManagerSignal:
        return self._signals

    def __del__(self) -> None:
        log.info(
            "WatchManager for %s has been garbage collected.",
            self._model_class.plural,
        )
