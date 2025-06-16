from __future__ import annotations
import asyncio
from typing import (
    Dict,
    Any,
    List,
    Optional,
    TYPE_CHECKING,
    Tuple,
    Callable,
)
from collections import defaultdict
import copy
import logging

from .resource_registry import RESOURCE_REGISTRY

if TYPE_CHECKING:
    from textual.app import App


class WatchedResourceStore:
    """Store for Kubernetes resources that are being watched.
    Provides thread-safe access to the latest state of watched resources.
    """

    def __init__(self, app: App):
        self.logger = logging.getLogger(__name__)
        self.app = app
        self.store: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self.resource_versions: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.lock = asyncio.Lock()
        self._initial_load_complete: Dict[str, bool] = defaultdict(bool)

        # Listeners for UI updates, keyed by resource type
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    async def subscribe(
        self,
        resource_kind_plural: str,
        callback: Callable,
    ) -> None:
        """Subscribes a listener to receive updates for a resource type."""
        async with self.lock:
            if callback not in self._listeners[resource_kind_plural]:
                self._listeners[resource_kind_plural].append(callback)

    async def get_current_list(
        self, resource_kind_plural: str, namespace: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Get the current list of resources and resource version for a given kind.
        Returns a tuple of (items, resource_version).
        
        This method uses a lock to ensure consistent reads during updates and returns
        deep copies of the data to prevent external mutations affecting the store's state.
        """
        async with self.lock:
            all_items_for_type = self.store.get(resource_kind_plural)
            list_rv = self.resource_versions.get(resource_kind_plural, {}).get(
                namespace or "all-namespaces"
            )

            if not all_items_for_type:
                return [], list_rv

            if namespace and namespace != "--all-namespaces--":
                # Return a deep copy to prevent mutation of the store's internal list
                return copy.deepcopy(list(all_items_for_type.get(namespace, {}).values())), list_rv

            all_items: list[dict[str, Any]] = []
            for ns_items in all_items_for_type.values():
                all_items.extend(copy.deepcopy(list(ns_items.values())))
            return all_items, list_rv

    async def remove_listener(self, resource_kind_plural: str, callback: Callable) -> None:
        """Unregister a callback for a specific resource."""
        async with self.lock:
            if callback in self._listeners[resource_kind_plural]:
                self._listeners[resource_kind_plural].remove(callback)

    async def _notify_listeners(
        self, event_type: str, resource_kind_plural: str, resource: dict[str, Any]
    ) -> None:
        """Notify all registered listeners for a specific resource type."""
        # We must acquire the lock to safely get the list of listeners.
        async with self.lock:
            listeners_for_resource = self._listeners[resource_kind_plural][:]

        for callback in listeners_for_resource:
            try:
                await callback(
                    event_type=event_type,
                    resource_kind_plural=resource_kind_plural,
                    resource=resource,
                )
            except Exception:
                self.logger.exception("Error calling listener %s", callback)

    async def _notify_full_refresh(
        self,
        resource_kind_plural: str,
        items: list[dict[str, Any]],
        list_resource_version: str,
    ) -> None:
        """Notify listeners for a specific resource type that a full refresh is needed."""
        async with self.lock:
            listeners_for_resource = self._listeners[resource_kind_plural][:]

        for callback in listeners_for_resource:
            try:
                await callback(
                    event_type="FULL_REFRESH",
                    resource_kind_plural=resource_kind_plural,
                    resource=items,
                    list_resource_version=list_resource_version,
                )
            except Exception:
                self.logger.exception("Error calling listener %s", callback)

    def _get_resource_key_and_ref(
        self,
        resource_object: Dict[str, Any],
        resource_kind_plural_context: Optional[str] = None,
    ) -> Optional[Tuple[str, str, str]]:
        """A robust way to get the kind, namespace, and name from a resource object."""
        try:
            # The object from the client can be a dict or an object with attributes.
            # We check for both.
            metadata = resource_object.get("metadata", {})
            if not metadata:
                self.logger.warning(
                    "Resource has no 'metadata' field. Object: %s", resource_object
                )
                return None

            kind_from_obj = resource_object.get("kind")
            name = metadata.get("name")
            obj_namespace_field = metadata.get("namespace")

            # The resource kind might not be on the object itself in some list contexts,
            # so we fall back to the context provided by the caller.
            if kind_from_obj:
                kind = kind_from_obj.lower().rstrip("s")
            elif resource_kind_plural_context:
                kind = resource_kind_plural_context.lower().rstrip("s")
            else:
                kind = None

            # Namespaces are a special case; they are cluster-scoped but have no 'namespace' field.
            is_namespaced_resource = resource_kind_plural_context != "namespaces"

            if is_namespaced_resource:
                effective_namespace = obj_namespace_field
            else:
                # This is for cluster-scoped resources like Namespace, Node, etc.
                effective_namespace = "cluster-scoped"

            if not all([kind, name, effective_namespace]):
                self.logger.warning(
                    "Failed to extract key fields: kind=%s, name=%s, ns=%s. Object: %s",
                    kind,
                    name,
                    effective_namespace,
                    resource_object,
                )
                return None

            # Use singular form for kind for consistency
            return kind, effective_namespace, name
        except Exception as e:
            self.logger.error(
                "Unexpected error in _get_resource_key_and_ref: %s", e, exc_info=True
            )
            return None

    async def replace_list(
        self,
        resource_kind_plural: str,
        operation_namespace_key: str,
        resource_objects: List[Any],
        list_resource_version: str,
    ) -> None:
        items_added_count = 0
        async with self.lock:
            # When we get a list for all namespaces, we need to be careful.
            # We don't want to wipe out other namespace-specific watches if they exist.
            # The most common case is one big watch for all namespaces for a resource type.
            # In that case, we clear the whole top-level store for that resource.
            if operation_namespace_key == "all-namespaces":
                self.store[resource_kind_plural].clear()
            else:
                # If it's for a specific namespace, just clear that part.
                if operation_namespace_key in self.store[resource_kind_plural]:
                    self.store[resource_kind_plural][operation_namespace_key].clear()

            items = []
            for resource_object in resource_objects:
                # Always convert to dictionary to ensure store consistency.
                if hasattr(resource_object, "to_dict") and callable(
                    getattr(resource_object, "to_dict")
                ):
                    current_object = resource_object.to_dict()
                else:
                    current_object = copy.deepcopy(resource_object)
                items.append(current_object)

                # Ensure 'kind' is in the object for self-description.
                if "kind" not in current_object:
                    singular_kind = resource_kind_plural.rstrip("s")
                    current_object["kind"] = singular_kind.capitalize()

                _, item_actual_namespace, item_name = (
                    self._get_resource_key_and_ref(current_object, resource_kind_plural)
                    or (None, None, None)
                )

                if not item_name or not item_actual_namespace:
                    continue

                self.store[resource_kind_plural][item_actual_namespace][
                    item_name
                ] = current_object
                items_added_count += 1

            self.resource_versions[resource_kind_plural][
                operation_namespace_key
            ] = list_resource_version

            self._initial_load_complete[resource_kind_plural] = True

        # Notify listeners *after* releasing the lock to prevent deadlocks.
        await self._notify_full_refresh(
            resource_kind_plural, items, list_resource_version
        )
        self.logger.info(
            "Replaced list for %s/%s with %s items.",
            resource_kind_plural,
            operation_namespace_key or "all-namespaces",
            items_added_count,
        )

    def _deep_merge(self, old: dict, new: dict) -> dict:
        for k, v in new.items():
            if v is None and k in old:
                continue
            if k in old and isinstance(old.get(k), dict) and isinstance(v, dict):
                old[k] = self._deep_merge(old[k], v)
            else:
                old[k] = v
        return old

    async def update_from_event(
        self, resource_kind_plural: str, event: dict[str, Any]
    ) -> None:
        """Update the store based on a watch event.
        The event should be a dictionary with 'type' and 'object' keys.
        """
        event_type = event.get("type")
        resource_as_dict = event.get("object")

        if (
            not event_type
            or not resource_as_dict
            or not isinstance(resource_as_dict, dict)
        ):
            return

        # Ensure 'kind' is in the object for self-description.
        if "kind" not in resource_as_dict:
            singular_kind = resource_kind_plural.rstrip("s")
            resource_as_dict["kind"] = singular_kind.capitalize()

        key_info = self._get_resource_key_and_ref(
            resource_as_dict, resource_kind_plural
        )
        if not key_info:
            return

        _, namespace, name = key_info

        async with self.lock:
            if event_type == "ADDED":
                self.store[resource_kind_plural][namespace][name] = resource_as_dict
            elif event_type == "DELETED":
                if (
                    resource_kind_plural in self.store
                    and namespace in self.store[resource_kind_plural]
                    and name in self.store[resource_kind_plural][namespace]
                ):
                    del self.store[resource_kind_plural][namespace][name]
            elif event_type == "MODIFIED":
                # Deep merge to handle partial updates, but replace if not present
                old_resource = self.store[resource_kind_plural][namespace].get(name)
                if old_resource:
                    self.store[resource_kind_plural][namespace][name] = (
                        self._deep_merge(old_resource, resource_as_dict)
                    )
                else:
                    self.store[resource_kind_plural][namespace][name] = resource_as_dict

            new_resource_version = resource_as_dict.get("metadata", {}).get(
                "resourceVersion"
            )
            if new_resource_version:
                self.resource_versions[resource_kind_plural][
                    namespace
                ] = new_resource_version

        # Notify listeners outside the lock to avoid deadlocks
        await self._notify_listeners(
            event_type=event_type,
            resource_kind_plural=resource_kind_plural,
            resource=resource_as_dict,
        )
        self.logger.debug(
            "Processed %s for %s/%s/%s", event_type, resource_kind_plural, namespace, name
        )

    def get_one(
        self, resource_type: str, namespace: str, resource_name: str
    ) -> dict[str, Any] | None:
        """Get a single resource by its type, namespace, and name."""
        namespace_key = namespace
        if not self.is_namespaced(resource_type):
            namespace_key = "cluster-scoped"

        return (
            self.store.get(resource_type, {}).get(namespace_key, {}).get(resource_name)
        )

    def is_namespaced(self, resource_kind_plural: str) -> bool:
        """
        Checks if a resource type is namespaced based on the RESOURCE_REGISTRY.
        Defaults to True if not found, as most resources are namespaced.
        """
        # This is a bit of a workaround. A better solution would be to get this info
        # from the API server's discovery client.
        config = RESOURCE_REGISTRY.get(resource_kind_plural)
        if config and isinstance(config, dict):
            return bool(config.get("is_namespaced", True))
        self.logger.warning(
            "Could not find namespaced config for '%s'. Defaulting to True.",
            resource_kind_plural,
        )
        return True
