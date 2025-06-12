from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Type, Protocol

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class PodProviderProtocol(Protocol):
    """Protocol defining the interface for PodProvider."""

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...


def create_pod_provider() -> Type[PodProviderProtocol]:
    """Creates a PodProvider class."""
    return PodProvider


class PodProvider:
    """Provider for pod-related operations."""

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        self.resource_kind = "pods"

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Gets cached pod items."""
        if not app_services.kubernetes_watch_manager:
            return []
        store = app_services.kubernetes_watch_manager.watched_resource_store
        return store.get_cached_items("pods", namespace)
