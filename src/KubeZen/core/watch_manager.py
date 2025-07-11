"""Watch multiple K8s event streams without threads."""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Literal, Type
import asyncio
from types import SimpleNamespace
import logging
import re
import orjson as json

from kubernetes_asyncio import watch
from kubernetes_asyncio.client.exceptions import ApiException

from textual.signal import Signal

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..models.base import UIRow

log = logging.getLogger(__name__)


class WatchManagerSignal:
    def __init__(self, app: KubeZenTuiApp, model_class: Type[UIRow]):
        kind: str = model_class.kind.lower()
        self._resource_added: Signal[dict[str, UIRow]] = Signal(
            app,f"resource_added_{kind}"
        )
        self._resource_modified: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_modified_{kind}"
        )
        self._resource_deleted: Signal[dict[str, UIRow]] = Signal(
            app, f"resource_deleted_{kind}"
        )

    def __del__(self):
        log.debug(f"Deleting watch manager signal")
        log.debug({self._resource_added})

    @property
    def resource_added(self) -> Signal[dict[str, UIRow]]:
        return self._resource_added

    @property
    def resource_modified(self) -> Signal[dict[str, UIRow]]:
        return self._resource_modified

    @property
    def resource_deleted(self) -> Signal[dict[str, UIRow]]:
        return self._resource_deleted


