from __future__ import annotations
import os
import yaml
import tempfile
from typing import Optional, Dict, Any, TYPE_CHECKING
from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.core.user_input_manager import InputSpec
from KubeZen.core.exceptions import (
    ActionFailedError,
    UserInputCancelledError,
    UserInputFailedError,
    TmuxOperationError,
)
import shlex

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


def validate_yes_no(input_str: str) -> None:
    """Validator to ensure input is 'y' or 'n'."""
    if input_str.lower().strip() not in ["y", "n", "yes", "no"]:
        raise ValueError("Please enter 'y' or 'n'.")


class EditResourceAction(Action):
    def is_applicable(self, context: ActionContext) -> bool:
        resource = context.raw_k8s_object
        return bool(resource and resource.get("kind"))

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        resource_kind = resource.get("kind")
        metadata = resource.get("metadata", {})
        resource_name = metadata.get("name")
        namespace = metadata.get("namespace")

        if not all([resource_kind, resource_name, namespace]):
            raise ActionFailedError("Resource kind, name, or namespace is missing.")

        try:
            # Check if a custom vim configuration is available. If so, we build a
            # command that sets all necessary environment variables for `kubectl edit`.
            vim_path = self.app_services.config.vim_path
            vim_config_path = self.app_services.config.vim_config_path

            if vim_path and vim_config_path:
                # Define the editor command for the KUBE_EDITOR variable.
                editor_command = f"'{vim_path}' -u '{vim_config_path}'"

                # Define all environment variables that need to be set for the command.
                env = {
                    "KUBE_EDITOR": editor_command,
                    "KUBEZEN_FZF_BASE_PLUGIN_DIR": str(self.app_services.config.fzf_base_plugin_path),
                    "KUBEZEN_FZF_VIM_COMMANDS_PLUGIN_DIR": str(self.app_services.config.fzf_vim_plugin_path),
                    "KUBEZEN_FZF_VIM_COMMANDS_BIN_DIR": str(self.app_services.config.fzf_path.parent),
                }

                # Format the env vars into 'VAR="value" VAR2="value2" ...'
                env_prefix = " ".join([f"{key}=\"{value}\"" for key, value in env.items()])
                
                command = (
                    f"{env_prefix} "
                    f"kubectl edit {shlex.quote(str(resource_kind))} "
                    f"{shlex.quote(str(resource_name))} --namespace {shlex.quote(str(namespace))}"
                )
            else:
                # Fallback to the default kubectl edit behavior.
                command = (
                    f"kubectl edit {shlex.quote(str(resource_kind))} "
                    f"{shlex.quote(str(resource_name))} --namespace {shlex.quote(str(namespace))}"
                )

            # This opens the user's editor. We make it non-blocking. The user can switch
            # back to KubeZen while the editor is open. The window will close automatically
            # when the editor is exited.
            await context.tmux_ui_manager.launch_command_in_new_window(
                command_str=command,
                window_name=f"Edit-{resource_name}",
                attach=True,
                wait_for_completion=False,
            )
        except TmuxOperationError as e:
            # This catches errors in launching the command itself.
            await context.tmux_ui_manager.show_toast(
                f"Failed to launch editor: {e}", bg_color="red", duration=8
            )

        return StaySignal()
