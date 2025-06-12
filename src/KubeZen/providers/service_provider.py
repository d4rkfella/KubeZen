from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Type, Protocol

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class ServiceProviderProtocol(Protocol):
    """Protocol defining the interface for ServiceProvider."""

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...


def create_service_provider() -> Type[ServiceProviderProtocol]:
    """Creates a ServiceProvider class."""
    return ServiceProvider


class ServiceProvider:
    """Provider for service-related operations."""

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        self.resource_kind = "services"

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Gets cached service items."""
        if not app_services.kubernetes_watch_manager:
            return []
        store = app_services.kubernetes_watch_manager.watched_resource_store
        return store.get_cached_items("services", namespace) 