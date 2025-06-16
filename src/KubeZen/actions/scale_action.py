from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable
import logging

from kubernetes_asyncio.client.exceptions import ApiException
from textual.widgets import Input

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

from .base_action import BaseAction
from ..core.resource_registry import RESOURCE_REGISTRY
from ..screens.confirmation_screen import ConfirmationScreen

log = logging.getLogger(__name__)


class ScaleResourceAction(BaseAction):
    """
    A generic action to scale any Kubernetes workload.
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
        Pushes a confirmation screen with an input for the number of replicas.
        """
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not resource_meta or not self.namespace:
            log.error(f"Cannot scale {self.resource_kind}, registry entry not found.")
            return

        api_client_attr = resource_meta["api_client_attr"]
        read_method_name = resource_meta["read_method"]
        api_client = getattr(self.client, api_client_attr)
        read_method = getattr(api_client, read_method_name)

        try:
            workload = await read_method(
                name=self.resource_name, namespace=self.namespace
            )
            current_replicas = workload.spec.replicas
        except ApiException as e:
            message = f"Failed to get resource details for scaling: {e.reason}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
            return
        except Exception as e:
            message = f"An unexpected error occurred while fetching resource: {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
            return

        await self.app.push_screen(
            ConfirmationScreen(
                title="Scale Resource",
                prompt=(
                    f"Enter new replicas for {self.resource_kind} "
                    f"'{self.resource_name}' (current: {current_replicas}):"
                ),
                callback=self._perform_scale,
                input_widget=Input(placeholder="Replicas", value=str(current_replicas)),
            )
        )

    async def _perform_scale(self, replicas: str) -> None:
        """Scales the resource after confirmation."""
        try:
            replicas_int = int(replicas)
            log.info(
                f"Attempting to scale {self.resource_kind} '{self.resource_name}' to {replicas_int} replicas"
            )
            patch_method = await self._get_patch_method()
            body = {"spec": {"replicas": replicas_int}}
            await patch_method(body=body)
            log.info(f"Successfully scaled {self.resource_kind} '{self.resource_name}'")
            self.app.notify(
                f"✅ Successfully scaled {self.resource_kind} '{self.resource_name}'.",
                title="Success",
                timeout=5,
            )
            # Pop the action and confirmation screens to return to the list
            self.app.pop_screen()
            self.app.pop_screen()
        except ValueError:
            self.app.notify(
                "Invalid input. Please enter a valid integer for replicas.",
                title="Error",
                severity="error",
                timeout=10,
            )
        except ApiException as e:
            message = f"Failed to scale {self.resource_kind} '{self.resource_name}'. Reason: {e.reason}"
            log.error(f"API error scaling resource: {e.reason}", exc_info=True)
            self.app.notify(message, title="Error", severity="error", timeout=10)
        except Exception as e:
            message = f"An unexpected error occurred: {e}"
            log.error(
                "An unexpected error occurred during resource scaling:", exc_info=True
            )
            self.app.notify(message, title="Error", severity="error", timeout=10)

    async def _get_patch_method(self) -> Callable[..., Any]:
        """A generic function to get the patch method for any Kubernetes resource."""
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not isinstance(resource_meta, dict):
            raise ValueError(
                f"Scaling resource kind '{self.resource_kind}' is not supported."
            )

        api_client_attr = resource_meta["api_client_attr"]
        if not isinstance(api_client_attr, str):
            raise TypeError("Expected api_client_attr to be a string")
        api_client = getattr(self.client, api_client_attr, None)
        if not api_client:
            raise ValueError(f"API client '{api_client_attr}' not found.")

        patch_method_name = resource_meta["patch_method"]
        if not isinstance(patch_method_name, str):
            raise TypeError("Expected patch_method to be a string")

        api_method = getattr(api_client, patch_method_name, None)
        if not callable(api_method):
            raise ValueError(f"API method '{patch_method_name}' not found.")

        kwargs: dict[str, Any] = {"name": self.resource_name}
        if resource_meta["is_namespaced"]:
            kwargs["namespace"] = self.namespace

        # We need to return a callable with the arguments already bound
        return lambda **patch_kwargs: api_method(**kwargs, **patch_kwargs)
