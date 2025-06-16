from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging

from .base_action import BaseAction
from ..screens.port_forward_screen import PortForwardScreen
from ..core.resource_registry import RESOURCE_REGISTRY, PortInfo

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp


log = logging.getLogger(__name__)


class PortForwardAction(BaseAction):
    """An action to port-forward to a pod or service."""

    def __init__(
        self,
        app: "KubeZenTuiApp",
        resource: dict[str, Any],
        object_name: str,
        resource_key: str,
    ):
        super().__init__(app, resource, object_name, resource_key)

    async def run(self) -> None:
        """Port-forward to a pod or service."""
        ports = self._get_ports()

        async def port_forward_callback(
            values: dict[str, str] | None,
        ) -> None:
            """Callback to handle the result from the port forward screen."""
            if not values:
                self.app.notify("Port forward cancelled.", title="Port Forward")
                return

            local_port = values.get("local_port")
            remote_port = values.get("remote_port")

            if not local_port or not remote_port:
                self.app.notify(
                    "Local and remote ports must be specified.",
                    title="Error",
                    severity="error",
                )
                return

            await self._execute_port_forward(local_port, remote_port)

        await self.app.push_screen(
            PortForwardScreen(target_name=self.resource_name, ports=ports),
            port_forward_callback,
        )

    async def _execute_port_forward(self, local_port: str, remote_port: str) -> None:
        """Constructs and executes the final kubectl port-forward command."""
        self.app.pop_screen()  # Pop the ActionScreen
        try:
            port_forward_command = (
                f"kubectl port-forward -n {self.namespace} "
                f"{self.resource_kind}/{self.resource_name} {local_port}:{remote_port}"
            )
            logging.info(f"Executing port-forward command: {port_forward_command}")

            if self.tmux_manager:
                await self.tmux_manager.launch_command_in_new_window(
                    command=port_forward_command,
                    window_name=f"port-forward-{self.resource_name}",
                    attach=True,
                )
            self.app.notify(
                f"Port forward to {self.resource_name} on {local_port}:{remote_port} established.",
                title="Port Forward",
            )
        except Exception as e:
            logging.error(f"Error during port-forward: {e}", exc_info=True)
            self.app.notify(
                f"Failed to port-forward to {self.resource_name}: {e}",
                title="Port Forward",
                severity="error",
            )

    def _get_ports(self) -> list[PortInfo]:
        """
        Extracts ports from a pod or service by using the provider
        from the resource registry.
        """
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not resource_meta:
            return []

        port_provider = resource_meta.get("port_forward_provider")
        if not port_provider:
            return []

        return port_provider(self.resource)
