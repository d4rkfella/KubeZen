from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable
import logging
from kubernetes_asyncio.client.exceptions import ApiException

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

from .base_action import BaseAction
from ..core.resource_registry import RESOURCE_REGISTRY

log = logging.getLogger(__name__)


class DeleteResourceAction(BaseAction):
    """
    A generic action to delete any Kubernetes resource.
    """

    def __init__(
        self,
        app: KubeZenTuiApp,
        resource: dict[str, Any],
        object_name: str,
        resource_key: str,
    ):
        super().__init__(app, resource, object_name, resource_key)

    async def run(self) -> None:
        """
        Pushes a confirmation screen before performing the delete operation.
        """
        from ..screens.confirmation_screen import ConfirmationScreen

        # The actual deletion logic is passed as a callback to the confirmation screen
        await self.app.push_screen(
            ConfirmationScreen(
                title="Confirm Deletion",
                prompt=(
                    f"Are you sure you want to delete {self.resource_kind} "
                    f"'{self.resource_name}' in namespace '{self.namespace or 'all'}?"
                ),
                callback=self._perform_delete,
            )
        )

    async def _perform_delete(self) -> None:
        """Deletes the resource after confirmation."""
        try:
            log.info(
                f"Attempting to delete {self.resource_kind} '{self.resource_name}' "
                f"in namespace '{self.namespace}'"
            )
            delete_method = await self._get_delete_method()
            await delete_method()
            log.info(
                f"Successfully deleted {self.resource_kind} '{self.resource_name}' "
                f"in namespace '{self.namespace}'"
            )
            self.app.notify(
                f"✅ Successfully deleted {self.resource_kind} '{self.resource_name}'.",
                title="Success",
                timeout=5,
            )
            # Pop the action and confirmation screens to return to the list
            self.app.pop_screen()
            self.app.pop_screen()
            # TODO: Trigger a refresh of the resource list screen
        except ApiException as e:
            message = f"Failed to delete {self.resource_kind} '{self.resource_name}'. Reason: {e.reason}"
            log.exception(f"API error deleting resource '{self.resource_name}':")
            self.app.notify(message, title="Error", severity="error", timeout=10)
        except Exception:
            message = (
                f"An unexpected error occurred while deleting '{self.resource_name}'."
            )
            log.exception("An unexpected error occurred during resource deletion:")
            self.app.notify(message, title="Error", severity="error", timeout=10)

    async def _get_delete_method(self) -> Callable[[], Any]:
        """A generic function to get the delete method for any Kubernetes resource."""
        log.debug(f"Getting delete method for resource kind: '{self.resource_kind}'")
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not isinstance(resource_meta, dict):
            log.error(f"Resource kind '{self.resource_kind}' not found in registry.")
            raise ValueError(
                f"Deleting resource kind '{self.resource_kind}' is not supported."
            )
        log.debug(f"Found resource metadata: {resource_meta}")

        api_client_attr = resource_meta["api_client_attr"]
        if not isinstance(api_client_attr, str):
            raise TypeError("Expected api_client_attr to be a string")

        log.debug(f"Looking for API client attribute: '{api_client_attr}'")
        api_client = getattr(self.client, api_client_attr, None)
        if not api_client:
            log.error(f"API client '{api_client_attr}' not found on KubernetesClient.")
            raise ValueError(f"API client '{api_client_attr}' not found.")

        delete_method_name = resource_meta["delete_method"]
        if not isinstance(delete_method_name, str):
            raise TypeError("Expected delete_method to be a string")

        log.debug(f"Looking for delete method: '{delete_method_name}' on API client")
        api_method = getattr(api_client, delete_method_name, None)
        if not callable(api_method):
            log.error(f"API method '{delete_method_name}' not found or not callable.")
            raise ValueError(f"API method '{delete_method_name}' not found.")

        kwargs: dict[str, Any] = {"name": self.resource_name}
        if resource_meta["is_namespaced"]:
            log.debug("Resource is namespaced, adding namespace to arguments.")
            kwargs["namespace"] = self.namespace

        log.debug(f"Successfully created delete method with arguments: {kwargs}")
        # We need to return a callable with the arguments already bound
        return lambda: api_method(**kwargs)
