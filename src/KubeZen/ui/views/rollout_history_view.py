from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import yaml
import json
import shlex

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals
from KubeZen.core.user_input_manager import InputSpec
from KubeZen.core.exceptions import UserInputCancelledError


class RolloutHistoryView(BaseUIView):
    """
    A view to display the rollout history of a deployment and allow rollback.
    """
    VIEW_TYPE = "RolloutHistoryView"

    def __init__(self, navigation_coordinator, context: Optional[Dict[str, Any]] = None):
        super().__init__(navigation_coordinator, context)
        self.deployment_name = self.context.get("deployment_name", "Unknown")
        self.namespace = self.context.get("namespace", "Unknown")
        self.revision_details = self.context.get("revision_details", [])

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        items = []
        for item in self.revision_details:
            items.append(
                self.fzf_formatter.format_item(
                    action_code=str(item["revision"]),
                    display_name=f"{item['revision']:<10}{item['change_cause']}",
                    icon="📜"
                )
            )

        header = f"Rollout history for Deployment '{self.deployment_name}'. Select revision for details."
        prompt = f"Rollback {self.deployment_name} > "
        
        fzf_options = {
            "prompt": prompt, 
            "header": header,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_name: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        
        selected_revision = int(action_code)

        # Confirm the rollback
        try:
            prompt = f"Roll back Deployment '{self.deployment_name}' to revision {selected_revision}? (y/n): "
            spec = InputSpec(result_key="confirmation", prompt_message=prompt)
            results = await self.app_services.user_input_manager.get_multiple_inputs(
                specs=[spec], task_name="Confirm Rollback"
            )
            if results.get("confirmation", "n").lower() != "y":
                raise UserInputCancelledError("User did not confirm rollback.")

        except UserInputCancelledError:
            await self.app_services.tmux_ui_manager.show_toast("Rollback cancelled.", bg_color="blue")
            return signals.StaySignal()

        # Execute the rollback
        try:
            await self.app_services.kubernetes_client.rollback_deployment_to_revision(
                namespace=self.namespace,
                name=self.deployment_name,
                revision=selected_revision,
            )
            await self.app_services.tmux_ui_manager.show_toast(
                f"Rollback to revision {selected_revision} initiated for '{self.deployment_name}'.",
                bg_color="green",
            )
        except Exception as e:
            await self.app_services.tmux_ui_manager.show_toast(f"Rollback failed: {e}", bg_color="red")

        return signals.PopViewSignal() 