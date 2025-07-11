from __future__ import annotations
from typing import TYPE_CHECKING

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.base import UIRow
from KubeZen.models.core import ServiceRow, PodRow
from KubeZen.screens.port_forward_screen import PortForwardScreen, PortInfo


if TYPE_CHECKING:
    from ..app import KubeZenTuiApp


@supports_resources("pods", "services")
class PortForwardAction(BaseAction):
    """An action to port-forward to a resource."""

    name = "Port-forward"

    async def execute(self, row_info: UIRow) -> None:
        """Shows the port-forward screen and then executes the forward."""

        ports = []
        if isinstance(row_info, PodRow):
            ports = row_info.raw.spec.containers[0].ports
        elif isinstance(row_info, ServiceRow):
            ports = row_info.raw.spec.ports

        async def on_select(selected_ports: list[PortInfo] | None) -> None:
            if selected_ports:
                await self._start_port_forward(selected_ports)

        self.app.push_screen(
            PortForwardScreen(target_name=row_info.name, ports=ports), on_select
        )

    async def _start_port_forward(self, ports: list[PortInfo]) -> None:
        """Constructs and runs the kubectl port-forward command."""
        port_mappings = [
            f"{p.local_port}:{p.container_port}" for p in ports if p.local_port
        ]
        if not port_mappings:
            self.app.notify(
                "No ports selected for forwarding.", title="Error", severity="error"
            )
            return

        command = (
            f"kubectl port-forward {row_info.plural}/{row_info.name} "
            f"--namespace {row_info.namespace} {' '.join(port_mappings)}"
        )
        window_name = f"pf-{row_info.name}"

        try:
            # This command runs indefinitely, so it needs its own pane
            await self.app.tmux_manager.launch_command_in_new_window(
                command,
                window_name=window_name,
                attach=True,
            )
            self.app.notify(
                f"✅ Port-forward started for {row_info.name}",
                title="Success",
            )
        except Exception as e:
            self.app.notify(
                f"Failed to start port-forward: {e}",
                title="Error",
                severity="error",
            )
