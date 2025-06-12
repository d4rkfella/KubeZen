from __future__ import annotations
import asyncio
import time

# import time  # F401 unused
from typing import (
    TYPE_CHECKING,
    List,
    Dict,
    Any,
    Optional,
    Callable,
    # Coroutine, # F401 unused
    Tuple,
    cast,
)

# import yaml  # F401 unused
# import json  # F401 unused
from kubernetes_asyncio.watch import Watch

from KubeZen.core.watched_resource_store import WatchedResourceStore
from KubeZen.core.service_base import ServiceBase  # Added import

from kubernetes_asyncio.client.exceptions import ApiException as K8sApiException


if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


RESOURCE_WATCH_CONFIG = {
    "pods": {
        "api_client_attr": "_core_v1_api",
        "list_all_method": "list_pod_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_pod",
        "is_namespaced": True,
        "expected_kind": "Pod",
        "expected_api_version": "v1",
    },
    "namespaces": {
        "api_client_attr": "_core_v1_api",
        "list_all_method": "list_namespace",  # Namespaces are not namespaced themselves
        "list_namespaced_method": None,  # No namespaced equivalent for listing namespaces
        "is_namespaced": False,
        "expected_kind": "Namespace",
        "expected_api_version": "v1",
    },
    "deployments": {
        "api_client_attr": "_apps_v1_api",
        "list_all_method": "list_deployment_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_deployment",
        "is_namespaced": True,
        "expected_kind": "Deployment",
        "expected_api_version": "apps/v1",
    },
    "pvcs": {
        "api_client_attr": "_core_v1_api",
        "list_all_method": "list_persistent_volume_claim_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_persistent_volume_claim",
        "is_namespaced": True,
        "expected_kind": "PersistentVolumeClaim",
        "expected_api_version": "v1",
    },
    "services": {
        "api_client_attr": "_core_v1_api",
        "list_all_method": "list_service_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_service",
        "is_namespaced": True,
        "expected_kind": "Service",
        "expected_api_version": "v1",
    },
    # "configmaps": {
    #     "api_client_attr": "core_v1_api",
    #     "list_all_method": "list_config_map_for_all_namespaces",
    #     "list_namespaced_method": "list_namespaced_config_map",
    #     "is_namespaced": True,
    #     "expected_kind": "ConfigMap",
    #     "expected_api_version": "v1",
    # },
}


