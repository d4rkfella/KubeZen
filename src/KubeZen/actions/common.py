from __future__ import annotations

import re
from typing import TYPE_CHECKING
import logging
import asyncio
import yaml

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from KubeZen.utils.files import create_temp_file_and_get_command

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..models import UIRow


log = logging.getLogger(__name__)


@supports_resources("*")  # Describe works with all resource types
class DescribeAction(BaseAction):
    """An action to describe a Kubernetes resource."""

    name = "Describe"

    async def execute(self, row_info: UIRow) -> None:
        """Runs kubectl describe in a new tmux pane."""

        window_name = f"describe-{row_info.name}"
        existing_window = await self.app.tmux_manager.find_window(window_name)
        if existing_window:
            log.debug("Found existing window for %s. Selecting it.", window_name)
            await asyncio.to_thread(existing_window.select_window)
            return

        kubectl_resource_type = row_info.plural

        command = f"kubectl describe {kubectl_resource_type} {row_info.name}"
        if row_info.namespace:
            command += f" --namespace {row_info.namespace}"

        command += " | less -R"
        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"describe-{row_info.name}",
                attach=True,
            )
        except Exception as e:
            log.error("Failed to execute describe command: %s", e, exc_info=True)
            self.app.notify(
                f"Failed to describe {row_info.name}",
                title="Error",
                severity="error",
            )


@supports_resources("*")
class ViewYamlAction(BaseAction):
    """An action to view the YAML of a Kubernetes resource."""

    name = "View YAML"

    async def execute(self, row_info: UIRow) -> None:
        """
        Fetches the resource YAML and displays it, reusing an existing window if possible.
        """
        try:
            window_name = f"yaml-{row_info.name}"

            existing_window = await self.app.tmux_manager.find_window(window_name)
            if existing_window:
                log.debug("Found existing window for %s. Selecting it.", window_name)
                await asyncio.to_thread(existing_window.select_window)
                return

            resource_data = row_info.raw
            if not resource_data:
                self.app.notify("Could not fetch resource.", severity="error")
                return

            sanitized_data = (
                self.app.kubernetes_client.sanitize_for_serialization(
                    resource_data
                )
            )
            yaml_content = yaml.dump(sanitized_data)

            command = create_temp_file_and_get_command(
                content=yaml_content,
                file_prefix=row_info.name,
            )

            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=window_name,
                attach=True,
            )
        except Exception as e:
            log.error("Failed to show YAML: %s", e, exc_info=True)
            self.app.notify(f"Failed to show YAML: {e}", severity="error")


@supports_resources("*")
class EditAction(BaseAction):
    """An action to edit a Kubernetes resource."""

    name = "Edit"
    _row_info: UIRow

    async def execute(self, row_info: UIRow) -> None:
        """Runs kubectl edit in a new tmux pane."""
        self._row_info = row_info

        temp_dir = self.app.config.paths.temp_dir
        command = (
            f"TMPDIR={temp_dir} kubectl edit {row_info.plural} {row_info.name}"
        )
        if row_info.namespace:
            command += f" --namespace {row_info.namespace}"

        window_name = f"edit-{row_info.name}"

        try:
            # Launch command and capture output
            output = await self.app.tmux_manager.launch_command_and_capture_output(
                command=command, window_name=window_name, attach=True
            )

            if "edit cancelled" in output.lower():
                self.app.notify("Edit cancelled, no changes made", title="Info")
            elif "edited" in output.lower() or "saved" in output.lower():
                self.app.notify(
                    f"✅ Successfully edited {row_info.kind} '{row_info.name}'",
                    title="Success",
                )

        except Exception as e:
            log.error("Failed to execute 'kubectl edit': %s", e, exc_info=True)
            self.app.notify(
                f"Failed to run edit for {row_info.name}",
                title="Error",
                severity="error",
            )


@supports_resources("*")
class DeleteAction(BaseAction):
    """An action to delete a Kubernetes resource."""

    name = "Delete"
    _row_info: UIRow

    async def execute(self, row_info: UIRow) -> None:
        self._row_info = row_info
        """Show confirmation screen and delete if confirmed."""
        log.debug(
            "Starting delete action for %s %s", row_info.kind, row_info.name
        )

        namespace_text = (
            f" in namespace '{row_info.namespace}'"
            if row_info.namespace
            else ""
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
                delete_method, kwargs = self.app.kubernetes_client.get_api_method_for_resource(
                    model_class=self._row_info.__class__,  # Pass the class of the resource model
                    action="delete",
                    namespace=self._row_info.namespace
                )

                kwargs["name"] = self._row_info.name

                await delete_method(**kwargs)

                self.app.notify(f"Successfully deleted {self._row_info.kind} '{self._row_info.name}'")

            except Exception as e:
                log.error(f"Failed to delete {self._row_info.kind} '{self._row_info.name}': {e}", exc_info=True)
                self.app.notify(f"Error deleting resource: {e}", severity="error")
