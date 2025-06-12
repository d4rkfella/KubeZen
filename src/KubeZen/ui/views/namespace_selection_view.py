from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals
from KubeZen.providers.namespace_provider import create_namespace_provider

if TYPE_CHECKING:
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator


class NamespaceSelectionView(BaseUIView):
    """Allows the user to select a Kubernetes namespace or 'all namespaces'."""

    ALL_NAMESPACES_CODE = "_ALL_NAMESPACES_"
    ALL_NAMESPACES_TEXT = "All Namespaces"
    SELECT_NAMESPACE_PROMPT = "Select Namespace > "
    DEFAULT_HEADER = "Namespaces"
    VIEW_TYPE = "NamespaceSelectionView"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(navigation_coordinator, context)
        self.provider_class = create_namespace_provider()
        self.logger.debug(f"Initialized with context: {self.context}")

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        self.logger.debug("NamespaceSelectionView: Entered get_fzf_configuration.")
        items = [
            self.fzf_formatter.format_item(
                self.ALL_NAMESPACES_CODE, self.ALL_NAMESPACES_TEXT, icon="🌐"
            )
        ]
        self.logger.debug(f"NamespaceSelectionView: Initial items list: {items}")

        if not self.provider_class:
            error_msg = "No provider available for namespaces"
            self.logger.error(error_msg)
            items.append(
                self.fzf_formatter.format_item(
                    self.ERROR_FETCHING_ACTION_CODE, error_msg, self.ERROR_FETCHING_ICON
                )
            )
        else:
            try:
                namespaces = self.provider_class.get_cached_items(self.app_services)
                self.logger.debug(
                    "NamespaceSelectionView: Provider returned {} namespaces.".format(
                        len(namespaces)
                    )
                )

                for i, ns_obj in enumerate(namespaces):
                    self.logger.debug(f"NamespaceSelectionView: Processing ns_obj #{i}")
                    if not ns_obj:
                        self.logger.warning(
                            f"NamespaceSelectionView: Found null namespace object at index {i}"
                        )
                        continue

                    ns_name = (
                        ns_obj.get("metadata", {}).get("name")
                        if isinstance(ns_obj, dict)
                        else getattr(getattr(ns_obj, "metadata", None), "name", None)
                    )

                    if ns_name:
                        self.logger.debug(
                            f"NamespaceSelectionView: Extracted namespace name: {ns_name}"
                        )
                        items.append(self.fzf_formatter.format_item(ns_name, ns_name, icon="📦"))
                    else:
                        self.logger.warning(
                            f"NamespaceSelectionView: Found namespace object #{i} with missing metadata or name: {ns_obj}"
                        )
            except Exception as e:
                self.logger.error(
                    f"NamespaceSelectionView: Exception during namespace fetching/processing: {e}",
                    exc_info=True,
                )
                error_item_text = f"Error fetching namespaces: {str(e)[:50]}"
                items.append(
                    self.fzf_formatter.format_item(
                        self.ERROR_FETCHING_ACTION_CODE,
                        error_item_text,
                        icon=self.ERROR_FETCHING_ICON,
                    )
                )

        self.logger.debug(
            f"NamespaceSelectionView: Final FZF items list (count: {len(items)}) before returning. First 5: {items[:5]}"
        )
        fzf_options = {
            "prompt": self.SELECT_NAMESPACE_PROMPT,
            "header": self.context.get("header", self.DEFAULT_HEADER),
            "preview": None,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.debug(
            f"NamespaceSelectionView: Processing selection - action_code: '{action_code}', display: '{display_text}'"
        )

        if action_code == self.ERROR_FETCHING_ACTION_CODE or action_code == "ERROR_NO_K8S_CLIENT":
            self.logger.warning("NamespaceSelectionView: Error item selected, staying in view.")
            return signals.StaySignal(context=self.context)

        selected_namespace = action_code if action_code != self.ALL_NAMESPACES_CODE else None

        self.app_services.set_current_namespace(selected_namespace)

        next_view_key = self.context.get("next_view_override", "ResourceTypeSelectionView")
        self.logger.debug(f"NamespaceSelectionView: next_view_key resolved to '{next_view_key}'")

        # Ensure we always go through ResourceTypeSelectionView
        if next_view_key == "ResourceListView":
            self.logger.warning(
                "NamespaceSelectionView: Attempted to navigate directly to ResourceListView. Forcing to ResourceTypeSelectionView."
            )
            next_view_key = "ResourceTypeSelectionView"

        new_context_for_next_view = {
            "selected_namespace": selected_namespace,
            "header_info": f"Namespace: {display_text}",
        }

        self.logger.debug(
            f"NamespaceSelectionView: Pushing next view '{next_view_key}' with context: {new_context_for_next_view}"
        )

        return signals.PushViewSignal(view_key=next_view_key, context=new_context_for_next_view)
