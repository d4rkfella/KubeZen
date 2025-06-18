from __future__ import annotations
from typing import Any, Optional
import logging

from .resource_events import (
    ResourceEventListener,
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
    ResourceIdentifier,
)
from .watched_resource_store import WatchedResourceStore

log = logging.getLogger(__name__)


class WatchedResourceStoreAdapter:
    """Adapts a WatchedResourceStore to forward events to a specific listener.
    Each adapter instance handles one subscription (resource_type + namespace + listener).
    """

    def __init__(
        self,
        store: WatchedResourceStore,
        resource_type: str,
        namespace: Optional[str],
        listener: ResourceEventListener,
        resource_version: Optional[str] = None,
    ):
        self._store = store
        self._resource_type = resource_type
        self._namespace = namespace
        self.listener = listener
        self._is_running = False
        self._identifier = ResourceIdentifier(
            resource_type=resource_type, namespace=namespace
        )
        # This is the list resource version from the initial list operation
        self._list_resource_version = resource_version

    async def start(self) -> None:
        """Start forwarding events to the listener."""
        if self._is_running:
            return

        self._is_running = True
        log.debug(
            "Started watching %s from list version %s",
            self._resource_type,
            self._list_resource_version,
        )

    async def stop(self) -> None:
        """Stop forwarding events to the listener."""
        self._is_running = False

    def _should_process_event(self, resource_type: str, namespace: str) -> bool:
        """Check if an event should be processed based on resource type and namespace."""
        if not self._is_running or resource_type != self._resource_type:
            return False

        if self._namespace is not None and namespace != self._namespace:
            return False

        return True

    async def on_resource_added(
        self, resource_type: str, namespace: str, key: str, resource: dict[str, Any]
    ) -> None:
        """Forward resource added event if relevant."""
        if not self._should_process_event(resource_type, namespace):
            return

        event_identifier = ResourceIdentifier(
            resource_type=resource_type, namespace=namespace
        )
        await self.listener.on_resource_added(
            ResourceAddedSignal(identifier=event_identifier, resource_key=key)
        )

    async def on_resource_modified(
        self, resource_type: str, namespace: str, key: str, resource: dict[str, Any]
    ) -> None:
        """Forward resource modified event if relevant."""
        if not self._should_process_event(resource_type, namespace):
            return

        event_identifier = ResourceIdentifier(
            resource_type=resource_type, namespace=namespace
        )
        await self.listener.on_resource_modified(
            ResourceModifiedSignal(identifier=event_identifier, resource_key=key)
        )

    async def on_resource_deleted(
        self, resource_type: str, namespace: str, key: str
    ) -> None:
        """Forward resource deleted event if relevant."""
        if not self._should_process_event(resource_type, namespace):
            return

        event_identifier = ResourceIdentifier(
            resource_type=resource_type, namespace=namespace
        )
        await self.listener.on_resource_deleted(
            ResourceDeletedSignal(identifier=event_identifier, resource_key=key)
        )

    async def on_resource_full_refresh(
        self, resource_type: str, namespace: str
    ) -> None:
        """Forward resource full refresh event if relevant."""
        if not self._should_process_event(resource_type, namespace):
            return

        event_identifier = ResourceIdentifier(
            resource_type=resource_type, namespace=namespace
        )
        await self.listener.on_resource_full_refresh(
            ResourceFullRefreshSignal(
                identifier=event_identifier,
                resource_version=self._list_resource_version,
            )
        )
