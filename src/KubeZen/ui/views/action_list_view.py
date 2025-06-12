from __future__ import annotations
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple, Coroutine

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core import signals
from KubeZen.core.contexts import ActionContext
from KubeZen.actions import get_registered_actions_for_resource_type
from KubeZen.core.actions import Action

if TYPE_CHECKING:
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator
    from typing import Callable


class MenuItem:
    def __init__(
        self,
        display_text: str,
        action_instance: Optional[Action] = None,
        shortcut: Optional[str] = None,
        icon: Optional[str] = None,
        is_separator: bool = False,
    ):
        self.display_text = display_text
        self.action_instance = action_instance
        self.shortcut = shortcut
        self.icon = icon
        self.is_separator = is_separator

    @property
    def handler(
        self,
    ) -> Optional[
        Callable[
            [ActionContext, Dict[str, Any]],
            Coroutine[Any, Any, Optional[signals.NavigationSignal]],
        ]
    ]:
        if self.action_instance:
            return self.action_instance.execute
        return None


class ActionListView(BaseUIView):
    """
    A generic view that displays a list of applicable actions for a given resource.
    """

    DEFAULT_PROMPT_TEMPLATE = "Select action for {resource_display_name} '{resource_name}' > "
    DEFAULT_HEADER_TEMPLATE = (
        "Actions for {resource_display_name} '{resource_name}' (ns: {namespace_display})"
    )

    VIEW_TYPE = "ActionListView"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(navigation_coordinator, context)
        # This view receives the action CLASSES and the specific resource dict
        self.raw_resource_object: Dict[str, Any] = self.context.get("raw_resource_object", {})
        self.selected_resource_name: Optional[str] = self.context.get("selected_resource_name")
        self.resource_type: Optional[str] = self.context.get("selected_resource_kind")
        self.current_namespace: Optional[str] = self.context.get("selected_resource_namespace")

        self.menu_items: List[MenuItem] = []

        if not self.raw_resource_object or not self.resource_type:
            self.logger.warning("ActionListView initialized with no resource or resource type.")
            return

        action_configs = get_registered_actions_for_resource_type(self.resource_type)
        action_context = self._create_action_context()
        if not action_context:
            return

        for config in action_configs:
            action_class = config["class"]
            # pass all config items except 'class' and 'resource_types' to the constructor
            init_args = {k: v for k, v in config.items() if k not in ["class", "resource_types"]}
            init_args["app_services"] = self.app_services
            action_instance = action_class(**init_args)

            if action_instance.is_applicable(action_context):
                self.menu_items.append(
                    MenuItem(
                        action_instance.name,
                        action_instance=action_instance,
                        shortcut=action_instance.shortcut,
                        icon=action_instance.icon,
                    )
                )

    def _create_action_context(
        self, from_dict: Optional[Dict[str, Any]] = None
    ) -> Optional[ActionContext]:
        """Helper method to create a fresh ActionContext."""
        if from_dict:
            return ActionContext.from_dict(from_dict, self.app_services)

        # Assert that all required services are available
        assert self.app_services.logger is not None, "Logger not initialized"
        assert self.app_services.config is not None, "Config not initialized"
        assert self.app_services.tmux_ui_manager is not None, "TmuxUIManager not initialized"
        assert self.app_services.kubernetes_client is not None, "KubernetesClient not initialized"
        assert self.app_services.user_input_manager is not None, "UserInputManager not initialized"
        assert self.app_services.fzf_ui_manager is not None, "FzfUIManager not initialized"

        return ActionContext(
            logger=self.app_services.logger,
            config=self.app_services.config,
            tmux_ui_manager=self.app_services.tmux_ui_manager,
            kubernetes_client=self.app_services.kubernetes_client,
            user_input_manager=self.app_services.user_input_manager,
            fzf_ui_manager=self.app_services.fzf_ui_manager,
            raw_k8s_object=self.raw_resource_object,
            resource_name=self.selected_resource_name,
            resource_kind=self.resource_type,
            current_namespace=self.current_namespace,
            namespace=self.raw_resource_object.get("metadata", {}).get("namespace"),
            original_view_context=self.context,
            custom_data={},
        )

    def __repr__(self) -> str:
        resource_name = self.selected_resource_name
        resource_kind = self.resource_type

        return (
            f"ActionListView(resource_name='{resource_name}', " f"resource_kind='{resource_kind}')"
        )

    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        self.logger.debug("ActionListView: Entered get_fzf_configuration.")
        items = []

        if not self.menu_items:
            error_msg = "No actions available for this resource"
            self.logger.warning(error_msg)
            items.append(
                self.fzf_formatter.format_item(
                    self.ERROR_FETCHING_ACTION_CODE, error_msg, self.ERROR_FETCHING_ICON
                )
            )
        else:
            try:
                for menu_item in self.menu_items:
                    if menu_item.is_separator or not menu_item.action_instance:
                        continue
                    items.append(
                        self.fzf_formatter.format_item(
                            menu_item.action_instance.action_code,
                            menu_item.display_text,
                            icon=menu_item.icon,
                        )
                    )
            except Exception as e:
                self.logger.error(
                    f"ActionListView: Exception during action processing: {e}",
                    exc_info=True,
                )
                error_item_text = f"Error processing actions: {str(e)[:50]}"
                items.append(
                    self.fzf_formatter.format_item(
                        self.ERROR_FETCHING_ACTION_CODE,
                        error_item_text,
                        icon=self.ERROR_FETCHING_ICON,
                    )
                )

        self.logger.debug(
            f"ActionListView: Final FZF items list (count: {len(items)}) before returning. First 5: {items[:5]}"
        )

        # Format the prompt and header dynamically based on resource type and name
        resource_name = self.selected_resource_name or "Unknown"
        resource_type = self.resource_type or "Unknown"
        namespace_display = self.current_namespace or "All"

        prompt = self.DEFAULT_PROMPT_TEMPLATE.format(
            resource_display_name=resource_type, resource_name=resource_name
        )
        header = self.DEFAULT_HEADER_TEMPLATE.format(
            resource_display_name=resource_type,
            resource_name=resource_name,
            namespace_display=namespace_display,
        )

        fzf_options = {
            "prompt": prompt,
            "header": header,
            "preview": None,
        }
        return items, fzf_options

    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.info(f"Processing selection with action_code: '{action_code}'")

        if action_code == self.GO_BACK_ACTION_CODE:
            return signals.ToParentSignal()

        item = next(
            (
                item
                for item in self.menu_items
                if item.action_instance and item.action_instance.action_code == action_code
            ),
            None,
        )

        if item and item.handler:
            self.logger.info(f"Executing action '{item.display_text}'.")
            action_context = self._create_action_context()
            if not action_context:
                return signals.StaySignal()

            try:
                # The unsafe call is isolated in the try block.
                result_signal = await item.handler(action_context, self.raw_resource_object)
            except Exception as e:
                self.logger.error(
                    f"Error executing action handler for '{item.display_text}': {e}", exc_info=True
                )
                return signals.StaySignal()

            # The logic is now simple, linear, and outside the try block.
            if result_signal is None:
                return signals.StaySignal()

            # The only special case is PushViewSignal, which needs context added.
            if isinstance(result_signal, signals.PushViewSignal):
                if result_signal.context is None:
                    result_signal.context = {}
                result_from_dict = action_context.to_dict()
                result_signal.context["original_action_context"] = result_from_dict
                result_signal.context["action_to_resume"] = action_code

            # Per the type hints, result_signal is now a valid NavigationSignal.
            # No further checks are needed. We just return it.
            return result_signal

        self.logger.warning(
            f"No handler found for action code '{action_code}'. Returning StaySignal."
        )
        return signals.StaySignal()

    async def on_view_popped_with_result(
        self, result: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Optional[signals.NavigationSignal]:
        self.logger.debug(f"ActionListView received result: {result} and context: {context}")

        if not context:
            self.logger.error("Could not resume action: no context from child view.")
            return signals.StaySignal()

        action_to_resume_code = context.get("action_to_resume")
        original_action_context_dict = context.get("original_action_context")

        if not action_to_resume_code or not original_action_context_dict:
            self.logger.error("Could not resume action: missing context from child.")
            return signals.StaySignal()

        # Add the new result from the child view into the custom_data of the context.
        if "custom_data" not in original_action_context_dict:
            original_action_context_dict["custom_data"] = {}
        original_action_context_dict["custom_data"].update(result)

        action_context = self._create_action_context(from_dict=original_action_context_dict)
        if not action_context:
            return signals.StaySignal()

        item = next(
            (
                item
                for item in self.menu_items
                if item.action_instance
                and item.action_instance.action_code == action_to_resume_code
                and item.action_instance.is_applicable(action_context)
            ),
            None,
        )

        if item and item.handler:
            self.logger.info(f"Resuming action '{item.display_text}' with new context.")
            return await item.handler(action_context, self.raw_resource_object)
        else:
            self.logger.error(f"Could not find action to resume: {action_to_resume_code}")
            return signals.StaySignal()
