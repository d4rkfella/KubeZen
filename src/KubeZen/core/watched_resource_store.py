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

    This store:
    1. Maintains the current state of resources
    2. Processes events from the watch manager to update state
    3. Notifies a single update handler when state changes
    """

    def __init__(self, app: App):
        self.logger = logging.getLogger(__name__)
        self.app = app
        # Resource data, indexed by: resource_type -> namespace -> name -> resource
        self.store: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # Resource versions, indexed by: resource_type -> namespace -> version
        self.resource_versions: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.lock = asyncio.Lock()
        # Single callback for state updates
        self._update_handler: Optional[
            Callable[[str, str, str, dict[str, Any]], None]
        ] = None

    def set_update_handler(
        self, handler: Callable[[str, str, str, dict[str, Any]], None]
    ) -> None:
        """Set the handler that will be called when resources are updated.

        The handler receives:
        - event_type: "ADDED", "MODIFIED", "DELETED", or "FULL_REFRESH"
        - resource_type: The type of resource that changed
        - namespace: The namespace of the resource
        - resource: The resource data (empty dict for DELETED events)
        """
        self._update_handler = handler

    def _deep_merge(self, old: dict, new: dict) -> dict:
        """Deep merge two dictionaries, with new values taking precedence."""
        for k, v in new.items():
            if v is None and k in old:
                continue
            if k in old and isinstance(old.get(k), dict) and isinstance(v, dict):
                old[k] = self._deep_merge(old[k], v)
            else:
                old[k] = v
        return old

    async def update_from_event(
        self, resource_type: str, event: dict[str, Any]
    ) -> None:
        """Process an event from the watch manager and update store state.

        Args:
            resource_type: The type of resource (e.g. 'pods', 'services')
            event: The event from the watch manager containing:
                - type: "ADDED", "MODIFIED", "DELETED"
                - object: The resource data
        """
        event_type = event.get("type")
        resource = event.get("object", {})

        if not event_type or not isinstance(resource, dict):
            return

        # Ensure 'kind' is in the object
        if "kind" not in resource:
            singular_kind = resource_type.rstrip("s")
            resource["kind"] = singular_kind.capitalize()

        # For deleted events, we only need the metadata
        if event_type == "DELETED":
            # Try to get the resource name from the event object
            resource_name = resource.get("metadata", {}).get("name")
            if not resource_name:
                self.logger.warning(
                    "Received DELETE event without resource name for %s",
                    resource_type,
                )
                return

            # Get the namespace from the event object or use None for cluster-scoped resources
            namespace = resource.get("metadata", {}).get("namespace")
            if not self.is_namespaced(resource_type):
                namespace = None

            # Call the update handler with minimal information needed for deletion
            if self._update_handler is not None:
                self._update_handler(
                    event_type,
                    resource_type,
                    namespace,
                    {"metadata": {"name": resource_name, "namespace": namespace}},
                )
            return

        # For other events, process normally
        namespace = resource.get("metadata", {}).get("namespace")
        if not self.is_namespaced(resource_type):
            namespace = None

        # Update the store
        key_info = self._get_resource_key_and_ref(resource, resource_type)
        if not key_info:
            return

        _, namespace, name = key_info

        async with self.lock:
            if event_type == "ADDED":
                self.store[resource_type][namespace][name] = resource
            elif event_type == "MODIFIED":
                old_resource = self.store[resource_type][namespace].get(name)
                if old_resource:
                    self.store[resource_type][namespace][name] = self._deep_merge(
                        old_resource, resource
                    )
                else:
                    self.store[resource_type][namespace][name] = resource

            # Update resource version
            new_resource_version = resource.get("metadata", {}).get("resourceVersion")
            if new_resource_version:
                self.resource_versions[resource_type][namespace] = new_resource_version

        # Notify handler outside the lock
        if self._update_handler is not None:
            self._update_handler(event_type, resource_type, namespace, resource)

        self.logger.debug(
            "Processed %s for %s/%s/%s", event_type, resource_type, namespace, name
        )

    async def replace_list(
        self,
        resource_type: str,
        operation_namespace_key: str,
        resource_objects: List[Any],
        list_resource_version: str,
    ) -> None:
        """Replace the entire list of resources for a given type and namespace."""
        async with self.lock:
            # Clear the appropriate section of the store
            if operation_namespace_key == "all-namespaces":
                self.store[resource_type].clear()
            else:
                if operation_namespace_key in self.store[resource_type]:
                    self.store[resource_type][operation_namespace_key].clear()

            # Store the new resource version
            self.resource_versions[resource_type][
                operation_namespace_key
            ] = list_resource_version

            # Process and store each resource
            for resource_object in resource_objects:
                # Convert to dictionary if needed
                if hasattr(resource_object, "to_dict") and callable(
                    getattr(resource_object, "to_dict")
                ):
                    current_object = resource_object.to_dict()
                else:
                    current_object = copy.deepcopy(resource_object)

                # Ensure 'kind' is in the object
                if "kind" not in current_object:
                    singular_kind = resource_type.rstrip("s")
                    current_object["kind"] = singular_kind.capitalize()

                # Get the resource identifiers
                _, item_actual_namespace, item_name = self._get_resource_key_and_ref(
                    current_object, resource_type
                ) or (None, None, None)

                if not item_name or not item_actual_namespace:
                    continue

                # Store the resource
                self.store[resource_type][item_actual_namespace][
                    item_name
                ] = current_object

            # Notify handler about the full refresh
            if self._update_handler:
                self._update_handler(
                    "FULL_REFRESH", resource_type, operation_namespace_key, {}
                )

    async def get_list(
        self, resource_type: str, namespace: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Get the current list of resources for a given type and namespace.

        Returns:
            A tuple of (list of resources, resource version)
        """
        async with self.lock:
            all_items_for_type = self.store.get(resource_type)
            if not all_items_for_type:
                return [], None

            # For cluster-scoped resources like namespaces, use "cluster-scoped" as the key
            if not self.is_namespaced(resource_type):
                resource_version = self.resource_versions.get(resource_type, {}).get(
                    "cluster-scoped"
                )
            else:
                # Always use "all-namespaces" for the resource version since that's how we store it
                # The namespace parameter only affects which items we return
                resource_version = self.resource_versions.get(resource_type, {}).get(
                    "all-namespaces"
                )

            if namespace and namespace != "all-namespaces":
                return (
                    copy.deepcopy(list(all_items_for_type.get(namespace, {}).values())),
                    resource_version,
                )

            all_items: list[dict[str, Any]] = []
            for ns_items in all_items_for_type.values():
                all_items.extend(copy.deepcopy(list(ns_items.values())))
            return all_items, resource_version

    async def get_resource_version(
        self, resource_type: str, namespace: str | None = None
    ) -> str | None:
        """Get the current resource version for a given type and namespace."""
        async with self.lock:
            return self.resource_versions.get(resource_type, {}).get(
                namespace or "all-namespaces"
            )

    def _get_resource_key_and_ref(
        self,
        resource_object: Dict[str, Any],
        resource_kind_plural_context: Optional[str] = None,
    ) -> Optional[Tuple[str, str, str]]:
        """Extract kind, namespace, and name from a resource object."""
        try:
            metadata = resource_object.get("metadata", {})
            if not metadata:
                self.logger.warning(
                    "Resource has no 'metadata' field. Object: %s", resource_object
                )
                return None

            kind_from_obj = resource_object.get("kind")
            name = metadata.get("name")
            obj_namespace_field = metadata.get("namespace")

            # The resource kind might not be on the object itself in some list contexts
            if kind_from_obj:
                kind = kind_from_obj.lower().rstrip("s")
            elif resource_kind_plural_context:
                kind = resource_kind_plural_context.lower().rstrip("s")
            else:
                kind = None

            # Namespaces are cluster-scoped but have no 'namespace' field
            is_namespaced_resource = resource_kind_plural_context != "namespaces"
            effective_namespace = (
                obj_namespace_field if is_namespaced_resource else "cluster-scoped"
            )

            if not all([kind, name, effective_namespace]):
                self.logger.warning(
                    "Failed to extract key fields: kind=%s, name=%s, ns=%s. Object: %s",
                    kind,
                    name,
                    effective_namespace,
                    resource_object,
                )
                return None

            return kind, effective_namespace, name
        except Exception as e:
            self.logger.error(
                "Unexpected error in _get_resource_key_and_ref: %s", e, exc_info=True
            )
            return None

    def get_one(
        self, resource_type: str, namespace: str, resource_name: str
    ) -> dict[str, Any] | None:
        """Get a single resource by its type, namespace, and name."""
        return copy.deepcopy(
            self.store.get(resource_type, {}).get(namespace, {}).get(resource_name)
        )

    def is_namespaced(self, resource_type: str) -> bool:
        """Check if a resource type is namespaced."""
        config = RESOURCE_REGISTRY.get(resource_type)
        return bool(config and config.get("is_namespaced", True))
