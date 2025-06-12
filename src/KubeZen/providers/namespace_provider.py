from __future__ import annotations
from typing import List, Dict, Any, TYPE_CHECKING, Type, Protocol, Optional

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class NamespaceProviderProtocol(Protocol):
    """Protocol defining the interface for NamespaceProvider."""

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...


def create_namespace_provider() -> Type[NamespaceProviderProtocol]:
    """Creates a NamespaceProvider class."""
    return NamespaceProvider


class NamespaceProvider:
    """Provider for namespace-related operations."""

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        self.resource_kind = "namespaces"

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Gets cached namespace items."""
        if not app_services.kubernetes_watch_manager:
            return []
        store = app_services.kubernetes_watch_manager.watched_resource_store
        return store.get_cached_items("namespaces", None)
