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
        resource_name = resource.get("metadata", {}).get("name")
        namespace = resource.get("metadata", {}).get("namespace")

        if not resource_name or not namespace:
            raise ActionFailedError("Resource name or namespace is missing.")

        try:
            initial_yaml = await context.kubernetes_client.get_resource_as_yaml(
                resource_type=str(resource.get("kind")),
                namespace=namespace,
                name=resource_name,
            )
            if not initial_yaml:
                raise ActionFailedError("Could not retrieve resource YAML.")

            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".yaml"
            ) as tmp_file:
                tmp_file.write(initial_yaml)
                file_path = tmp_file.name

            while True:
                if not await context.tmux_ui_manager.launch_editor(file_path):
                    raise UserInputCancelledError("Editor was closed or failed to launch.")

                # The edited content is now in file_path. We can use it directly.
                try:
                    command = ["kubectl", "apply", "-f", file_path]
                    result = await context.tmux_ui_manager.launch_command_in_new_window(
                        command_str=command,
                        window_name=f"apply-{resource_name}",
                        attach=False,
                        wait_for_completion=True,
                    )

                    output = result.get("output", "") if result else ""
                    
                    # Check for success keywords in kubectl output.
                    if "unchanged" in output or "configured" in output or "created" in output:
                        await context.tmux_ui_manager.show_toast(
                            f"Successfully applied changes to {resource_name}.",
                            bg_color="green",
                        )
                        break # Exit loop on success
                    else:
                        # If no success keyword, assume failure and show output.
                        error_message = output.strip().split("\n")[-1] # Get last line of error
                        raise ActionFailedError(error_message)

                except (ActionFailedError, TmuxOperationError) as e:
                    await context.tmux_ui_manager.show_toast(
                        f"Error applying changes: {e}", bg_color="red", duration=8
                    )
                    
                    re_edit_spec = InputSpec(
                        result_key="re_edit",
                        prompt_message="Apply failed. Re-edit the file? (y/n): ",
                        default_value="y",
                        validator=validate_yes_no,
                        validation_error_message="Invalid choice."
                    )
                    results = await context.user_input_manager.get_multiple_inputs([re_edit_spec])
                    re_edit = results.get("re_edit", "n")

                    if re_edit.lower() in ["n", "no"]:
                        break  # Exit loop if user chooses not to re-edit
                    # Otherwise, the loop continues for another edit attempt

        except (UserInputCancelledError, UserInputFailedError):
            await context.tmux_ui_manager.show_toast("Edit action cancelled.", duration=3)
        finally:
            if "file_path" in locals() and os.path.exists(file_path):
                os.remove(file_path)

            return StaySignal()
