from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Optional, List, Tuple, Type
import shlex

from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.ui.view_registry import ViewRegistry
from KubeZen.core import signals
from KubeZen.core.service_base import ServiceBase

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class NavigationCoordinator(ServiceBase):
    """
    Coordinates navigation between different views in the application.
    Manages the view stack and handles navigation signals.
    """

    def __init__(
        self,
        app_services: AppServices,
        view_registry: ViewRegistry,
        initial_view_key: Optional[str] = None,
    ):
        super().__init__(app_services)
        self.view_registry = view_registry
        self.initial_view_key = initial_view_key or view_registry.get_default_view()
        self.view_stack: List[BaseUIView] = []
        self.current_view: Optional[BaseUIView] = None
        self.logger.debug(
            f"NavigationCoordinator initialized. Initial view key: '{self.initial_view_key}'"
        )

    async def _get_actions_for_view(
        self, view: BaseUIView, is_initial: bool = False, is_resumed: bool = False
    ) -> List[str]:
        """Helper to get view content and assemble FZF actions."""
        fzf_items, fzf_options = await view.get_fzf_configuration()

        # Add 'Go Back' option if applicable
        if self.can_go_back():
            fzf_items.append(view.get_go_back_fzf_item())

        # The view writes its content to a stable file path and returns it as a string
        data_file_path = view.write_fzf_items_to_file(fzf_items)

        actions = []
        if data_file_path:
            # The item reader script path is already a string from the config
            if self.app_services.config:
                item_reader_script = self.app_services.config.fzf_item_reader_script_path
                reload_command = (
                    f"reload({shlex.quote(item_reader_script)} {shlex.quote(data_file_path)})"
                )
                actions.append(reload_command)

        # Add other actions based on fzf options
        if fzf_options.get("header") is not None:
            actions.append(f"change-header({fzf_options['header']})")
        if fzf_options.get("prompt") is not None:
            actions.append(f"change-prompt({fzf_options['prompt']})")
        if fzf_options.get("preview") is not None:
            actions.append(f"preview({fzf_options['preview']})")
        if self.logger:
            self.logger.debug(f"Assembled FZF actions: {actions}")

        # For any view that isn't the very first one, select the top item.
        if not is_initial:
            actions.append("first")

        return actions

    def get_current_view(self) -> Optional[BaseUIView]:
        """Returns the currently active view from the top of the stack."""
        return self.view_stack[-1] if self.view_stack else None

    async def start(self) -> Optional[List[str]]:
        """
        Clears the view stack and starts the navigation with the initial
        entrypoint view. Returns its FZF actions.
        """
        view_key = self.initial_view_key
        if self.logger:
            self.logger.info("NC: Starting navigation with initial view: {}".format(view_key))

        # Clean up any existing views on the stack before starting fresh
        for view in reversed(self.view_stack):
            if self.logger:
                self.logger.debug(f"View leaving: {view.__class__.__name__}")
            view.file_manager.cleanup()
        self.view_stack.clear()
        if self.logger:
            self.logger.info("NC: View stack cleared. Starting fresh.")

        # Push the initial view
        return await self.push_view(view_key=view_key, is_initial_view=True)

    async def push_view(
        self,
        view_key: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        is_initial_view: bool = False,
        view_class: Optional[Type[BaseUIView]] = None,
    ) -> Optional[List[str]]:
        """Pushes a new view onto the stack and returns its FZF actions."""
        if self.logger:
            self.logger.info(
                f"NC: Pushing view (key='{view_key}', class='{view_class.__name__ if view_class else None}')"
            )

        target_class = view_class
        if not target_class:
            if view_key:
                target_class = self.view_registry.get_view_class(view_key)
            else:
                if self.logger:
                    self.logger.error("Push failed: Both view_key and view_class are None.")
                return None

        if not target_class:
            if self.logger:
                self.logger.error(f"Push failed: View key '{view_key}' not in ViewRegistry.")
            return None

        key_for_log = view_key or (target_class.__name__ if target_class else "Unknown")
        if self.logger:
            self.logger.info(
                f"NC: Attempting to push '{key_for_log}'. Current stack depth: {len(self.view_stack)}"
            )
        # Notify the current view it's being left
        if self.view_stack:
            old_view = self.view_stack[-1]
            if self.logger:
                self.logger.debug(f"View leaving: {old_view.__class__.__name__}")
            old_view.file_manager.cleanup()

        try:
            new_view = target_class(navigation_coordinator=self, context=context)
            self.view_stack.append(new_view)
            if self.logger:
                self.logger.info(f"Pushed '{key_for_log}'. Stack depth: {len(self.view_stack)}")
            if self.logger:
                self.logger.debug(
                    f"View entered: {new_view.__class__.__name__}. Initial: {is_initial_view}, Resumed: False"
                )

            # Enter the new view (hook for subclasses) and then get its display actions
            fzf_actions = await self._get_actions_for_view(new_view, is_initial=is_initial_view)
            return fzf_actions
        except Exception as e:
            # This is a critical error, as it means the view itself is broken.
            if self.logger:
                self.logger.critical(
                    f"FATAL: Error instantiating or entering '{view_key or (target_class and target_class.__name__)}': {e}",
                    exc_info=True,
                )
            # Optionally, push an ErrorView onto the stack
            # For now, we'll log, but in a real app, you might want a graceful error view.
            # Attempt to pop the failed view if it was added
            if self.view_stack and target_class and isinstance(self.view_stack[-1], target_class):
                self.view_stack.pop()
            return None

    async def pop_view(
        self, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[List[str]], Optional[BaseUIView]]:
        if self.logger:
            self.logger.info("NC: Popping current view.")
        if len(self.view_stack) > 1:
            # Leave current view
            old_view = self.view_stack.pop()
            if self.logger:
                self.logger.debug(f"View leaving: {old_view.__class__.__name__}")
            old_view.file_manager.cleanup()
            if self.logger:
                self.logger.info(
                    f"NC: Popped '{old_view.__class__.__name__}'. Stack depth now: {len(self.view_stack)}"
                )

            # Resume parent view
            new_current_view = self.get_current_view()
            if new_current_view:
                if self.logger:
                    self.logger.info(f"Resuming view '{new_current_view.__class__.__name__}'.")

                # Update the context of the parent view with any context from the signal
                if context:
                    if new_current_view.context:
                        new_current_view.context.update(context)
                    else:
                        new_current_view.context = context

                if self.logger:
                    self.logger.debug(
                        f"View entered: {new_current_view.__class__.__name__}. Initial: False, Resumed: True"
                    )
                fzf_actions = await self._get_actions_for_view(new_current_view)
                return fzf_actions, new_current_view
            return None, None
        else:
            # This is the last view, so we should exit
            if self.logger:
                self.logger.info("NC: Last view popped, signaling application exit.")
            if self.app_services:
                self.app_services.shutdown_requested = True
            return ["abort"], None

    async def pop_view_with_result(
        self, result: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[signals.NavigationSignal], Optional[List[str]]]:
        """
        Pops the current view and calls the on_view_popped_with_result on the
        newly resumed parent view, returning any subsequent signal and the FZF
        actions required to refresh the parent view.
        """
        if self.logger:
            self.logger.info("NC: Popping current view with result.")
        if len(self.view_stack) <= 1:
            if self.logger:
                self.logger.warning("Attempted to pop the last view with result. Aborting.")
            return None, None

        leaving_view = self.view_stack.pop()
        if self.logger:
            self.logger.debug(f"View leaving: {leaving_view.__class__.__name__}")
        leaving_view.file_manager.cleanup()
        if self.logger:
            self.logger.info(
                f"NC: Popped '{leaving_view.__class__.__name__}' with result. Stack depth now: {len(self.view_stack)}"
            )

        resumed_view = self.get_current_view()
        if not resumed_view:
            if self.logger:
                self.logger.error("Popped to an empty view stack unexpectedly.")
            return signals.ExitApplicationSignal(), None

        if self.logger:
            self.logger.debug(
                f"View entered: {resumed_view.__class__.__name__}. Initial: False, Resumed: True"
            )

        # Get the actions for the resumed view first.
        fzf_actions = await self._get_actions_for_view(resumed_view, is_resumed=True)

        # Now, let the resumed view process the result from its child.
        # This might return a new signal (e.g., to stay, or to push another view).
        if self.logger:
            self.logger.debug(
                f"Calling on_view_popped_with_result for '{resumed_view.__class__.__name__}'"
            )
        sub_signal = await resumed_view.on_view_popped_with_result(result, context)

        return sub_signal, fzf_actions

    async def refresh_current_view(
        self, context: Optional[Dict[str, Any]] = None
    ) -> Optional[List[str]]:
        """Refreshes the current view's content and FZF display."""
        current_view = self.get_current_view()
        if not current_view:
            if self.logger:
                self.logger.warning("NC: Tried to refresh with no current view.")
            return None

        if self.logger:
            self.logger.info(f"NC: Refreshing view '{current_view.__class__.__name__}'.")

        # Update context if provided
        if context:
            if current_view.context:
                current_view.context.update(context)
            else:
                current_view.context = context

        # Re-fetch actions, treating it as a resumed view to force a redraw.
        return await self._get_actions_for_view(current_view, is_resumed=True)

    def can_go_back(self) -> bool:
        """Checks if there's a view to go back to on the stack."""
        return len(self.view_stack) > 1
