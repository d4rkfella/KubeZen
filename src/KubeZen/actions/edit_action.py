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


class EditResourceAction(BaseAction):
    """
    A generic action to edit a Kubernetes resource using 'kubectl edit'.
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
        Constructs and runs 'kubectl edit' in a new tmux window.
        """
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not resource_meta:
            log.error(f"Unknown resource kind '{self.resource_kind}' for edit action.")
            return

        # Use the lowercase 'kind' for kubectl commands (e.g., "pod", "deployment")
        kubectl_resource_type = resource_meta["kind"].lower()

        command = f"kubectl edit {kubectl_resource_type} {self.resource_name}"
        if self.namespace:
            command += f" --namespace {self.namespace}"

        window_name = f"edit-{self.resource_name}"
        log.info(f"Launching kubectl edit with command: {command}")

        try:
            output = await self.tmux_manager.launch_command_and_capture_output(
                command, window_name=window_name, attach=True
            )

            log.info(f"Captured output from kubectl edit: >>>\n{output}\n<<<")

            # kubectl edit prints "no changes" to stdout if the file is not modified
            if "no changes" in output.lower():
                self.app.notify(
                    f"Edit cancelled, no changes made to '{self.resource_name}'.",
                    title="Edit Cancelled",
                )
                return

            log.info(
                f"'kubectl edit' for '{self.resource_name}' completed with changes."
            )
            self.app.notify(
                f"✅ Resource '{self.resource_name}' may have been updated.",
                title="Edit Complete",
                timeout=5,
            )
            # After editing, we should refresh the screen to show changes.
            # Popping the ActionScreen will achieve this for now.
            self.app.pop_screen()
            # TODO: Add a more robust refresh mechanism.
        except Exception as e:
            message = f"Failed to execute 'kubectl edit'. Error: {e}"
            log.error("Failed to execute 'kubectl edit'", exc_info=True)
            self.app.notify(message, title="Error", severity="error", timeout=10)
