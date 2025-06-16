from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

@dataclass
class ResourceEvent:
    """Base class for all resource events."""
    resource_type: str

@dataclass
class ResourceAddedSignal(ResourceEvent):
    """Signal when a resource is added."""
    resource_key: str  # Just the name/key of the resource that changed

@dataclass
class ResourceModifiedSignal(ResourceEvent):
    """Signal when a resource is modified."""
    resource_key: str  # Just the name/key of the resource that changed

@dataclass
class ResourceDeletedSignal(ResourceEvent):
    """Signal when a resource is deleted."""
    resource_key: str  # Just the name/key of the resource that was deleted

@dataclass
class ResourceFullRefreshSignal(ResourceEvent):
    """Signal when a full refresh is needed."""
    resource_version: Optional[str] = None

class ResourceEventListener(ABC):
    """Abstract base class for objects that can listen to resource events."""
    
    @abstractmethod
    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Called when a resource is added."""
        pass

    @abstractmethod
    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Called when a resource is modified."""
        pass

    @abstractmethod
    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Called when a resource is deleted."""
        pass

    @abstractmethod
    async def on_resource_full_refresh(self, event: ResourceFullRefreshSignal) -> None:
        """Called when a full refresh is needed."""
        pass

class ResourceEventSource(Protocol):
    """Protocol for objects that can emit resource events."""
    
    async def subscribe(self, resource_type: str, listener: ResourceEventListener) -> None:
        """Subscribe to events for a specific resource type."""
        ...

    async def unsubscribe(self, resource_type: str, listener: ResourceEventListener) -> None:
        """Unsubscribe from events for a specific resource type."""
        ...

    def get_current_list(self, resource_type: str, namespace: Optional[str] = None) -> tuple[List[dict[str, Any]], Optional[str]]:
        """Get the current list of resources."""
        ... 