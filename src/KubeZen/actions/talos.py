from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.core import NodeRow
from KubeZen.models.base import UIRow
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
import logging
import os
from typing import cast

log = logging.getLogger(__name__)


@supports_resources("nodes")
class TalosEditConfigAction(BaseAction):
    name = "Edit Talos Config"

    _row_info: UIRow

    def can_perform(self, row_info: UIRow) -> bool:
        """
        Only enable this action if the node's OS is Talos.
        """
        # The 'supports_resources' decorator and the __init__ assert ensure
        # that this method will only be called with a NodeRow.
        node_info = cast(NodeRow, row_info)
        return "talos" in node_info.os.lower()

    async def execute(self, row_info: UIRow) -> None:
        self._row_info = row_info
        
        talos_config = os.environ.get("TALOSCONFIG")
        command = f"talosctl edit machineconfig"
        if talos_config:
            command += f" --talosconfig {talos_config}"
        window_name = f"edit-{self._row_info.name}"

        try:
            output = await self.app.tmux_manager.launch_command_and_capture_output(
                command=command, window_name=window_name, attach=True
            )

            if "edit cancelled" in output.lower():
                self.app.notify("Edit cancelled, no changes made.", title="Info")
            elif "edited" in output.lower() or "saved" in output.lower():
                self.app.notify(
                    f"✅ Successfully edited {self._row_info.kind} '{self._row_info.name}'",
                    title="Success",
                )
            elif "command not found" in output.lower():
                self.app.notify(
                    "❌ Command 'talosctl' not found. Is it installed and in your PATH?",
                    title="Error: Command Not Found",
                )
            else:
                self.app.notify(
                    f"❌ Failed to edit {self._row_info.kind} '{self._row_info.name}': {output.strip()}",
                    title="Error",
                )

        except Exception as e:
            log.error(
                "Failed to execute 'talosctl edit machineconfig': %s", e, exc_info=True
            )
            self.app.notify(
                f"❌ Failed to execute command for '{self.row_info.name}': {e}",
                title="Execution Error",
            )


@supports_resources("nodes")
class TalosRebootAction(BaseAction):
    name = "Reboot Talos Node"

    _row_info: UIRow

    def can_perform(self, row_info: UIRow) -> bool:
        node_info = cast(NodeRow, row_info)
        return "talos" in node_info.os.lower()

    async def execute(self, row_info: UIRow) -> None:
        self._row_info = row_info

        prompt = f"Are you sure you want to reboot {self._row_info.kind} '{self._row_info.name}'?"

        buttons = [
            ButtonInfo(label="Reboot", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]

        screen = ConfirmationScreen(
            title="Confirm Deletion",
            prompt=prompt,
            buttons=buttons,
        )

        confirmed = await self.app.push_screen_wait(screen)

        if confirmed:
            command = f"talosctl reboot --nodes {self._row_info.name}"

            window_name = f"reboot-{self._row_info.name}"

            try:
                output = await self.app.tmux_manager.launch_command_and_capture_output(
                    command=command, window_name=window_name, attach=True
                )

                if "rebooted" in output.lower():
                    self.app.notify(
                        f"✅ Successfully rebooted {self._row_info.kind} '{self._row_info.name}'",
                        title="Success",
                    )
                else:
                    self.app.notify(
                        f"❌ Failed to reboot {self._row_info.kind} '{self._row_info.name}': {output.strip()}",
                        title="Error",
                    )
            except Exception as e:
                log.error("Failed to execute 'talosctl reboot': %s", e, exc_info=True)
        else:
            self.app.notify(
                f"❌ Reboot cancelled for {self.row_info.kind} '{self.row_info.name}'",
                title="Info",
            )
