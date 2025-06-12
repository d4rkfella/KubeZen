from __future__ import annotations
from typing import Optional, Dict, Any

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import ActionFailedError, UserInputCancelledError
from KubeZen.core.signals import NavigationSignal, StaySignal, PopViewSignal
from KubeZen.core.user_input_manager import InputSpec


def validate_is_non_negative_int(input_str: str) -> None:
    """Validator to ensure input is a non-negative integer."""
    if not input_str.isdigit():
        raise ValueError("Input must be a whole number.")
    if int(input_str) < 0:
        raise ValueError("Input cannot be negative.")


class ScaleWorkloadAction(Action):
    """
    An action to scale a workload resource (Deployment, StatefulSet, ReplicaSet)
    to a specified number of replicas.
    """

    APPLICABLE_KINDS = {"Deployment", "StatefulSet", "ReplicaSet"}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        """
        This action is applicable if the resource kind is one of the scalable
        workload types.
        """
        resource_kind = (
            context.raw_k8s_object.get("kind") if context.raw_k8s_object else None
        )
        return resource_kind in self.APPLICABLE_KINDS

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        """
        Prompts the user for the number of replicas and scales the workload.
        """
        resource_name = resource.get("metadata", {}).get("name")
        resource_kind = resource.get("kind")
        namespace = resource.get("metadata", {}).get("namespace")
        current_replicas = resource.get("spec", {}).get("replicas", "N/A")

        if not all([resource_name, resource_kind, namespace]):
            raise ActionFailedError("Resource metadata is incomplete.")

        # 1. Prompt for new replica count using UserInputManager
        try:
            prompt = f"Enter new replica count for {resource_kind} '{resource_name}' (current: {current_replicas}):"
            spec = InputSpec(
                result_key="replicas",
                prompt_message=prompt,
                validator=validate_is_non_negative_int,
                validation_error_message="Please enter a non-negative number.",
            )

            results = await context.user_input_manager.get_multiple_inputs(
                specs=[spec], task_name="Scale Workload"
            )

            replica_str = results.get("replicas")
            if replica_str is None:
                raise UserInputCancelledError("Scale action cancelled by user.")

            new_replicas = int(replica_str)

        except UserInputCancelledError:
            await context.tmux_ui_manager.show_toast(
                "Scale action cancelled.", bg_color="blue"
            )
            return StaySignal()
        except Exception as e:
            raise ActionFailedError(f"Failed to get user input: {e}") from e

        # 2. Call Kubernetes API to scale the resource
        try:
            await context.kubernetes_client.scale_resource(
                resource_type=resource_kind,
                namespace=namespace,
                name=resource_name,
                replicas=new_replicas,
            )
            await context.tmux_ui_manager.show_toast(
                f"Successfully scaled {resource_kind} '{resource_name}' to {new_replicas} replicas.",
                bg_color="green",
            )
        except Exception as e:
            error_message = f"Failed to scale {resource_kind} '{resource_name}': {e}"
            context.logger.error(error_message, exc_info=True)
            await context.tmux_ui_manager.show_toast(error_message, bg_color="red")
            raise ActionFailedError(error_message) from e

        return PopViewSignal() 