from __future__ import annotations
from typing import Optional, Dict, Any

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import (
    ActionFailedError,
    ActionCancelledError,
    UserInputCancelledError,  # To catch direct cancellation of the input prompt
    UserInputFailedError,  # If the input mechanism itself fails
    TmuxCommandFailedError,  # Though less likely here unless wrapped, good practice
    TmuxCommandInterruptedError,
    TmuxEnvironmentError,
)
from KubeZen.core.signals import PopViewSignal, NavigationSignal
from KubeZen.core.user_input_manager import InputSpec


class DeleteResourceAction(Action):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        return context.raw_k8s_object is not None

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        """
        Executes the delete action.
        Returns a PopViewSignal if deletion was successfully initiated.
        Raises ActionCancelledError if the user cancels the operation.
        Raises ActionFailedError for other failures.
        """
        resource_name = resource.get("metadata", {}).get("name")
        resource_kind = resource.get("kind")
        resource_display_name = resource_name  # Fallback or primary identifier
        action_name = self.__class__.__name__

        # Since is_applicable should have already run, we can assume these exist.
        namespace_for_command = resource.get("metadata", {}).get("namespace")
        if not namespace_for_command:
            msg = f"{action_name}: Namespace not available in context, cannot delete {resource_kind} '{resource_name}'."
            context.logger.error(msg)
            raise ActionFailedError("Namespace not found in context.")

        context.logger.debug(
            f"{action_name}: Initiating 'Delete' for {resource_kind} '{resource_name}' in namespace '{namespace_for_command}'"
        )

        # Create a validator function
        def validate_confirmation(input_str: str):
            if input_str != resource_name:
                raise ValueError(f"Input must match '{resource_name}'.")

        try:
            prompt = f"To confirm deletion, please type the resource name '{resource_name}': "
            spec = InputSpec(
                result_key="confirmation",
                prompt_message=prompt,
                validator=validate_confirmation,
                validation_error_message="Confirmation failed.",
            )
            
            await context.user_input_manager.get_multiple_inputs(
                specs=[spec], task_name="Confirm Deletion"
            )

            context.logger.info("User confirmed deletion. Proceeding...")

            # --- API Call to Delete ---
            if not context.kubernetes_client:
                raise ActionFailedError("KubernetesClient not available, cannot delete.")

            try:
                await context.kubernetes_client.delete_namespaced_resource(
                    resource_type_str=str(resource_kind),
                    name=resource_name,
                    namespace=namespace_for_command,
                )
            except TmuxCommandFailedError as e:
                context.logger.error(f"{action_name}: Tmux command failed during delete: {e}")
                raise ActionFailedError(f"Failed to execute delete command: {str(e)}")
            except TmuxCommandInterruptedError:
                context.logger.info(f"{action_name}: Delete command was interrupted")
                raise ActionCancelledError("Delete operation was interrupted")
            except TmuxEnvironmentError as e:
                context.logger.error(f"{action_name}: Tmux environment error: {e}")
                raise ActionFailedError(f"Tmux environment error: {str(e)}")

            await context.tmux_ui_manager.show_toast(
                f"Deletion of {resource_display_name} initiated.", bg_color="green", duration=5
            )
            return PopViewSignal()

        except (UserInputCancelledError, UserInputFailedError):
            await context.tmux_ui_manager.show_toast(
                "Delete action cancelled.", duration=3
            )
            return
        except Exception as e:
            context.logger.error(
                f"{action_name}: Unexpected error during delete: {e}", exc_info=True
            )
            raise ActionFailedError(
                f"Unexpected error deleting {resource_kind}/{resource_name}."
            ) from e
