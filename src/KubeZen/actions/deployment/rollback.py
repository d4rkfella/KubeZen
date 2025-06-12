from __future__ import annotations
from typing import Optional, Dict, Any

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import ActionFailedError
from KubeZen.core.signals import NavigationSignal, PushViewSignal, StaySignal
from KubeZen.ui.views.rollout_history_view import RolloutHistoryView


class RollbackAction(Action):
    """
    An action that displays the rollout history of a Deployment and allows
    the user to roll back to a specific revision.
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

        # 1. Fetch the rollout history from the Kubernetes client
        try:
            revision_details = await context.kubernetes_client.get_deployment_rollout_history(
                namespace=namespace,
                name=resource_name,
            )
            if not revision_details:
                await context.tmux_ui_manager.show_toast(
                    f"No rollout history found for Deployment '{resource_name}'.",
                    bg_color="blue",
                )
                return StaySignal()

        except Exception as e:
            error_message = f"Failed to get rollout history for '{resource_name}': {e}"
            context.logger.error(error_message, exc_info=True)
            await context.tmux_ui_manager.show_toast(error_message, bg_color="red")
            return StaySignal()

        # 2. Push the RolloutHistoryView with the history data
        view_context = {
            "deployment_name": resource_name,
            "namespace": namespace,
            "revision_details": revision_details,
        }
        return PushViewSignal(view_class=RolloutHistoryView, context=view_context) 