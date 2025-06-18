from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple
import logging
import asyncio

from textual.app import App
from .watched_resource_store import WatchedResourceStore
from .watched_resource_store_adapter import WatchedResourceStoreAdapter
from .resource_events import (
    ResourceEventSource,
    ResourceEventListener,
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
)

log = logging.getLogger(__name__)


def create_resource_event_source(
    store: Optional[WatchedResourceStore] = None, app: Optional[App] = None
) -> ResourceEventSource:
    """Creates a ResourceEventSource from a WatchedResourceStore.

    Args:
        store: Optional WatchedResourceStore instance. If not provided, a new one will be created.
        app: Optional App instance. Required if store is not provided.

    Returns:
        A ResourceEventSource that can be used by screens.
    """
    if store is None:
        if app is None:
            raise ValueError("Either store or app must be provided")
        store = WatchedResourceStore(app)

    return ResourceSubscriptionManager(store)


class ResourceSubscriptionManager(ResourceEventSource):
    """Manages subscriptions to resource events.
    This is the main entry point for screens to subscribe to Kubernetes resource events.

    Flow:
    1. WatchManager -> Store.update_from_event() -> Store._update_handler
    2. Store._update_handler -> ResourceSubscriptionManager._handle_store_update
    3. ResourceSubscriptionManager -> Relevant Adapters -> Screen Listeners
    """

    def __init__(self, store: WatchedResourceStore):
        self._store = store
        self._adapters: Dict[
            str, Dict[Optional[str], List[WatchedResourceStoreAdapter]]
        ] = {}
        # Register as the store's update handler
        store.set_update_handler(self._handle_store_update)

    def _handle_store_update(
        self,
        event_type: str,
        resource_type: str,
        namespace: str,
        resource: dict[str, Any],
    ) -> None:
        """Handle updates from the store and forward them to relevant adapters."""
        # Get all potentially interested adapters
        interested_adapters = []

        # Adapters listening to this specific namespace
        if (
            resource_type in self._adapters
            and namespace in self._adapters[resource_type]
        ):
            interested_adapters.extend(self._adapters[resource_type][namespace])

        # Adapters listening to all namespaces
        if resource_type in self._adapters and None in self._adapters[resource_type]:
            interested_adapters.extend(self._adapters[resource_type][None])

        # Forward the event to each interested adapter
        for adapter in interested_adapters:
            if event_type == "DELETED":
                # For deleted events, try to get the resource name safely
                resource_name = resource.get("metadata", {}).get("name")
                if resource_name:
                    asyncio.create_task(
                        adapter.on_resource_deleted(
                            resource_type, namespace, resource_name
                        )
                    )
                else:
                    log.warning(
                        "Received DELETE event without resource name for %s in %s",
                        resource_type,
                        namespace,
                    )
            elif event_type == "ADDED":
                resource_key = resource["metadata"]["name"]
                asyncio.create_task(
                    adapter.on_resource_added(
                        resource_type, namespace, resource_key, resource
                    )
                )
            elif event_type == "MODIFIED":
                resource_key = resource["metadata"]["name"]
                asyncio.create_task(
                    adapter.on_resource_modified(
                        resource_type, namespace, resource_key, resource
                    )
                )
            elif event_type == "FULL_REFRESH":
                # For full refresh, let the adapter handle it by getting the current list
                asyncio.create_task(
                    adapter.on_resource_full_refresh(resource_type, namespace)
                )

    def _create_adapter(
        self,
        resource_type: str,
        namespace: Optional[str],
        listener: ResourceEventListener,
        resource_version: str,
    ) -> WatchedResourceStoreAdapter:
        """Create and register a new adapter.

        The resource_version is required to ensure we don't miss events between
        getting the initial state and starting to watch for changes.
        """
        if resource_type not in self._adapters:
            self._adapters[resource_type] = {}

        if namespace not in self._adapters[resource_type]:
            self._adapters[resource_type][namespace] = []

        adapter = WatchedResourceStoreAdapter(
            store=self._store,
            resource_type=resource_type,
            namespace=namespace,
            listener=listener,
            resource_version=resource_version,
        )
        self._adapters[resource_type][namespace].append(adapter)
        return adapter

    async def subscribe(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> None:
        """Subscribe to events for a specific resource type and namespace.

        Args:
            resource_type: The type of resource to subscribe to (e.g. 'pods', 'services')
            listener: The object that will receive the events
            namespace: Optional namespace to filter events. If None, receives events from all namespaces.
        """
        # Get the current list to get the resource version
        items, resource_version = await self._store.get_list(
            resource_type, namespace or "all-namespaces"
        )

        if resource_version is None:
            # This should never happen if the store is working correctly
            raise RuntimeError(
                f"Got None resource version for {resource_type} in {namespace or 'all-namespaces'}. "
                "This indicates a bug in the store implementation."
            )

        adapter = self._create_adapter(
            resource_type, namespace, listener, resource_version
        )
        await adapter.start()

    async def unsubscribe(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> None:
        """Unsubscribe a listener from events.
        Stops and removes the dedicated adapter for this subscription."""
        if resource_type not in self._adapters:
            return

        if namespace not in self._adapters[resource_type]:
            return

        adapters = self._adapters[resource_type][namespace]
        for adapter in adapters[:]:  # Create a copy to avoid modifying while iterating
            if adapter.listener is listener:
                await adapter.stop()
                adapters.remove(adapter)

        # Clean up empty lists
        if not adapters:
            del self._adapters[resource_type][namespace]
        if not self._adapters[resource_type]:
            del self._adapters[resource_type]

    async def get_current_list(
        self, resource_type: str, namespace: Optional[str] = None
    ) -> Tuple[List[dict[str, Any]], Optional[str]]:
        """Get the current list of resources."""
        return await self._store.get_list(resource_type, namespace)

    async def get_one(
        self,
        resource_type: str,
        namespace: Optional[str],
        resource_name: str,
    ) -> dict[str, Any] | None:
        """Get a single resource by its type, namespace, and name."""
        # Handle cluster-scoped resources
        if not self._store.is_namespaced(resource_type):
            namespace = "cluster-scoped"
        elif namespace is None:
            namespace = "all-namespaces"

        return self._store.get_one(resource_type, namespace, resource_name)

    async def subscribe_and_get_list(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> Tuple[List[dict[str, Any]], str]:
        """Subscribe to events and get initial list atomically.

        This ensures no events are missed between getting the initial list and subscribing.
        The resource version from the initial list is used to start watching for changes,
        ensuring we don't miss any events that happened after the list was retrieved.

        Returns:
            Tuple of (list of resources, resource version)
        """
        # First get the current list and resource version
        items, resource_version = await self._store.get_list(
            resource_type, namespace or "all-namespaces"
        )

        if resource_version is None:
            # This should never happen if the store is working correctly
            raise RuntimeError(
                f"Got None resource version for {resource_type} in {namespace or 'all-namespaces'}. "
                "This indicates a bug in the store implementation."
            )

        # Then subscribe using that resource version
        await self.subscribe(resource_type, listener, namespace)

        return items, resource_version
