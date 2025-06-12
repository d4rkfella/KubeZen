from __future__ import annotations

# import sys # F401 unused
from typing import (
    Dict,
    Any,
    List,
    Optional,
    TYPE_CHECKING,
    Tuple,
)
from collections import defaultdict
import copy  # For deep copying objects if needed
import asyncio
import time

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices  # For ServiceBase

from KubeZen.core.service_base import ServiceBase  # Import ServiceBase
from KubeZen.core.events import ResourceStoreUpdateEvent


class WatchedResourceStore(ServiceBase):  # Inherit from ServiceBase
    """
    Manages an in-memory cache of Kubernetes resources, primarily updated by watch events.
    Also stores resource versions for watched lists and view versions for polling UI updates.
    """

    def __init__(self, app_services: AppServices):  # Accept AppServices
        super().__init__(app_services)  # Call super().__init__
        # self.logger is now set by ServiceBase
        self.store: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
        self.resource_versions: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.lock = asyncio.Lock()

        self.metrics = {
            "store_size": {},  # {(kind, ns): count}
            "prune_count": 0,
        }

        # Access config through app_services since ServiceBase guarantees it exists
        self.config = self.app_services.config
        assert self.config is not None, "AppConfig must be initialized"

        self._locks: Dict[str, asyncio.Lock] = {}
        self._publish_debounce_tasks: Dict[Tuple[str, str], asyncio.Task[None]] = {}
        self._publish_buffer: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self._publish_debounce_time = 0.1  # 100ms

    def _get_resource_key_and_ref(
        self, resource_object: Dict[str, Any], resource_kind_plural_context: Optional[str] = None
    ) -> Optional[Tuple[str, str, str]]:
        """Helper to extract kind, namespace, and name from a Kubernetes resource object."""
        try:
            kind_from_obj = resource_object.get("kind")
            if kind_from_obj is None:
                # self.logger.debug(
                #     f"WatchedResourceStore: Resource object has 'kind: None'. Raw object: {str(resource_object)[:200]}..."
                # )
                if resource_kind_plural_context == "namespaces":
                    kind_from_obj = "Namespace"

            kind_str = str(kind_from_obj) if kind_from_obj is not None else ""
            kind = kind_str.lower()

            metadata = resource_object.get("metadata", {})
            name = metadata.get("name")
            obj_namespace_field = metadata.get("namespace")

            effective_namespace = (
                "cluster-scoped"
                if kind == "namespace"
                else obj_namespace_field or "cluster-scoped"
            )

            if not name:
                self.logger.warning(
                    f"Resource object missing name in metadata. Kind: '{kind}', Object: {str(resource_object)[:200]}..."
                )
                return None

            if not kind:  # If kind is still empty after attempting to get it from object
                self.logger.warning(
                    f"Resource object missing 'kind'. Name: '{name}', Object: {str(resource_object)[:200]}..."
                )
                # If plural context is given, we might be able to derive singular kind, but this indicates an issue.
                # For now, if kind is essential and missing, we might have to return None or raise.
                # However, for the store, the `resource_kind_plural` is the primary key.
                # This method's 'kind' output is more for logging/validation.

            return kind, effective_namespace, name
        except AttributeError as e:  # This specific except might be less likely now with str()
            self.logger.error(
                f"AttributeError accessing attributes in resource object: {e} - Object: {str(resource_object)[:200]}..."
            )
            return None
        except Exception as e:
            self.logger.error(f"Error in _get_resource_key_and_ref: {e}")
            return None

    def _get_store_key(self, resource_kind_plural: str, namespace: Optional[str]) -> str:
        """
        Returns the canonical key used for the resource_versions dictionary.
        """
        if not self.is_namespaced(resource_kind_plural):
            return "cluster-scoped"
        return namespace if namespace is not None else "all-namespaces"

    async def get_lock(self, resource_kind_plural: str) -> asyncio.Lock:
        if resource_kind_plural not in self._locks:
            self._locks[resource_kind_plural] = asyncio.Lock()
        return self._locks[resource_kind_plural]

    async def replace_list(
        self,
        resource_kind_plural: str,
        operation_namespace_key: str,
        resource_objects: List[Any],
        list_resource_version: str,
        publish_update_event: bool = True,
    ) -> None:
        """
        Replaces the current list of resources with a new list.
        This is used for initial list and re-listing after watch errors (410 Gone).
        Notifies UI of the new list state based on the publish_update_event flag.
        """
        t0 = time.monotonic()
        self.logger.debug(f"[TIMING] replace_list: start at {t0:.4f}")

        items_added_count = 0
        lock = await self.get_lock(resource_kind_plural)

        async with lock:
            # Clear the store for this namespace
            if operation_namespace_key == "all-namespaces":
                self.store[resource_kind_plural].clear()
            else:
                if operation_namespace_key in self.store[resource_kind_plural]:
                    self.store[resource_kind_plural][operation_namespace_key].clear()

            # Populate with new items
            for resource_object in resource_objects:
                if hasattr(resource_object, "to_dict"):
                    current_object = resource_object.to_dict()
                elif isinstance(resource_object, dict):
                    current_object = copy.deepcopy(resource_object)
                else:
                    continue

                _kind_singular, item_actual_namespace, item_name = self._get_resource_key_and_ref(
                    current_object, resource_kind_plural
                ) or (None, None, None)

                if not item_name or not item_actual_namespace:
                    continue

                target_store_bucket_ns = item_actual_namespace
                if (
                    operation_namespace_key != "all-namespaces"
                    and operation_namespace_key != "cluster-scoped"
                    and item_actual_namespace != operation_namespace_key
                ):
                    continue

                self.store[resource_kind_plural][target_store_bucket_ns][
                    item_name
                ] = current_object
                items_added_count += 1

            # Update resource version with the new one
            self.resource_versions[resource_kind_plural][
                operation_namespace_key
            ] = list_resource_version

            # Notify UI of the new list state, but only if requested
            if publish_update_event:
                await self._publish_update_event(
                    resource_kind_plural,
                    operation_namespace_key,
                    {
                        "type": "REPLACED_LIST",
                        "kind": resource_kind_plural,
                        "namespace": operation_namespace_key,
                        "count": items_added_count,
                        "resource_version": list_resource_version,
                    },
                )

        self.logger.debug(f"[TIMING] replace_list: finished in {time.monotonic() - t0:.4f}s")

    def _deep_merge(self, old: dict, new: dict) -> dict:
        """
        Recursively merge 'new' into 'old'.
        Crucially, it does NOT overwrite an existing value in 'old' with None from 'new'.
        This prevents partial watch events from corrupting a complete, cached object.
        """
        for k, v in new.items():
            if v is None and k in old:
                continue  # Do not overwrite existing values with None.

            if k in old and isinstance(old.get(k), dict) and isinstance(v, dict):
                old[k] = self._deep_merge(old[k], v)
            else:
                old[k] = v
        return old

    async def update_from_event(self, resource_kind_plural: str, event: Dict[str, Any]) -> None:
        """
        Updates the store based on a single Kubernetes watch event.
        """
        event_type = event.get("type")
        raw_event_object = event.get("object")

        if not event_type or not raw_event_object:
            self.logger.debug(f"Event missing 'type' or 'object' field: {event}")
            return

        if hasattr(raw_event_object, "to_dict"):
            resource_as_dict = raw_event_object.to_dict()
        elif isinstance(raw_event_object, dict):
            resource_as_dict = copy.deepcopy(raw_event_object)
        else:
            self.logger.warning(
                f"Event object is not a dict or has no to_dict method: {type(raw_event_object)}"
            )
            return

        key_info = self._get_resource_key_and_ref(resource_as_dict, resource_kind_plural)
        if not key_info:
            return
        _kind_singular, namespace, name = key_info

        lock = await self.get_lock(resource_kind_plural)
        async with lock:
            if event_type == "DELETED":
                old_object = self.store[resource_kind_plural][namespace].pop(name, None)
                if old_object:
                    self.logger.debug(
                        f"Deleted {resource_kind_plural}/{namespace}/{name} from store."
                    )
                    await self._publish_update_event(
                        resource_kind_plural,
                        namespace,
                        {"type": event_type, "object_name": name},
                        old_object=old_object,
                    )
                return

            if event_type == "ADDED":
                self.store[resource_kind_plural][namespace][name] = resource_as_dict
                await self._publish_update_event(
                    resource_kind_plural,
                    namespace,
                    {"type": event_type, "object_name": name},
                    old_object=None,
                )
                self.logger.debug(f"Stored ADDED for {resource_kind_plural}/{namespace}/{name}.")
            elif event_type == "MODIFIED":
                old_object = self.store[resource_kind_plural][namespace].get(name)

                if old_object:
                    # Merge the incoming partial object into the existing complete one.
                    merged_obj = self._deep_merge(copy.deepcopy(old_object), resource_as_dict)
                    self.store[resource_kind_plural][namespace][name] = merged_obj
                else:
                    # If we don't have it, the event object is the best we have.
                    # Subsequent MODIFIED events will fill it out.
                    self.store[resource_kind_plural][namespace][name] = resource_as_dict

                self.logger.debug(
                    f"Stored MODIFIED event data for {resource_kind_plural}/{namespace}/{name}."
                )

                await self._publish_update_event(
                    resource_kind_plural,
                    namespace,
                    {"type": event_type, "object_name": name},
                    old_object=old_object,
                )

            # Update the list's resourceVersion to the one from the individual event object.
            new_resource_version = resource_as_dict.get("metadata", {}).get("resourceVersion")
            if new_resource_version:
                list_key_ns = (
                    namespace if self.is_namespaced(resource_kind_plural) else "cluster-scoped"
                )
                self.resource_versions[resource_kind_plural][list_key_ns] = new_resource_version

    def get_items(
        self,
        resource_kind_plural: str,
        namespace: Optional[str] = None,
    ) -> List[Any]:
        """
        Returns a list of items for a given resource kind and namespace.
        If namespace is None, it returns items from all namespaces for namespaced resources.
        """
        t0 = time.monotonic()
        target_items = []

        store_key = self._get_store_key(resource_kind_plural, namespace)

        # Decide which namespaces to iterate over in the store
        namespaces_to_check: List[str]
        if store_key == "cluster-scoped":
            namespaces_to_check = ["cluster-scoped"]
        elif store_key == "all-namespaces":  # all namespaces
            namespaces_to_check = list(self.store[resource_kind_plural].keys())
        else:
            namespaces_to_check = [store_key]

        self.logger.debug(
            f"get_items for {resource_kind_plural}, requested_ns={namespace}, store_key={store_key}, store_keys_to_check={namespaces_to_check}"
        )

        for ns_key in namespaces_to_check:
            if ns_key in self.store[resource_kind_plural]:
                for item_name, item in self.store[resource_kind_plural][ns_key].items():
                    target_items.append(item)
        t1 = time.monotonic()
        self.logger.debug(
            f"[TIMING] get_items for {resource_kind_plural} took {t1-t0:.4f}s, found {len(target_items)} items."
        )
        return target_items

    def get_all_items_of_kind(self, resource_kind_plural: str) -> List[Any]:
        """
        Returns all stored items of a specific kind, across all namespaces.
        """
        all_items: List[Any] = []
        for namespace_bucket in self.store[resource_kind_plural].values():
            all_items.extend(namespace_bucket.values())
        return all_items

    async def update_resource_version(
        self,
        resource_kind_plural: str,
        namespace: Optional[str],
        new_resource_version: str,
    ) -> None:
        """Updates the stored resource version for a list operation."""
        namespace_key = self._get_store_key(resource_kind_plural, namespace)
        lock = await self.get_lock(resource_kind_plural)
        async with lock:
            current_rv = self.resource_versions.get(resource_kind_plural, {}).get(namespace_key)
            if not current_rv or int(new_resource_version) > int(current_rv):
                self.resource_versions[resource_kind_plural][namespace_key] = new_resource_version
                self.logger.debug(
                    f"Updated resourceVersion for {resource_kind_plural}/{namespace_key} to {new_resource_version}"
                )

    async def _publish_update_event(
        self,
        resource_kind_plural: str,
        namespace: str,
        change_info: Dict[str, Any],
        old_object: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Debounces and publishes a ResourceStoreUpdateEvent to the event bus.
        This method collects rapid-fire changes into a buffer and schedules a
        single event publication after a short delay, preventing event storms.
        """
        buffer_key = (resource_kind_plural, namespace)

        # Cancel any existing, pending publish task for this resource/namespace pair.
        if buffer_key in self._publish_debounce_tasks:
            self._publish_debounce_tasks[buffer_key].cancel()

        # Add the new change to the buffer.
        self._publish_buffer[buffer_key].append(change_info)

        # Schedule the actual publish task.
        self._publish_debounce_tasks[buffer_key] = asyncio.create_task(
            self._execute_publish_debounced(buffer_key)
        )

    async def _execute_publish_debounced(self, buffer_key: Tuple[str, str]) -> None:
        """
        Waits for the debounce period, then publishes a single event with all
        buffered changes for a given resource kind and namespace.
        """
        try:
            await asyncio.sleep(self._publish_debounce_time)

            resource_kind_plural, namespace = buffer_key

            # Atomically get the buffered changes and clear the buffer for the key.
            # This prevents race conditions if a new event arrives right as this one fires.
            changes_to_publish = self._publish_buffer.pop(buffer_key, [])

            if not changes_to_publish:
                # This can happen if the buffer was cleared by another process, though unlikely.
                return

            # For now, we still publish a single event representing a "batch" update.
            # The `is_relevant_update` logic in the view doesn't need to know the details
            # of every single change, just that *something* changed.
            # We can use the details of the last change as representative.
            final_change_info = changes_to_publish[-1]

            event = ResourceStoreUpdateEvent(
                resource_kind_plural=resource_kind_plural,
                namespace=namespace,
                change_details=final_change_info,  # Contains info like ADDED/MODIFIED/DELETED
            )
            if self.app_services.event_bus:
                await self.app_services.event_bus.publish(event)
            self.logger.debug(
                f"Published batched ResourceStoreUpdateEvent for {resource_kind_plural}/{namespace} with {len(changes_to_publish)} changes."
            )
        except asyncio.CancelledError:
            # This is expected when debouncing. A new event came in for the same key.
            self.logger.debug(f"Publish task for {buffer_key} was cancelled (debounced).")
        finally:
            # Clean up the task entry once it's finished or cancelled.
            self._publish_debounce_tasks.pop(buffer_key, None)

    def is_namespaced(self, resource_kind_plural: str) -> bool:
        """
        Checks if a resource type is namespaced based on the RESOURCE_WATCH_CONFIG.
        Defaults to True if not found, as most resources are namespaced.
        """
        # This is a bit of a workaround. A better solution would be to get this info
        # from the API server's discovery client.
        from KubeZen.core.kubernetes_watch_manager import RESOURCE_WATCH_CONFIG

        config = RESOURCE_WATCH_CONFIG.get(resource_kind_plural)
        if config and isinstance(config, dict):
            return bool(config.get("namespaced", True))
        self.logger.warning(
            f"Could not find namespaced config for '{resource_kind_plural}'. Defaulting to True."
        )
        return True

    def get_cached_items(
        self,
        resource_kind_plural: str,
        namespace: Optional[str] = None,
    ) -> List[Any]:
        """
        Returns cached items. This is a simple alias for get_items.
        This method name is used by some views to fetch data.
        """
        return self.get_items(resource_kind_plural, namespace=namespace)
