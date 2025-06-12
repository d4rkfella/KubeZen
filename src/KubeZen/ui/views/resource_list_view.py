from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple, cast, Callable

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals
from KubeZen.ui.resource_type_registry import RESOURCE_TYPE_CONFIGS
from KubeZen.ui.resource_formatters import ResourceFormatterRegistry

if TYPE_CHECKING:
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator


class ResourceListView(BaseUIView):
    """Displays a list of Kubernetes resources of a specific type."""

    DEFAULT_PROMPT_TEMPLATE = "Select {resource_display_name} > "
    DEFAULT_HEADER_TEMPLATE = "{resource_display_name} in namespace {namespace_display}"
    VIEW_TYPE = "ResourceListView"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(navigation_coordinator, context)
        self._current_raw_items: List[Dict[str, Any]] = []
        self.logger.debug(f"Initialized with context: {self.context}")

    def _get_provider_method(self) -> Optional[Callable[..., List[Dict[str, Any]]]]:
        """
        Gets the appropriate data provider method for the resource type.
        """
        resource_kind = self.context.get("current_kubernetes_resource_type")
        if not resource_kind:
            self.logger.error("No resource kind specified in context")
            return None

        # Find the config for this resource type
        config = next((c for c in RESOURCE_TYPE_CONFIGS if c["code"] == resource_kind), None)
        if not config:
            self.logger.error(f"No config found for resource type '{resource_kind}'")
            return None

        # Get the provider factory from the config
        provider_factory = config.get("item_provider_factory")
        if not provider_factory or not callable(provider_factory):
            self.logger.error(f"No provider factory in config for {resource_kind}")
            return None

        # Get the provider class and its get_cached_items method
        provider_class = provider_factory()
        if not provider_class:
            self.logger.error(f"Provider factory returned None for {resource_kind}")
            return None

        get_cached_items = getattr(provider_class, "get_cached_items", None)
        if not get_cached_items or not callable(get_cached_items):
            self.logger.error(f"Provider class has no get_cached_items method for {resource_kind}")
            return None

        return cast(Callable[..., List[Dict[str, Any]]], get_cached_items)

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        resource_kind = self.context.get("current_kubernetes_resource_type")
        namespace = self.context.get("selected_namespace")

        self.logger.debug("ResourceListView: Entered get_fzf_configuration.")
        items = []
        self._current_raw_items = []  # Clear the current items

        provider_method = self._get_provider_method()
        if not provider_method:
            error_msg = "No provider available for resource type"
            self.logger.error(error_msg)
            items.append(
                self.fzf_formatter.format_item(
                    self.ERROR_FETCHING_ACTION_CODE, error_msg, self.ERROR_FETCHING_ICON
                )
            )
        else:
            try:
                namespace = self.context.get("selected_namespace")
                resources = provider_method(self.app_services, namespace=namespace)
                self.logger.debug(
                    f"ResourceListView: Provider returned {len(resources)} resources. First few names: {[r.get('metadata', {}).get('name') for r in resources[:3]]}"
                )
                self._current_raw_items = resources  # Store the raw items

                # Get the appropriate formatter for this resource type
                resource_kind = self.context.get("current_kubernetes_resource_type", "").lower()
                formatter = ResourceFormatterRegistry.get_formatter(resource_kind)

                for resource in resources:
                    name = resource.get("metadata", {}).get("name")
                    if name:
                        display_text = formatter.format_display_text(resource)
                        icon = formatter.get_icon(resource)
                        items.append(self.fzf_formatter.format_item(name, display_text, icon=icon))
                    else:
                        self.logger.warning(
                            f"ResourceListView: Found resource with missing metadata or name: {resource}"
                        )
            except Exception as e:
                self.logger.error(
                    f"ResourceListView: Exception during resource fetching/processing: {e}",
                    exc_info=True,
                )
                error_item_text = f"Error fetching resources: {str(e)[:50]}"
                items.append(
                    self.fzf_formatter.format_item(
                        self.ERROR_FETCHING_ACTION_CODE,
                        error_item_text,
                        icon=self.ERROR_FETCHING_ICON,
                    )
                )

        self.logger.debug(
            f"ResourceListView: Final FZF items list (count: {len(items)}) before returning. First 5: {items[:5]}"
        )

        # Format the prompt and header dynamically based on resource type and namespace
        resource_kind = self.context.get("current_kubernetes_resource_type", "Unknown")
        namespace_display = self.context.get("selected_namespace") or "All"

        prompt = self.DEFAULT_PROMPT_TEMPLATE.format(resource_display_name=resource_kind)
        header = self.DEFAULT_HEADER_TEMPLATE.format(
            resource_display_name=resource_kind, namespace_display=namespace_display
        )

        fzf_options = {
            "prompt": prompt,
            "header": header,
            "preview": None,
        }
        return items, fzf_options

    async def on_view_popped_with_result(
        self, result: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Optional[signals.NavigationSignal]:
        """Handle result from a popped child view."""
        self.logger.info(f"ResourceListView received result: {result}")
        return None

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.debug(
            f"ResourceListView: Processing selection: action='{action_code}', display='{display_text}'"
        )

        # For pods, the action_code is the pod name
        resource_name = action_code
        resource_namespace = self.context.get("selected_namespace")

        if not resource_name:
            self.logger.error(f"Selected item is missing a name: {action_code}")
            return signals.StaySignal()

        # Find the selected item from the internal list of raw items
        selected_item = next(
            (
                item
                for item in self._current_raw_items
                if item.get("metadata", {}).get("name") == resource_name
            ),
            None,
        )

        if not selected_item:
            self.logger.error(
                f"Could not find selected item with name '{resource_name}' in internal cache."
            )
            return signals.StaySignal()

        self.logger.debug(
            f"ResourceListView: Found selected item: {resource_name} in namespace {resource_namespace}"
        )

        return signals.PushViewSignal(
            view_key="ActionListView",
            context={
                "selected_resource_name": resource_name,
                "selected_resource_namespace": resource_namespace,
                "selected_resource_kind": self.context.get("current_kubernetes_resource_type"),
                "selected_resource_display_name": self.context.get(
                    "selected_resource_display_name"
                ),
                "raw_resource_object": selected_item,
            },
        )