class WatchManager:
    def __init__(
        self, app: "KubeZenTuiApp", model_class: type[UIRow]
    ):
        self._model_class = model_class
        self._api_client = app.kubernetes_client
        self._namespaces: list[str] | None = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._signals = WatchManagerSignal(app, model_class)
        self._current_update: asyncio.Future[list[UIRow]] | None = None

    @property
    def namespaces(self) -> list[str] | Literal["all"]:
        """Getter for the current list of namespaces."""
        return self._namespaces

    @namespaces.setter
    def namespaces(self, new_namespaces: list[str]) -> None:
        """
        Intelligently updates watches based on the difference between the old
        and new list of namespaces.
        """
        new_set = set(new_namespaces)
        old_set = set(self._namespaces)

        if old_set == new_set:
            # No change needed, set an empty result
            self._current_update = asyncio.Future()
            self._current_update.set_result([])
            return

        # First stop all existing watches if switching between "all" and specific namespaces
        if ("all" in new_set) != ("all" in old_set):
            for task in self._tasks.values():
                task.cancel()
            self._tasks.clear()
        else:
            # Otherwise, stop watches for removed namespaces
            for ns in (old_set - new_set):
                if task := self._tasks.pop(ns, None):
                    task.cancel()

        self._namespaces = new_namespaces

        # Start new watches and get initial items
        if "all" in new_namespaces:
            # Special case: watching all namespaces
            async def _watch_all():
                items, rv = await self._get_initial_list_for("all")
                self._tasks["all"] = asyncio.create_task(self._run_watch_for("all", rv))
                return items
            self._current_update = asyncio.create_task(_watch_all())
        else:
            # Watch specific namespaces
            async def _watch_namespaces():
                # Get items for all specified namespaces, not just new ones
                all_items = []
                for namespace in new_namespaces:
                    items, rv = await self._get_initial_list_for(namespace)
                    all_items.extend(items)
                    # Only start a new watch if we don't already have one
                    if namespace not in self._tasks:
                        self._tasks[ns] = asyncio.create_task(self._run_watch_for(namespace, rv))
                return all_items
            self._current_update = asyncio.create_task(_watch_namespaces())

    @property
    def current_update(self) -> asyncio.Future[list[UIRow]] | None:
        """Get the Future for the current namespace update operation."""
        if self._current_update and self._current_update.done():
            # Clear the update once it's been completed
            self._current_update = None
        return self._current_update

    async def stop(self) -> None:
        """Stops all running watch tasks gracefully."""
        if not self._tasks:
            return
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

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

    async def _get_initial_list_for(self, namespace: str) -> tuple[list[UIRow], str]:
        """Performs a LIST and returns resources and resource_version for a namespace."""
        list_call, list_kwargs = self._get_api_call_info(namespace)
        response = await list_call(**list_kwargs)

        # Handle the different response structures for standard vs. custom resources
        if self._model_class.api_info.client_name == "CustomObjectsApi":
            # For CRDs, the response is a dictionary. The items are also dictionaries.
            # We convert them to SimpleNamespace to allow dot-notation access in the UIRow models.
            items = []
            for item in response.get("items", []):
                items.append(self._model_class(raw=item))
            resource_version = response.get("metadata", {}).get("resourceVersion", "")
        else:
            # For standard resources, the response is a model object (e.g., V1PodList)
            items = [self._model_class(raw=item) for item in response.items]
            resource_version = response.metadata.resource_version

        return items, resource_version

    async def _run_watch_for(self, namespace: str, resource_version: str) -> None:
        """The core watch loop for a specific namespace or all namespaces."""
        current_rv = resource_version

        # This outer loop ensures the watch is persistent and reconnects on errors or timeouts.
        while True:
            response = None
            try:
                watch_call, watch_kwargs = self._get_api_call_info(namespace)
                watch_kwargs["resource_version"] = current_rv
                watch_kwargs["allow_watch_bookmarks"] = True
                watch_kwargs["_preload_content"] = False
                watch_kwargs["watch"] = True
                watch_kwargs["timeout_seconds"] = 240  # A reasonable timeout to ensure reconnections

                # The response type for deserialization, e.g. "V1Pod"
                version = self._model_class.api_info.version.capitalize()
                kind = self._model_class.kind
                response_type = f"{version}{kind}"

                log.info(
                    "Starting watch for %s in namespace '%s' from RV: %s",
                    self._model_class.kind,
                    namespace,
                    current_rv,
                )

                # Use the underlying API call to get the raw response
                response = await watch_call(**watch_kwargs)

                while True:
                    try:
                        line = await response.content.readline()
                        if not line:
                            log.info(
                                "Watch connection closed by server for %s in ns '%s'. Reconnecting from RV: %s",
                                self._model_class.kind,
                                namespace,
                                current_rv,
                            )
                            break  # End of inner stream-reading loop to reconnect
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log.warning(
                            "Error reading from watch stream for %s in ns '%s': %s. Reconnecting.",
                            self._model_class.kind,
                            namespace,
                            e,
                        )
                        break

                    event = json.loads(line)

                    if event["type"] == "BOOKMARK":
                        current_rv = event["object"]["metadata"]["resourceVersion"]
                        log.info(
                            "BOOKMARK event for %s in NS '%s', updating RV to %s",
                            self._model_class.kind,
                            namespace,
                            current_rv,
                        )
                        continue

                    # The deserialize method expects a response-like object with a `data` attribute
                    data_to_deserialize = SimpleNamespace(
                        data=json.dumps(event["object"])
                    )
                    deserialized_object = self._api_client.client.deserialize(
                        data_to_deserialize, response_type
                    )
                    model_instance = self._model_class(raw=deserialized_object)

                    log.info(
                        "Watch received event: %s for %s '%s' in NS '%s'",
                        event["type"],
                        self._model_class.kind,
                        model_instance.name,
                        namespace,
                    )
                    event_data = {"resource": model_instance}
                    if event["type"] == "ADDED":
                        self._signals.resource_added.publish(event_data)
                    elif event["type"] == "MODIFIED":
                        self._signals.resource_modified.publish(event_data)
                    elif event["type"] == "DELETED":
                        self._signals.resource_deleted.publish(event_data)

            except asyncio.CancelledError:
                log.info(
                    "Watch permanently cancelled for %s in namespace '%s'.",
                    self._model_class.kind,
                    namespace,
                )
                break  # Exit the outer persistence loop

            except ApiException as e:
                if e.status == 410:
                    log.warning(
                        "Resource version %s for %s in ns '%s' is too old. Re-listing to get a fresh start.",
                        current_rv,
                        self._model_class.kind,
                        namespace,
                    )
                    try:
                        # Re-list to get the latest state and a new, valid resource version
                        _items, new_rv = await self._get_initial_list_for(namespace)
                        current_rv = new_rv
                        log.info(
                            "Successfully re-listed. Restarting watch for %s in ns '%s' from new RV: %s",
                            self._model_class.kind,
                            namespace,
                            new_rv,
                        )
                    except Exception as exc:
                        log.exception(
                            "Failed to re-list after 410 error for %s in ns '%s'. Retrying in 5 seconds. Error: %s",
                            self._model_class.kind,
                            namespace,
                            exc,
                        )
                        await asyncio.sleep(5)
                else:
                    log.exception(
                        "API error in watch loop for %s in namespace '%s'. Reconnecting in 5 seconds.",
                        self._model_class.kind,
                        namespace,
                    )
                    await asyncio.sleep(5)
            finally:
                # Ensure the response is closed before the next reconnection attempt
                if response:
                    try:
                        response.close()
                    except Exception as e:
                        log.debug(
                            "Error closing response stream, may already be closed: %s", e
                        )

    @property
    def signals(self) -> WatchManagerSignal:
        return self._signals

    def __del__(self) -> None:
        log.info(
            "WatchManager for %s has been garbage collected.",
            self._model_class.plural,
        )
