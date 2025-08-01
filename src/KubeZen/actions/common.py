from __future__ import annotations

import logging

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from KubeZen.models.base import UIRow

log = logging.getLogger(__name__)


@supports_resources("*")  # Describe works with all resource types
class DescribeAction(BaseAction[UIRow]):
    """An action to describe a Kubernetes resource."""

    name = "Describe"

    async def execute(self, row_info: UIRow) -> None:
        """Runs kubectl describe in a new tmux pane."""

        command = f"kubectl describe {row_info.plural} {row_info.name}"
        if row_info.namespace:
            command += f" --namespace {row_info.namespace}"

        command += " | less -R"
        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"describe-{row_info.name}",
            )
        except Exception as e:
            log.error("Failed to execute describe command: %s", e, exc_info=True)
            self.app.notify(
                f"Failed to describe {row_info.name}",
                title="Error",
                severity="error",
            )


@supports_resources("*")
class ViewYamlAction(BaseAction[UIRow]):
    """An action to view the YAML representation of a Kubernetes resource."""

    name = "View YAML"

    async def execute(self, row_info: UIRow) -> None:

        command = f"kubectl get {row_info.plural} {row_info.name} -o yaml"
        if row_info.namespace:
            command += f" --namespace {row_info.namespace}"
        command += " | less -R"

        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"view-yaml-{row_info.name}",
            )
        except Exception as e:
            log.error("Failed to execute get command: %s", e, exc_info=True)
            self.app.notify(
                f"Failed to get resource {row_info.name}",
                title="Error",
                severity="error",
            )


@supports_resources("*")
class EditAction(BaseAction[UIRow]):
    """An action to edit a Kubernetes resource."""

    name = "Edit"

    async def execute(self, row_info: UIRow) -> None:
        """Runs kubectl edit in a new tmux pane."""
        row_info = row_info

        command = f"kubectl edit {row_info.plural} {row_info.name}"
        if row_info.namespace:
            command += f" --namespace {row_info.namespace}"

        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"edit-{row_info.name}",
            )

        except Exception as e:
            log.error("Failed to execute 'kubectl edit': %s", e, exc_info=True)
            self.app.notify(
                f"Failed to run edit for {row_info.name}",
                title="Error",
                severity="error",
            )


@supports_resources("*")
class DeleteAction(BaseAction[UIRow]):
    """An action to delete a Kubernetes resource."""

    name = "Delete"

    async def execute(self, row_info: UIRow) -> None:
        row_info = row_info
        """Show confirmation screen and delete if confirmed."""
        log.debug("Starting delete action for %s %s", row_info.kind, row_info.name)

        namespace_text = (
            f" in namespace '{row_info.namespace}'" if row_info.namespace else ""
        )
        prompt = f"Are you sure you want to delete {row_info.kind} '{row_info.name}'{namespace_text}?"

        buttons = [
            ButtonInfo(label="Delete", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]

        screen = ConfirmationScreen(
            title="Confirm Deletion",
            prompt=prompt,
            buttons=buttons,
        )

        confirmed = await self.app.push_screen_wait(screen)

        if confirmed:
            try:
                delete_method, kwargs = (
                    self.app.kubernetes_client.get_api_method_for_resource(
                        model_class=row_info.__class__,  # Pass the class of the resource model
                        action="delete",
                        namespace=row_info.namespace,
                    )
                )

                kwargs["name"] = row_info.name

                await delete_method(**kwargs)

                self.app.notify(
                    f"Successfully deleted {row_info.kind} '{row_info.name}'"
                )

            except Exception as e:
                log.error(
                    f"Failed to delete {row_info.kind} '{row_info.name}': {e}",
                    exc_info=True,
                )
                self.app.notify(f"Error deleting resource: {e}", severity="error")
