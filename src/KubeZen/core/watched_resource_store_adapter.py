from typing import Any, Dict, Optional, List
from .resource_events import (
    ResourceEventListener,
    ResourceEventSource,
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
)
from .watched_resource_store import WatchedResourceStore

class WatchedResourceStoreAdapter(ResourceEventSource):
    """Adapts WatchedResourceStore to the ResourceEventSource interface."""

    def __init__(self, store: WatchedResourceStore):
        self._store = store
        self._listeners: Dict[str, List[ResourceEventListener]] = {}

    async def subscribe(self, resource_type: str, listener: ResourceEventListener) -> None:
        """Subscribe to events for a specific resource type."""
        if resource_type not in self._listeners:
            self._listeners[resource_type] = []
            # Subscribe to the underlying store
            await self._store.subscribe(resource_type, self._handle_store_event)
        
        if listener not in self._listeners[resource_type]:
            self._listeners[resource_type].append(listener)

    async def unsubscribe(self, resource_type: str, listener: ResourceEventListener) -> None:
        """Unsubscribe from events for a specific resource type."""
        if resource_type in self._listeners:
            if listener in self._listeners[resource_type]:
                self._listeners[resource_type].remove(listener)
            
            if not self._listeners[resource_type]:
                # No more listeners for this resource type
                del self._listeners[resource_type]
                await self._store.remove_listener(resource_type, self._handle_store_event)

    async def get_current_list(self, resource_type: str, namespace: Optional[str] = None) -> tuple[List[dict[str, Any]], Optional[str]]:
        """Get the current list of resources."""
        return await self._store.get_current_list(resource_type, namespace)

    async def _handle_store_event(
        self,
        event_type: str,
        resource_kind_plural: Optional[str] = None,
        resource: Optional[Any] = None,
        list_resource_version: Optional[str] = None,
    ) -> None:
        """Handle events from the WatchedResourceStore and convert them to ResourceEvents."""
        if not resource_kind_plural or resource_kind_plural not in self._listeners:
            return

        listeners = self._listeners[resource_kind_plural]

        if event_type == "FULL_REFRESH":
            event = ResourceFullRefreshSignal(
                resource_type=resource_kind_plural,
                resource_version=list_resource_version
            )
            for listener in listeners:
                await listener.on_resource_full_refresh(event)
            return

        if not resource or not isinstance(resource, dict):
            return

        resource_key = resource.get("metadata", {}).get("name")
        if not resource_key:
            return

        event_map = {
            "ADDED": (ResourceAddedSignal, "on_resource_added"),
            "MODIFIED": (ResourceModifiedSignal, "on_resource_modified"),
            "DELETED": (ResourceDeletedSignal, "on_resource_deleted")
        }

        if event_type in event_map:
            event_class, handler_name = event_map[event_type]
            event = event_class(
                resource_type=resource_kind_plural,
                resource_key=resource_key
            )
            for listener in listeners:
                handler = getattr(listener, handler_name)
                await handler(event) 