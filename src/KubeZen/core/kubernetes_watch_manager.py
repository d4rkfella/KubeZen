from __future__ import annotations
import asyncio
import logging
import random
from typing import (
    List,
    Dict,
    Any,
    Optional,
    Callable,
    Coroutine,
)

from kubernetes_asyncio.watch import Watch
from kubernetes_asyncio.client.exceptions import ApiException as K8sApiException

from .watched_resource_store import WatchedResourceStore
from .kubernetes_client import KubernetesClient
from .resource_registry import RESOURCE_REGISTRY


class KubernetesWatchManager:
    """Manages Kubernetes resource watches, updates a local store, and provides
    access to this watched data.
    """

    def __init__(
        self, kubernetes_client: KubernetesClient, store: WatchedResourceStore
    ):
        self.logger = logging.getLogger(__name__)
        self.kubernetes_client = kubernetes_client
        self.watched_resource_store = store
        self._watch_tasks: List[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        self.retry_delay_seconds = 5  # Simple config

    def _get_api_watch_methods(
        self, resource_kind_plural: str, namespace: str | None = None
    ) -> tuple[Callable[..., Coroutine[Any, Any, Any]], bool] | None:
        config_entry = RESOURCE_REGISTRY.get(resource_kind_plural)
        if not isinstance(config_entry, dict):
            self.logger.error("No watch config for '%s'", resource_kind_plural)
            return None

        api_client_attr_name = config_entry.get("api_client_attr")
        if not isinstance(api_client_attr_name, str):
            self.logger.error(
                "Invalid api_client_attr in config for '%s'", resource_kind_plural
            )
            return None
        api_client_instance = getattr(
            self.kubernetes_client, api_client_attr_name, None
        )
        if not api_client_instance:
            self.logger.error(
                "API client '%s' not found on KubernetesClient", api_client_attr_name
            )
            return None

        is_namespaced = config_entry.get("is_namespaced", True)
        is_specific_ns = is_namespaced and namespace is not None

        method_name_key = (
            "list_namespaced_method" if is_specific_ns else "list_all_method"
        )
        method_name = config_entry.get(method_name_key)
        if not isinstance(method_name, str):
            self.logger.error(
                "No list method found for '%s' (namespaced=%s)",
                resource_kind_plural,
                is_specific_ns,
            )
            return None

        api_call_function = getattr(api_client_instance, method_name, None)
        if not callable(api_call_function):
            self.logger.error(
                "Method '%s' not found or not callable on API client '%s'",
                method_name,
                api_client_attr_name,
            )
            return None

        return api_call_function, is_specific_ns

    async def get_and_store_initial_list(
        self, resource_kind_plural: str, namespace: str | None
    ) -> str | None:
        resource_config = RESOURCE_REGISTRY.get(resource_kind_plural)
        if not isinstance(resource_config, dict):
            self.logger.error("Unsupported resource: %s", resource_kind_plural)
            return None

        is_namespaced_resource = resource_config.get("is_namespaced", True)
        effective_namespace = namespace if is_namespaced_resource else "cluster-scoped"
        if not is_namespaced_resource and namespace:
            self.logger.warning(
                "Namespace '%s' ignored for cluster-scoped resource '%s'",
                namespace,
                resource_kind_plural,
            )

        api_methods = self._get_api_watch_methods(
            resource_kind_plural, namespace=namespace
        )
        if not api_methods:
            return None
        api_watch_func, is_specific_ns = api_methods

        list_kwargs: Dict[str, Any] = {"watch": False}
        if is_specific_ns:
            list_kwargs["namespace"] = namespace

        try:
            # Perform the slow network call *before* acquiring any locks.
            list_response = await api_watch_func(**list_kwargs)
            resource_version = getattr(list_response.metadata, "resource_version", None)

            if not resource_version:
                self.logger.error(
                    "Could not get resource_version from list response for %s",
                    resource_kind_plural,
                )
                return None

            if self.kubernetes_client.api_client is None:
                self.logger.error(
                    "API client is not initialized, cannot sanitize objects."
                )
                return None

            items = [
                self.kubernetes_client.api_client.sanitize_for_serialization(item)
                for item in getattr(list_response, "items", [])
            ]

            # Now, acquire the lock only for the brief moment we are writing data.
            await self.watched_resource_store.replace_list(
                resource_kind_plural,
                effective_namespace or "all-namespaces",
                items,
                resource_version,
            )
            self.logger.info(
                "Stored %s %s from '%s'",
                len(items),
                resource_kind_plural,
                effective_namespace or "all",
            )
            return str(resource_version)

        except K8sApiException as e:
            self.logger.error(
                "API error listing %s: %s - %s",
                resource_kind_plural,
                e.status,
                e.reason,
            )
            return None
        except Exception as e:
            self.logger.error(
                "Unexpected error listing %s: %s",
                resource_kind_plural,
                e,
                exc_info=True,
            )
            return None

    async def _process_watch_event(
        self, watch_id: str, resource_kind_plural: str, event: Dict[str, Any]
    ) -> Optional[str]:
        event_type = event.get("type")
        # With return_type=object in Watch constructor, 'object' should already be the dict.
        # Prioritize 'object' if available, otherwise fall back to 'raw_object'.
        raw_object = event.get("object", event.get("raw_object"))

        if event_type == "ERROR":
            self.logger.error(
                "[%s] Watch stream received an ERROR event: %s",
                watch_id,
                event
            )
            return None

        if raw_object is None:
            self.logger.error(
                "[%s] Event has a null 'object' or 'raw_object'. Event: %s",
                watch_id,
                event,
            )
            return None

        sanitized_object = None
        try:
            if self.kubernetes_client.api_client is None:
                self.logger.error(
                    "API client is not initialized, cannot sanitize event object."
                )
                return None
            sanitized_object = (
                self.kubernetes_client.api_client.sanitize_for_serialization(raw_object)
            )
        except ValueError as e:
            self.logger.warning(
                "[%s] Deserialization (ValueError) for %s object in event type %s: %s. "
                "Skipping this event.",
                watch_id,
                resource_kind_plural,
                event_type,
                e,
            )
            return None
        except Exception as e:
            self.logger.error(
                "[%s] Unexpected error during object sanitization for %s event type %s: %s",
                watch_id,
                resource_kind_plural,
                event_type,
                e,
                exc_info=True,
            )
            return None

        # For BOOKMARK events, we only care about the resourceVersion and don't store the event.
        if event_type == "BOOKMARK":
            res_ver = sanitized_object.get("metadata", {}).get("resourceVersion")
            self.logger.debug(
                "[%s] Received BOOKMARK event. New resourceVersion: %s",
                watch_id,
                res_ver,
            )
            return str(res_ver) if res_ver is not None else None

        # For other event types (ADDED, MODIFIED, DELETED), update the store.
        await self.watched_resource_store.update_from_event(
            resource_kind_plural, {"type": event_type, "object": sanitized_object}
        )

        res_ver = sanitized_object.get("metadata", {}).get("resourceVersion")
        return str(res_ver) if res_ver is not None else None

    async def _watch_loop(
        self,
        watch_id: str,
        resource_kind_plural: str,
        api_watch_func: Callable[..., Coroutine[Any, Any, Any]],
        api_watch_func_kwargs: Dict[str, Any],
    ) -> None:
        """A resilient watch loop that attempts to maintain a watch on a resource,
        re-listing and re-watching as necessary.
        """
        self.logger.info("[%s] Starting watch loop.", watch_id)
        try:
            while not self._stop_event.is_set():
                try:
                    # 1. Get the initial list of resources and the resource_version.
                    # This is the entry point for the loop and the recovery point after a major error.
                    self.logger.info("[%s] Performing initial list.", watch_id)
                    resource_version = await self.get_and_store_initial_list(
                        resource_kind_plural, api_watch_func_kwargs.get("namespace")
                    )
                    if not resource_version:
                        self.logger.error(
                            "[%s] Failed to get initial list. Retrying after delay...",
                            watch_id,
                        )
                        await asyncio.sleep(self.retry_delay_seconds)
                        continue

                    # 2. Start a resilient watch sub-loop that survives timeouts.
                    while not self._stop_event.is_set():
                        self.logger.debug(
                            "[%s] Starting watch stream at version %s.",
                            watch_id,
                            resource_version,
                        )
                        should_relist = False
                        # Use a long, randomized timeout to avoid thundering herd problem.
                        timeout_with_jitter = random.randint(240, 360)
                        try:
                            async with Watch(return_type=object).stream(
                                api_watch_func,
                                **api_watch_func_kwargs,
                                resource_version=resource_version,
                                timeout_seconds=timeout_with_jitter,
                                allow_watch_bookmarks=True,
                                _preload_content=False,
                            ) as stream:
                                try:
                                    async for event in stream:
                                        if self._stop_event.is_set():
                                            return

                                        new_rv = await self._process_watch_event(
                                            watch_id, resource_kind_plural, event
                                        )
                                        if new_rv:
                                            resource_version = new_rv
                                        else:
                                            self.logger.warning(
                                                "[%s] Event processing failed (likely malformed object). Continuing watch.",
                                                watch_id
                                            )
                                except asyncio.CancelledError:
                                    self.logger.info(
                                        "[%s] Watch stream iteration cancelled.",
                                        watch_id
                                    )
                                    return
                                except Exception as e:
                                    self.logger.error(
                                        "[%s] Unhandled exception during watch stream iteration: %s",
                                        watch_id,
                                        e,
                                        exc_info=True,
                                    )
                                    should_relist = True  # Force a full re-list
                                    break
                        except asyncio.CancelledError:
                            self.logger.info(
                                "[%s] Watch stream cancelled.",
                                watch_id
                            )
                            return
                        except Exception as e:
                            self.logger.error(
                                "[%s] Error in watch stream: %s",
                                watch_id,
                                e,
                                exc_info=True
                            )
                            should_relist = True
                            break

                        if should_relist or self._stop_event.is_set():
                            break

                        if not self._stop_event.is_set():
                            self.logger.debug(
                                "[%s] Watch timed out, re-watching.",
                                watch_id
                            )

                except K8sApiException as e:
                    if e.status == 410:
                        self.logger.warning(
                            "[%s] Watch returned 410 Gone. Re-listing.",
                            watch_id
                        )
                    else:
                        self.logger.error(
                            "[%s] Kubernetes API exception in watch loop: %s - %s. "
                            "Retrying after delay.",
                            watch_id,
                            e.status,
                            e.reason,
                            exc_info=True,
                        )
                        await asyncio.sleep(self.retry_delay_seconds)
                except asyncio.CancelledError:
                    self.logger.info(
                        "[%s] Watch loop cancelled.",
                        watch_id
                    )
                    return
                except Exception as e:
                    self.logger.error(
                        "[%s] Unexpected error in watch loop: %s",
                        watch_id,
                        e,
                        exc_info=True,
                    )
                    await asyncio.sleep(self.retry_delay_seconds)
        finally:
            self.logger.info("[%s] Watch loop terminated.", watch_id)

    async def _start_watch_task(
        self, resource_kind_plural: str, namespace: str | None = None
    ) -> None:
        """Helper to create and start a single watch task."""
        resource_config = RESOURCE_REGISTRY.get(resource_kind_plural)
        if not isinstance(resource_config, dict):
            self.logger.error(
                "Unsupported resource kind for watch: %s", resource_kind_plural
            )
            return

        is_namespaced = resource_config.get("is_namespaced", True)
        ns_part = (
            "cluster-scoped" if not is_namespaced else (namespace or "all-namespaces")
        )
        watch_id = f"{resource_kind_plural}::{ns_part}"

        api_methods = self._get_api_watch_methods(
            resource_kind_plural, namespace=namespace
        )
        if not api_methods:
            self.logger.error(
                "Cannot start watch for %s, failed to get API methods.",
                watch_id
            )
            return
        api_watch_func, is_specific_ns = api_methods

        watch_kwargs: Dict[str, Any] = {}
        if is_specific_ns and namespace:
            watch_kwargs["namespace"] = namespace

        task = asyncio.create_task(
            self._watch_loop(
                watch_id, resource_kind_plural, api_watch_func, watch_kwargs
            )
        )
        self._watch_tasks.append(task)
        self.logger.info("Watch task created for %s", watch_id)

    async def start_and_monitor_watches(self) -> None:
        """The main entry point for the manager. Starts all configured watches and
        monitors them, restarting them if they fail. This coroutine runs until
        `stop()` is called.
        """
        self.logger.info("Starting and monitoring all configured watches...")

        # Create and start individual watch tasks for every resource defined
        # in the central resource registry.
        for resource_type in RESOURCE_REGISTRY:
            await self._start_watch_task(resource_type)

        # Keep this coroutine running until the stop event is set
        await self._stop_event.wait()

        # Once the stop event is set, we can clean up.
        self.logger.info("Stop event received, cleaning up watch tasks.")
        if self._watch_tasks:
            await asyncio.gather(*self._watch_tasks, return_exceptions=True)
        self.logger.info("All watch tasks have completed.")

    async def stop(self) -> None:
        """
        Signals all watch loops to stop and waits for them to terminate.
        """
        if self._stop_event.is_set():
            return
        self.logger.info("Signaling all watch loops to stop.")
        self._stop_event.set()

        # First try graceful shutdown
        tasks = list(self._watch_tasks)
        if tasks:
            # Wait up to 5 seconds for graceful shutdown
            _, pending = await asyncio.wait(tasks, timeout=5)
            
            # If any tasks are still pending, cancel them forcefully
            if pending:
                self.logger.warning(
                    "%s watch tasks did not terminate gracefully, cancelling them.",
                    len(pending)
                )
                for task in pending:
                    task.cancel()
                
                # Wait for cancelled tasks to complete
                try:
                    await asyncio.wait(pending, timeout=2)
                except asyncio.TimeoutError:
                    self.logger.error(
                        "%s watch tasks could not be cancelled and will be orphaned.",
                        len(pending)
                    )

        self.logger.info("Watch loop shutdown process complete.")
