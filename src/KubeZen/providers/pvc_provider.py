from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Type, Protocol

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class PVCProviderProtocol(Protocol):
    """Protocol defining the interface for PVCProvider."""

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...


def create_pvc_provider() -> Type[PVCProviderProtocol]:
    """Creates a PVCProvider class."""
    return PVCProvider


class PVCProvider:
    """Provider for PVC-related operations."""

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        self.resource_kind = "pvcs"

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Gets cached PVC items."""
        if not app_services.kubernetes_watch_manager:
            return []
        store = app_services.kubernetes_watch_manager.watched_resource_store
        return store.get_cached_items("pvcs", namespace)
