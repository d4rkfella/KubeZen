from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.core import NodeRow
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
import logging
import os

log = logging.getLogger(__name__)


@supports_resources("nodes")
class TalosEditConfigAction(BaseAction):
    name = "Edit Talos Config"

    def can_perform(self, row_info: NodeRow) -> bool:
        """
        Only enable this action if the node's OS is Talos.
        """
        return "talos" in row_info.os.lower()

    async def execute(self, row_info: NodeRow) -> None:
        talos_config = os.environ.get("TALOSCONFIG")
        command = "talosctl edit machineconfig"
        if talos_config:
            command += f" --talosconfig {talos_config}"
        window_name = f"edit-{row_info.name}"

        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command, window_name=window_name
            )
        except Exception as e:
            log.error(
                "Failed to execute 'talosctl edit machineconfig': %s", e, exc_info=True
            )
            self.app.notify(
                f"❌ Failed to execute command for '{row_info.name}': {e}",
                title="Execution Error",
            )


@supports_resources("nodes")
class TalosRebootAction(BaseAction):
    name = "Reboot Talos Node"

    def can_perform(self, row_info: NodeRow) -> bool:
        return "talos" in row_info.os.lower()

    async def execute(self, row_info: NodeRow) -> None:
        prompt = f"Are you sure you want to reboot {row_info.kind} '{row_info.name}'?"

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
            command = f"talosctl reboot --nodes {row_info.name}"

            window_name = f"reboot-{row_info.name}"

            try:
                await self.app.tmux_manager.launch_command_in_new_window(
                    command=command, window_name=window_name
                )
            except Exception as e:
                log.error("Failed to execute 'talosctl reboot': %s", e, exc_info=True)
        else:
            self.app.notify(
                f"❌ Reboot cancelled for {row_info.kind} '{row_info.name}'",
                title="Info",
            )
