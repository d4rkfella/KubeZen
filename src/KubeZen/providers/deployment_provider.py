from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Type, Protocol

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class DeploymentProviderProtocol(Protocol):
    """Protocol defining the interface for DeploymentProvider."""

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...


def create_deployment_provider() -> Type[DeploymentProviderProtocol]:
    """Creates a DeploymentProvider class."""
    return DeploymentProvider


class DeploymentProvider:
    """Provider for deployment-related operations."""

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        self.resource_kind = "deployments"

    @classmethod
    def get_cached_items(
        cls, app_services: AppServices, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Gets cached deployment items."""
        if not app_services.kubernetes_watch_manager:
            return []
        store = app_services.kubernetes_watch_manager.watched_resource_store
        return store.get_cached_items("deployments", namespace)
