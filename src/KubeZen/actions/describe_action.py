from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

from .base_action import BaseAction
from ..core.resource_registry import RESOURCE_REGISTRY

log = logging.getLogger(__name__)


class DescribeResourceAction(BaseAction):
    """
    A generic action to describe a Kubernetes resource using 'kubectl describe'.
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
        Constructs and runs 'kubectl describe' in a new tmux window,
        piping the output to a pager like 'less'.
        """
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not resource_meta:
            log.error(
                f"Unknown resource kind '{self.resource_kind}' for describe action."
            )
            return

        # Use the lowercase 'kind' for kubectl commands (e.g., "pod", "deployment")
        kubectl_resource_type = resource_meta["kind"].lower()

        command = f"kubectl describe {kubectl_resource_type} {self.resource_name}"
        if self.namespace:
            command += f" --namespace {self.namespace}"

        # Pipe the output to less for comfortable viewing
        command_with_pager = f"{command} | less"

        window_name = f"describe-{self.resource_name}"
        log.info(f"Launching kubectl describe with command: {command_with_pager}")

        try:
            # We don't need to wait, just display the output
            await self.tmux_manager.launch_command_in_new_window(
                command_with_pager, window_name=window_name, attach=True
            )
        except Exception:
            log.error("Failed to execute 'kubectl describe'", exc_info=True)
            # TODO: Show error to user.
