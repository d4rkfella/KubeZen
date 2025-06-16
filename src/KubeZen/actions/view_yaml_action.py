from __future__ import annotations
from typing import TYPE_CHECKING, Any
import yaml
import logging
from kubernetes_asyncio.client.exceptions import ApiException

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

from ..utils import create_temp_file_and_get_command
from .base_action import BaseAction
from ..core.resource_registry import RESOURCE_REGISTRY

log = logging.getLogger(__name__)


class ViewYamlAction(BaseAction):
    """
    A generic action to view the YAML of any Kubernetes resource.
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
        """Fetches the resource YAML, writes it to a temp file, and shows it."""
        try:
            resource_yaml = await self._get_resource_yaml()
        except ApiException as e:
            if e.status == 404:
                resource_yaml = (
                    f"Error: Resource '{self.resource_kind}/{self.resource_name}' not found.\n\n"
                    f"It may have been deleted after it was displayed in the list."
                )
                log.warning(f"Resource not found for view yaml: {e.reason}")
            else:
                resource_yaml = f"An API error occurred: {e.reason}\n\nStatus: {e.status}\nBody: {e.body}"
                log.error("API error viewing resource YAML:", exc_info=True)
        except Exception:
            log.error("An unexpected error occurred during view yaml:", exc_info=True)
            return

        try:
            command = create_temp_file_and_get_command(
                content=resource_yaml,
                file_prefix=f"view-{self.resource_kind}-{self.resource_name}-",
            )
            log.info(f"Generated view yaml command: {command}")
            window_name = f"view-{self.resource_name}"
            await self.tmux_manager.launch_command_in_new_window(
                command, window_name=window_name, attach=True
            )
        except Exception:
            log.error("Failed to launch tmux window for view yaml:", exc_info=True)

    async def _get_resource_yaml(self) -> str:
        """Fetches details for a given resource and formats it as YAML."""
        resource_details_obj = await self._get_resource_details()

        # Sanitize the object to get a dict representation before dumping to YAML
        if not self.client.api_client:
            return "Error: API client not initialized."
        sanitized_dict = self.client.api_client.sanitize_for_serialization(
            resource_details_obj
        )

        # Remove verbose, managed fields for clarity
        if "metadata" in sanitized_dict and isinstance(
            sanitized_dict["metadata"], dict
        ):
            sanitized_dict["metadata"].pop("managedFields", None)
            sanitized_dict["metadata"].pop("resourceVersion", None)
            sanitized_dict["metadata"].pop("uid", None)
            sanitized_dict["metadata"].pop("generation", None)
            sanitized_dict["metadata"].pop("creationTimestamp", None)
        if "status" in sanitized_dict:
            sanitized_dict.pop("status", None)

        return str(yaml.dump(sanitized_dict, sort_keys=False, indent=2))

    async def _get_resource_details(self) -> Any:
        """A generic function to get details for any Kubernetes resource."""
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not isinstance(resource_meta, dict):
            raise ValueError(
                f"Viewing YAML for resource kind '{self.resource_kind}' is not supported."
            )

        api_client_attr = resource_meta["api_client_attr"]
        if not isinstance(api_client_attr, str):
            raise TypeError("Expected api_client_attr to be a string")
        api_client = getattr(self.client, api_client_attr, None)
        if not api_client:
            raise ValueError(f"API client '{api_client_attr}' not found.")

        read_method_name = resource_meta["read_method"]
        if not isinstance(read_method_name, str):
            raise TypeError("Expected read_method to be a string")

        api_method = getattr(api_client, read_method_name, None)
        if not callable(api_method):
            raise ValueError(f"API method '{read_method_name}' not found.")

        kwargs: dict[str, Any] = {"name": self.resource_name}
        if resource_meta["is_namespaced"]:
            kwargs["namespace"] = self.namespace

        return await api_method(**kwargs)