class KubernetesWatchManager(ServiceBase):  # Inherit from ServiceBase
    """
    Manages Kubernetes resource watches, updates a local store, and provides
    access to this watched data.
    """

    def __init__(self, app_services: AppServices):
        super().__init__(app_services)  # MODIFIED: Call new ServiceBase __init__ with app_services
        assert (
            self.app_services.config is not None
        ), "KubernetesWatchManager requires a non-None AppConfig from AppServices"
        # self.app_services is now set by ServiceBase
        # self.logger is now set by ServiceBase
        self.config = (
            self.app_services.config
        )  # Access config via self.app_services (was app_services.config)
        self.logger.debug(
            f"Initializing with app_services.config: {type(self.config)}, value: {self.config}"
        )

        # The WatchManager will own the store
        self.watched_resource_store = WatchedResourceStore(app_services=self.app_services)

        self._watch_tasks: Dict[str, asyncio.Task] = {}
        self._is_shutting_down = False
        self.metrics: Dict[str, Any] = {
            "watches_started": 0,
            "list_errors": 0,
            "initial_list_count": 0,
            "last_initial_list_duration": 0.0,
        }

    def _get_api_watch_methods_full_tuple(
        self, resource_kind_plural: str, namespace: Optional[str] = None
    ) -> Optional[Tuple[Callable, Callable, Any, bool]]:
        """
        Dynamically gets the API list/watch methods and API client instance based on configuration.
        Adapted from KubernetesClient.
        """
        self.logger.debug(
            f"_get_api_watch_methods_full_tuple: Called for kind='{resource_kind_plural}', namespace='{namespace}'"
        )
        config_entry = RESOURCE_WATCH_CONFIG.get(resource_kind_plural)

        if not isinstance(config_entry, dict):
            self.logger.error(
                f"_get_api_watch_methods_full_tuple: No watch configuration found for resource kind '{resource_kind_plural}'."
            )
            return None

        api_client_attr_name = config_entry.get("api_client_attr")
        if not api_client_attr_name:
            self.logger.error(f"No api_client_attr in config for {resource_kind_plural}")
            return None
        # API clients are stored directly on self (e.g., self.core_v1_api)

        if not self.app_services.kubernetes_client:
            self.logger.error(
                "_get_api_watch_methods_full_tuple: KubernetesClient not available in AppServices."
            )
            return None

        api_client_instance = getattr(
            self.app_services.kubernetes_client, api_client_attr_name, None
        )

        if not api_client_instance:
            self.logger.error(
                f"_get_api_watch_methods_full_tuple: API client attribute '{api_client_attr_name}' not found or not initialized on KubernetesClient for kind '{resource_kind_plural}'."
            )
            return None

        is_namespaced_resource = config_entry.get("is_namespaced", True)
        method_name_to_use: Optional[str] = None
        is_for_specific_namespace_call = False

        if is_namespaced_resource:
            if namespace:
                method_name_to_use = cast(
                    Optional[str], config_entry.get("list_namespaced_method")
                )
                is_for_specific_namespace_call = True
            else:
                method_name_to_use = cast(Optional[str], config_entry.get("list_all_method"))
                is_for_specific_namespace_call = False
        else:
            if namespace:
                self.logger.warning(
                    f"_get_api_watch_methods_full_tuple: Namespace '{namespace}' provided for cluster-scoped resource kind '{resource_kind_plural}'. Namespace will be ignored."
                )
            method_name_to_use = cast(Optional[str], config_entry.get("list_all_method"))
            is_for_specific_namespace_call = False

        if not method_name_to_use:
            self.logger.error(
                f"_get_api_watch_methods_full_tuple: Appropriate list/watch method name could not be determined for kind '{resource_kind_plural}' with namespace '{namespace}'. Check RESOURCE_WATCH_CONFIG."
            )
            return None

        api_call_function = getattr(api_client_instance, method_name_to_use, None)

        if not callable(api_call_function):
            self.logger.error(
                f"_get_api_watch_methods_full_tuple: Method '{method_name_to_use}' not found or not callable on API client '{api_client_attr_name}' for kind '{resource_kind_plural}'."
            )
            return None

        # For simplicity, list and watch methods are assumed to be the same.
        return (
            api_call_function,
            api_call_function,
            api_client_instance,
            is_for_specific_namespace_call,
        )

    async def get_and_store_initial_list(
        self,
        resource_kind_plural: str,
        namespace: Optional[str],  # Namespace for the API call
        stop_event: Optional[asyncio.Event] = None,  # For graceful shutdown during list
        publish_update_event: bool = True,  # New flag to control event publishing
    ) -> Optional[str]:  # Returns resource_version or None/Error string
        t0 = time.monotonic()
        self.logger.debug(f"[TIMING] get_and_store_initial_list: start at {t0:.4f}")
        resource_config = RESOURCE_WATCH_CONFIG.get(resource_kind_plural)
        if not isinstance(resource_config, dict):
            self.logger.error(f"[GET_INITIAL_LIST] Unsupported resource: {resource_kind_plural}")
            return f"Error: Unsupported resource kind '{resource_kind_plural}'"

        is_namespaced_resource_api = bool(resource_config.get("is_namespaced", True))

        # effective_namespace_for_id is used for logging and store key generation.
        # If namespace is None for a namespaced resource, it means "all-namespaces".
        # If namespace is provided for a cluster-scoped resource, it's ignored for the API call but noted.
        effective_namespace_for_id: str
        if is_namespaced_resource_api:
            effective_namespace_for_id = namespace if namespace is not None else "all-namespaces"
        else:  # Cluster-scoped
            effective_namespace_for_id = "cluster-scoped"
            if namespace is not None:
                self.logger.warning(
                    f"[GET_INITIAL_LIST] Namespace '{namespace}' specified for non-namespaced resource '{resource_kind_plural}', ignoring."
                )

        self.logger.info(
            f"[GET_INITIAL_LIST] Attempting for {resource_kind_plural}::{effective_namespace_for_id}"
        )

        api_methods = self._get_api_watch_methods_full_tuple(
            resource_kind_plural, namespace=namespace
        )
        if not api_methods:
            return f"Error: Could not resolve API methods for {resource_kind_plural}"

        api_list_func, _api_watch_func, _api_client, _is_specific_ns = api_methods

        list_kwargs: Dict[str, Any] = {"watch": False}
        if _is_specific_ns:
            list_kwargs["namespace"] = namespace

        try:
            t1 = time.monotonic()
            self.logger.debug(f"[TIMING] before API list call: {t1 - t0:.4f}s")
            # The return type of list calls is a model object, not a dict.
            list_response = await api_list_func(**list_kwargs)
            t2 = time.monotonic()
            self.logger.debug(
                f"[TIMING] after API list call: {t2 - t0:.4f}s (delta: {t2 - t1:.4f}s)"
            )

            items = getattr(list_response, "items", [])
            if not items:
                self.logger.error(
                    f"[GET_INITIAL_LIST] List response for {resource_kind_plural}::{effective_namespace_for_id} has no items."
                )
                return "Error: List response has no items"

            # Get resource version from the list response metadata
            metadata = getattr(list_response, "metadata", None)
            if not metadata:
                self.logger.error(
                    f"[GET_INITIAL_LIST] List response for {resource_kind_plural}::{effective_namespace_for_id} has no metadata."
                )
                return "Error: List response missing metadata"

            resource_version = getattr(metadata, "resource_version", None)
            if not resource_version:
                self.logger.error(
                    f"[GET_INITIAL_LIST] List response for {resource_kind_plural}::{effective_namespace_for_id} is missing resource_version in metadata."
                )
                return "Error: List response missing resource_version"

            # Convert items to dicts
            items_as_dicts = []
            expected_kind = resource_config.get("expected_kind")
            expected_api_version = resource_config.get("expected_api_version")

            for item_obj in items:
                if self.app_services.kubernetes_client:
                    sanitized_obj = self.app_services.kubernetes_client.sanitize_for_serialization(
                        item_obj
                    )
                else:
                    sanitized_obj = item_obj
                item_dict = cast(Dict[str, Any], sanitized_obj)

                # Add kind and apiVersion if missing
                if "kind" not in item_dict or item_dict.get("kind") is None:
                    if expected_kind:
                        item_dict["kind"] = expected_kind
                if "apiVersion" not in item_dict or item_dict.get("apiVersion") is None:
                    if expected_api_version:
                        item_dict["apiVersion"] = expected_api_version

                items_as_dicts.append(item_dict)

            t2 = time.monotonic()
            self.logger.debug(f"[TIMING] before store.replace_list: {time.monotonic() - t0:.4f}s")
            await self.watched_resource_store.replace_list(
                resource_kind_plural,
                effective_namespace_for_id,
                items_as_dicts,
                resource_version,
                publish_update_event=publish_update_event,
            )
            t3 = time.monotonic()
            self.logger.debug(
                f"[TIMING] after store.replace_list: {t3 - t0:.4f}s (delta: {t3-t2:.4f}s)"
            )

            self.logger.info(
                f"[GET_INITIAL_LIST] Stored {len(items_as_dicts)} for {resource_kind_plural}::{effective_namespace_for_id}, RV: {resource_version}"
            )

            # Log metrics
            duration = time.monotonic() - t0
            self.metrics["initial_list_count"] += 1
            self.metrics["last_initial_list_duration"] = duration
            self.logger.info(f"[WatchManagerMetrics] {self.metrics}")

            return str(resource_version)

        except K8sApiException as e:
            self.metrics["list_errors"] += 1
            self.logger.error(
                f"[GET_INITIAL_LIST] Kubernetes API error listing {resource_kind_plural} in namespace '{namespace}': {e.status} - {e.reason}"
            )
            return f"Error: {e.status} - {e.reason}"
        except Exception as e:
            self.metrics["list_errors"] += 1
            self.logger.error(
                f"[GET_INITIAL_LIST] Unexpected error listing {resource_kind_plural} in namespace '{namespace}': {e}",
                exc_info=True,
            )
            return f"Error: Unexpected error - {e}"

    async def _process_watch_event(
        self, watch_id: str, resource_kind_plural: str, event: Dict[str, Any]
    ) -> Optional[str]:
        """
        Processes a single event from a Kubernetes watch stream.
        Returns the new resource version extracted from the event, or None on failure.
        """
        self.logger.debug(f"[{watch_id}] Processing event: {event.get('type')}")
        event_type = event.get("type")
        raw_object = event.get("object")

        if event_type == "ERROR":
            self.logger.error(f"[{watch_id}] Watch stream received an ERROR event: {event}")
            return None  # Signal to reset the watch

        if raw_object is None:
            self.logger.error(f"[{watch_id}] Event has a null 'object'. Event: {event}")
            return None  # Signal to reset the watch

        # Process the event to update the store.
        # update_from_event should be able to handle the model object directly.
        await self.watched_resource_store.update_from_event(resource_kind_plural, event)

        # Extract the new resource version from the model object's metadata attribute
        if hasattr(raw_object, "metadata") and hasattr(raw_object.metadata, "resource_version"):
            new_resource_version = cast(str, raw_object.metadata.resource_version)
        else:
            self.logger.warning(
                f"[{watch_id}] Watch event object is missing metadata or resourceVersion. Event: {event}"
            )
            return None  # Reset if we lose the resource version

        if not new_resource_version:
            self.logger.warning(
                f"[{watch_id}] Watch event has an empty resourceVersion. Event: {event}"
            )
            return None

        return new_resource_version

    async def _watch_loop(
        self,
        watch_id: str,  # Composite ID like "pods::default" or "namespaces::cluster-scoped"
        resource_kind_plural: str,
        api_namespace_param: Optional[str],  # Namespace to pass to the K8s API watch call
        initial_resource_version: str,
        api_watch_func: Callable,
        api_watch_func_kwargs: Dict[str, Any],
        retry_delay: float,
    ) -> None:
        """Watch loop for a specific resource type."""
        self.logger.info(
            f"_watch_loop coroutine started for {watch_id}. Initial RV: {initial_resource_version}"
        )

        resource_version = initial_resource_version

        self.logger.debug(f"[{watch_id}] Entering watch loop with RV {resource_version}")

        while not self._is_shutting_down:
            try:
                async with Watch().stream(
                    api_watch_func, **api_watch_func_kwargs, resource_version=resource_version
                ) as stream:
                    async for event in stream:
                        new_resource_version = await self._process_watch_event(
                            watch_id, resource_kind_plural, event
                        )

                        if new_resource_version is None:
                            self.logger.warning(
                                f"[{watch_id}] _process_watch_event returned None. Resetting."
                            )
                            # A None RV indicates a fatal processing error or a 410 Gone.
                            # We need to break to force a re-list.
                            break  # Exit the 'async for'
                        else:
                            resource_version = new_resource_version

            except K8sApiException as e:
                self.logger.error(f"[{watch_id}] Kubernetes API error in watch: {e}")
                if e.status == 410:
                    self.logger.warning(
                        f"[{watch_id}] Resource version {resource_version} is too old (410 Gone). Breaking to re-list."
                    )
                    break  # Exit the while loop to trigger re-list
                continue  # For other API errors, retry the watch.

            except asyncio.CancelledError:
                self.logger.info(f"[{watch_id}] Watch loop cancelled as part of shutdown.")
                self._is_shutting_down = True
                break

            except Exception as e:
                self.logger.error(
                    f"[{watch_id}] Unhandled exception in watch loop: {e}", exc_info=True
                )
                continue

            # If the stream ends cleanly (e.g., timeout), we break to re-list
            self.logger.warning(f"[{watch_id}] Watch stream ended. Breaking to re-list.")
            break

        # If the loop is exited and we're not shutting down, it means a re-list is needed.
        if not self._is_shutting_down:
            self.logger.info(f"[{watch_id}] Watch loop exited. Attempting to restart after delay.")
            await asyncio.sleep(retry_delay)  # Wait before restarting
            # The function will now exit, and the caller (_run_watch_with_auto_restart) will handle the restart.

    async def start_watch_for_resource(
        self,
        resource_kind_plural: str,
        api_namespace_param: Optional[str] = None,
    ) -> Optional[asyncio.Task]:
        """
        Starts a watch for a given resource kind and optional namespace.
        It fetches the initial list and then creates the background watch task.
        Returns the asyncio.Task object for the watch loop if successful.
        """
        resource_config = RESOURCE_WATCH_CONFIG.get(resource_kind_plural)
        if not isinstance(resource_config, dict):
            self.logger.error(f"Unsupported resource kind for watch: {resource_kind_plural}")
            return None

        is_namespaced = bool(resource_config.get("is_namespaced", True))

        watch_id_ns_part = "cluster-scoped"
        if is_namespaced:
            watch_id_ns_part = (
                api_namespace_param if api_namespace_param is not None else "all-namespaces"
            )

        watch_id = f"{resource_kind_plural}::{watch_id_ns_part}"

        if watch_id in self._watch_tasks:
            self.logger.warning(f"Watch for '{watch_id}' is already running.")
            task = self._watch_tasks[watch_id]
            return task

        api_methods = self._get_api_watch_methods_full_tuple(
            resource_kind_plural, namespace=api_namespace_param
        )
        if not api_methods:
            self.logger.error(f"Failed to get API methods for '{watch_id}', cannot start watch.")
            return None

        _api_list_func, api_watch_func, _api_client, is_specific_ns = api_methods

        # Perform the initial list. The watch loop will now handle getting the RV from the store.
        initial_rv = await self.get_and_store_initial_list(
            resource_kind_plural, api_namespace_param
        )
        if not initial_rv or initial_rv.startswith("Error"):
            self.logger.error(
                f"Failed to get initial list for {watch_id}. Cannot start watch. Error: {initial_rv}"
            )
            return None

        self.logger.info(f"Initial list for {watch_id} OK, RV: {initial_rv}")

        watch_kwargs = {}  # The loop now manages the resource_version internally
        if is_specific_ns:
            watch_kwargs["namespace"] = api_namespace_param

        loop_task = asyncio.create_task(
            self._watch_loop(
                watch_id=watch_id,
                resource_kind_plural=resource_kind_plural,
                api_namespace_param=api_namespace_param,
                initial_resource_version=initial_rv,
                api_watch_func=api_watch_func,
                api_watch_func_kwargs=watch_kwargs,
                retry_delay=self.config.kubernetes_retry_delay_seconds,
            )
        )
        self._watch_tasks[watch_id] = loop_task
        self.logger.info(f"Watch started for {watch_id} as task {loop_task.get_name()}")
        self.metrics["watches_started"] += 1
        return loop_task

    async def setup_watches_based_on_config(self) -> None:
        """
        Iterates RESOURCE_WATCH_CONFIG and starts watches concurrently.
        This is the primary method to be called by AppController/AppServices to initiate watching.
        """
        self.logger.info("Setting up watches based on RESOURCE_WATCH_CONFIG...")

        setup_coroutines = []
        for resource_kind_plural in RESOURCE_WATCH_CONFIG:
            self.logger.info(f"Preparing watch setup for: {resource_kind_plural}")
            setup_coroutines.append(
                self.start_watch_for_resource(resource_kind_plural, api_namespace_param=None)
            )

        results = await asyncio.gather(*setup_coroutines, return_exceptions=True)

        successful_starts = 0
        for i, result in enumerate(results):
            resource_kind = list(RESOURCE_WATCH_CONFIG.keys())[i]
            if isinstance(result, Exception):
                self.logger.error(
                    f"Error setting up watch for {resource_kind}: {result}",
                    exc_info=result,
                )
            elif isinstance(result, asyncio.Task):
                successful_starts += 1
            else:
                self.logger.error(
                    f"Failed to start watch for {resource_kind}, returned: {result}."
                )

        if successful_starts == len(results):
            self.logger.info("All configured watches have been started and are running.")
        else:
            self.logger.error(
                f"{successful_starts}/{len(results)} configured watches started successfully."
            )

        self.logger.info("Watch setup based on config finished.")

    def get_all_items_of_kind(self, resource_kind_plural: str) -> List[Any]:
        """Get all items of a given kind from the store."""
        if not self.watched_resource_store:
            self.logger.error("WatchedResourceStore not initialized")
            return []
        return self.watched_resource_store.get_all_items_of_kind(resource_kind_plural)

    async def stop(self) -> None:
        """
        Gracefully stops all running watch tasks.
        """
        self.logger.info("Stopping all Kubernetes resource watches...")
        self._is_shutting_down = True

        if not self._watch_tasks:
            self.logger.info("No active watch tasks to stop.")
            return

        # Create a list of tasks to await for graceful shutdown
        tasks_to_wait_for = []
        for watch_id, task in self._watch_tasks.items():
            self.logger.debug(f"Cancelling watch task: {watch_id}")
            task.cancel()  # Cancel the task
            tasks_to_wait_for.append(task)

        self.logger.info(f"Waiting for {len(tasks_to_wait_for)} watch tasks to terminate...")
        try:
            await asyncio.gather(*tasks_to_wait_for, return_exceptions=True)
        except asyncio.CancelledError:
            self.logger.info(
                "Main stop task was cancelled, watch tasks may not have fully cleaned up."
            )

        self._watch_tasks.clear()
        self.logger.info("All Kubernetes resource watches have been stopped.")
