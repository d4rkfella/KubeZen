from __future__ import annotations

from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals

if TYPE_CHECKING:
    from KubeZen.ui.navigation_coordinator import (
        NavigationCoordinator,
    )


class ContainerSelectionView(BaseUIView):
    """
    A simple view that prompts the user to select a container from a list
    and returns the selected container name to the parent view.
    """

    VIEW_TYPE = "ContainerSelectionView"
    SELECT_CONTAINER_PROMPT = "Select Container > "
    DEFAULT_HEADER = "Containers"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(navigation_coordinator, context)
        self.pod_name: Optional[str] = self.context.get("pod_name")
        self.namespace: Optional[str] = self.context.get("namespace")
        self.container_names: List[str] = self.context.get("container_names", [])

        if not all([self.pod_name, self.namespace, self.container_names]):
            self.logger.error(f"{self.VIEW_TYPE}: Missing critical context. Ctx: {self.context}")

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        self.logger.debug("ContainerSelectionView: Entered get_fzf_configuration.")
        items = []

        if not self.container_names:
            error_msg = "No containers found in pod"
            self.logger.warning(error_msg)
            items.append(
                self.fzf_formatter.format_item(
                    self.NO_ITEMS_ACTION_CODE, error_msg, self.NO_ITEMS_ICON
                )
            )
        else:
            try:
                for container_name in self.container_names:
                    items.append(
                        self.fzf_formatter.format_item(container_name, container_name, icon="📦")
                    )
            except Exception as e:
                self.logger.error(
                    f"ContainerSelectionView: Exception during container processing: {e}",
                    exc_info=True,
                )
                error_item_text = f"Error processing containers: {str(e)[:50]}"
                items.append(
                    self.fzf_formatter.format_item(
                        self.ERROR_FETCHING_ACTION_CODE,
                        error_item_text,
                        icon=self.ERROR_FETCHING_ICON,
                    )
                )

        self.logger.debug(
            f"ContainerSelectionView: Final FZF items list (count: {len(items)}) before returning. First 5: {items[:5]}"
        )
        fzf_options = {
            "prompt": self.SELECT_CONTAINER_PROMPT,
            "header": self.context.get("header", self.DEFAULT_HEADER),
            "preview": None,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        # action_code is the container name
        self.logger.info(
            f"Container '{action_code}' selected for pod '{self.namespace}/{self.pod_name}'."
        )
        result = {"selected_container_name": action_code}
        return signals.ToParentWithResultSignal(result=result, context=self.context)
