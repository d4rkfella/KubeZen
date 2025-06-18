from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, Tuple, Union


@dataclass
class ResourceIdentifier:
    """Identifies a Kubernetes resource."""

    resource_type: str
    namespace: Optional[str]


@dataclass
class ResourceAddedSignal:
    """Signal when a resource is added."""

    identifier: ResourceIdentifier
    resource_key: str  # Just the name/key of the resource that changed


@dataclass
class ResourceModifiedSignal:
    """Signal when a resource is modified."""

    identifier: ResourceIdentifier
    resource_key: str  # Just the name/key of the resource that changed


@dataclass
class ResourceDeletedSignal:
    """Signal when a resource is deleted."""

    identifier: ResourceIdentifier
    resource_key: str  # Just the name/key of the resource that was deleted


@dataclass
class ResourceFullRefreshSignal:
    """Signal when a full refresh is needed."""

    identifier: ResourceIdentifier
    resource_version: Optional[str] = None


# Type alias for all resource signal types
ResourceSignal = Union[
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
]


class ResourceEventListener(Protocol):
    """Protocol for objects that can listen to resource events."""

    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Called when a resource is added."""
        ...

    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Called when a resource is modified."""
        ...

    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Called when a resource is deleted."""
        ...

    async def on_resource_full_refresh(self, event: ResourceFullRefreshSignal) -> None:
        """Called when a full refresh is needed."""
        ...


class ResourceEventSource(ABC):
    """Abstract base class for objects that can emit resource events."""

    @abstractmethod
    async def subscribe_and_get_list(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> Tuple[List[dict[str, Any]], Optional[str]]:
        """Subscribe to events and get initial list atomically.

        This ensures no events are missed between getting the initial list and subscribing.
        Returns the initial list and its resource version.

        Args:
            resource_type: The type of resource to subscribe to (e.g. 'pods', 'services')
            listener: The object that will receive the events
            namespace: Optional namespace to filter events. If None, receives events from all namespaces.

        Returns:
            Tuple of (list of resources, resource version)
        """
        pass

    @abstractmethod
    async def subscribe(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> None:
        """Subscribe to events for a specific resource type.

        Args:
            resource_type: The type of resource to subscribe to (e.g. 'pods', 'services')
            listener: The object that will receive the events
            namespace: Optional namespace to filter events. If None, receives events from all namespaces.
        """
        pass

    @abstractmethod
    async def unsubscribe(
        self,
        resource_type: str,
        listener: ResourceEventListener,
        namespace: Optional[str] = None,
    ) -> None:
        """Unsubscribe from events for a specific resource type.

        Args:
            resource_type: The type of resource to unsubscribe from
            listener: The listener to unsubscribe
            namespace: The namespace that was used for subscription. Must match the original subscription.
        """
        pass

    @abstractmethod
    async def get_current_list(
        self, resource_type: str, namespace: Optional[str] = None
    ) -> Tuple[List[dict[str, Any]], Optional[str]]:
        """Get the current list of resources."""
        pass

    @abstractmethod
    async def get_one(
        self,
        resource_type: str,
        namespace: Optional[str],
        resource_name: str,
    ) -> dict[str, Any] | None:
        """Get a single resource by its type, namespace, and name.

        Args:
            resource_type: The type of resource to get (e.g. 'pods', 'services')
            namespace: The namespace of the resource, or None for cluster-scoped resources
            resource_name: The name of the resource to get

        Returns:
            The resource data if found, None otherwise
        """
        pass
