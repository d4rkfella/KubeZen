from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING, Tuple, List

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals
from KubeZen.ui.view_managers import FZFItemFormatter

if TYPE_CHECKING:
    # from KubeZen.core.app_services import AppServices # F401 unused
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator


class PortForwardView(BaseUIView):
    VIEW_TYPE = "PortForwardView"
    ERROR_FETCHING_ACTION_CODE = "error_fetching"
    ERROR_FETCHING_ICON = "🔥"
    SELECT_PORT_FORWARD_PROMPT = "Select Port Forward>"
    DEFAULT_HEADER = "Active Port Forwards"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(navigation_coordinator, context)
        action_context = self.context.get("original_action_context", {})
        custom_data = action_context.get("custom_data", {})
        self._provider_method = custom_data.get("provider")
        self.header = custom_data.get("header", self.DEFAULT_HEADER)
        self.fzf_formatter = FZFItemFormatter(self.get_view_session_id())

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        self.logger.debug("PortForwardView: Entered get_fzf_configuration.")
        items = []

        if not self._provider_method:
            error_msg = "No provider available for port forwards"
            self.logger.error(error_msg)
            items.append(
                self.fzf_formatter.format_item(
                    self.ERROR_FETCHING_ACTION_CODE, error_msg, self.ERROR_FETCHING_ICON
                )
            )
        else:
            try:
                port_forwards = self._provider_method(self.app_services)
                if not isinstance(port_forwards, list):
                    port_forwards = []
                self.logger.debug(
                    "PortForwardView: Provider returned {} port forwards.".format(
                        len(port_forwards)
                    )
                )

                if not port_forwards:
                    items.append(
                        self.fzf_formatter.format_item("no_pfs", "No active port forwards.")
                    )
                else:
                    for i, pf_obj in enumerate(port_forwards):
                        self.logger.debug(f"PortForwardView: Processing pf_obj #{i}")
                        action_code = None
                        display_text = None
                        if isinstance(pf_obj, dict):
                            action_code = pf_obj.get("metadata", {}).get("name")
                            display_text = pf_obj.get("spec", {}).get("display_text")
                        elif hasattr(pf_obj, "metadata") and hasattr(pf_obj.metadata, "name"):
                            action_code = pf_obj.metadata.name
                            if hasattr(pf_obj, "spec") and hasattr(pf_obj.spec, "display_text"):
                                display_text = pf_obj.spec.display_text
                        if action_code and display_text:
                            self.logger.debug(
                                f"PortForwardView: Extracted port forward name: {action_code}, display: {display_text}"
                            )
                            items.append(self.fzf_formatter.format_item(action_code, display_text))
                        else:
                            self.logger.warning(
                                f"PortForwardView: Found port forward object #{i} with missing metadata or display text: {pf_obj}"
                            )
            except Exception as e:
                self.logger.error(
                    f"PortForwardView: Exception during port forward fetching/processing: {e}",
                    exc_info=True,
                )
                error_item_text = f"Error fetching port forwards: {str(e)[:50]}"
                items.append(
                    self.fzf_formatter.format_item(
                        self.ERROR_FETCHING_ACTION_CODE,
                        error_item_text,
                        icon=self.ERROR_FETCHING_ICON,
                    )
                )

        self.logger.debug(
            f"PortForwardView: Final FZF items list (count: {len(items)}) before returning. First 5: {items[:5]}"
        )
        fzf_options = {
            "prompt": self.SELECT_PORT_FORWARD_PROMPT,
            "header": self.header,
            "preview": None,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.debug(f"{self.VIEW_TYPE}: Processing selection action_code: '{action_code}'")
        if action_code.isdigit():
            result = {"selected_remote_port": int(action_code)}
            return signals.ToParentWithResultSignal(result=result, context=self.context)
        elif action_code == self.GO_BACK_ACTION_CODE:
            return signals.PopViewSignal()
        else:
            self.logger.warning(f"Action '{display_text}' not implemented in PortForwardView.")
        return signals.StaySignal(context=self.context)
