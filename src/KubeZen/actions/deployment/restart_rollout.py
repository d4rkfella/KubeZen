from __future__ import annotations
from typing import Optional, Dict, Any

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import ActionFailedError, UserInputCancelledError
from KubeZen.core.signals import NavigationSignal, PopViewSignal, StaySignal
from KubeZen.core.user_input_manager import InputSpec


def validate_yes_no(input_str: str) -> None:
    """Validator to ensure input is 'y' or 'n'."""
    if input_str.lower().strip() not in ["y", "n"]:
        raise ValueError("Please enter 'y' or 'n'.")


class RestartRolloutAction(Action):
    """
    An action to perform a rolling restart of a Deployment.
    """

    def is_applicable(self, context: ActionContext) -> bool:
        """
        This action is only applicable to Deployments.
        """
        resource_kind = (
            context.raw_k8s_object.get("kind") if context.raw_k8s_object else None
        )
        return resource_kind == "Deployment"

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        resource_name = resource.get("metadata", {}).get("name")
        namespace = resource.get("metadata", {}).get("namespace")

        if not all([resource_name, namespace]):
            raise ActionFailedError("Deployment metadata is incomplete.")

        # 1. Get confirmation from the user
        try:
            prompt = f"Are you sure you want to restart Deployment '{resource_name}'? (y/n): "
            spec = InputSpec(
                result_key="confirmation",
                prompt_message=prompt,
                validator=validate_yes_no,
            )
            results = await context.user_input_manager.get_multiple_inputs(
                specs=[spec], task_name="Confirm Restart"
            )
            if results.get("confirmation", "n").lower() != "y":
                raise UserInputCancelledError("User did not confirm restart.")

        except UserInputCancelledError:
            await context.tmux_ui_manager.show_toast(
                "Restart action cancelled.", bg_color="blue"
            )
            return StaySignal()

        # 2. Call Kubernetes API to trigger the restart
        try:
            await context.kubernetes_client.restart_deployment_rollout(
                namespace=namespace,
                name=resource_name,
            )
            await context.tmux_ui_manager.show_toast(
                f"Restart triggered for Deployment '{resource_name}'.",
                bg_color="green",
            )
        except Exception as e:
            error_message = f"Failed to restart Deployment '{resource_name}': {e}"
            context.logger.error(error_message, exc_info=True)
            await context.tmux_ui_manager.show_toast(error_message, bg_color="red")
            raise ActionFailedError(error_message) from e

        return PopViewSignal() 