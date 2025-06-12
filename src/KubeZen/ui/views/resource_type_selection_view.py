from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

from KubeZen.ui.resource_type_registry import RESOURCE_TYPE_CONFIGS
from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals

if TYPE_CHECKING:
    pass


class ResourceTypeSelectionView(BaseUIView):
    """Allows the user to select a Kubernetes resource type to view."""

    VIEW_TYPE = "ResourceTypeSelectionView"
    SELECT_RESOURCE_TYPE_PROMPT = "Select Resource Type > "
    DEFAULT_HEADER = "Select a resource type to view"

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        self.logger.debug("ResourceTypeSelectionView: Entered get_fzf_configuration.")
        items = []

        for config in RESOURCE_TYPE_CONFIGS:
            items.append(
                self.fzf_formatter.format_item(
                    str(config["code"]),
                    str(config["display"]),
                    icon=str(config.get("icon")) if config.get("icon") else None,
                )
            )

        fzf_options = {
            "prompt": self.SELECT_RESOURCE_TYPE_PROMPT,
            "header": self.DEFAULT_HEADER,
            "preview": None,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.debug(
            f"ResourceTypeSelectionView: Processing selection - action_code: '{action_code}', display: '{display_text}', selection_context: {selection_context}"
        )
        self.logger.debug(
            f"ResourceTypeSelectionView: Current context before processing selection: {self.context}"
        )

        # Defensive: Only allow valid resource type codes
        valid_codes = {c["code"] for c in RESOURCE_TYPE_CONFIGS}
        if action_code not in valid_codes:
            self.logger.error(
                f"ResourceTypeSelectionView: Invalid resource type code selected: '{action_code}'. Staying in view."
            )
            return signals.StaySignal(context=self.context)

        selected_resource_type_code = action_code
        # Get the clean display name from the config
        selected_resource_config = next(
            (c for c in RESOURCE_TYPE_CONFIGS if c["code"] == action_code), None
        )
        selected_resource_display_name = (
            selected_resource_config["display"] if selected_resource_config else ""
        )

        self.logger.info(
            f"ResourceTypeSelectionView: Resource type '{selected_resource_type_code}' selected."
        )

        new_context_for_next_view = {
            "current_kubernetes_resource_type": selected_resource_type_code,
            "current_resource_display_name": selected_resource_display_name,
            "selected_namespace": self.app_services.current_namespace,
            "header_info": self.context.get(
                "header_info", f"Namespace: {self.app_services.current_namespace or 'All'}"
            ),
        }

        return signals.PushViewSignal(
            view_key="ResourceListView", context=new_context_for_next_view
        )
