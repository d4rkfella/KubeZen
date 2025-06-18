from typing import Any, Type, TypeVar, Generic, cast
import logging

from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label, TextArea
from textual.app import ComposeResult
from textual.message import Message

from ..actions.action_registry import ACTION_REGISTRY
from ..utils.logging import log_batch_timing

log = logging.getLogger(__name__)

# Define a TypeVar for the action class type
T = TypeVar("T", bound=type)


class ActionListItem(ListItem, Generic[T]):
    """A ListItem that holds the action class."""

    def __init__(self, *args: Any, data: T, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.data = data


class ActionScreen(Screen[None]):
    """A screen to display available actions for a selected resource."""

    BINDINGS = [
        ("enter", "select", "Select Action"),
        ("escape", "app.pop_screen", "Back to Resource List"),
    ]

    class ActionSelected(Message):
        """Message to indicate a specific action has been selected."""

        def __init__(
            self,
            action_class: Type[Any],
            resource_key: str,
            ns: str,
            resource_name: str,
        ):
            super().__init__()
            self.action_class = action_class
            self.resource_key = resource_key
            self.namespace = ns  # type: ignore[misc]
            self.resource_name = resource_name

    def __init__(
        self,
        resource_key: str,
        namespace: str,
        resource_name: str,
        resource_emoji: str = "❓",
    ) -> None:
        super().__init__()
        self.resource_key = resource_key
        self.namespace = namespace
        self.resource_name = resource_name
        self.title = f"{resource_emoji} Actions for: {resource_name}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ListView()
        yield Footer()

    def on_mount(self) -> None:
        """Event handler for when the screen is mounted."""
        list_view = self.query_one(ListView)

        available_actions = []
        for action_info in ACTION_REGISTRY:
            resource_types = action_info.get("resource_types")
            if isinstance(resource_types, (list, tuple)) and (
                "all" in resource_types or self.resource_key in resource_types
            ):
                available_actions.append(action_info)

        with log_batch_timing(self.app, log_changes=True):
            if not available_actions:
                list_view.append(ListItem(Label("No actions available.")))
            else:
                for action_info in available_actions:
                    emoji = action_info.get("emoji", "▶️")
                    display_text = f"{emoji} {action_info['name']}"
                    # Cast the action class to type since we know it's a class
                    action_class = cast(type, action_info["class"])
                    list_item = ActionListItem[type](
                        Label(display_text), data=action_class
                    )
                    list_view.append(list_item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Event handler for when an action is selected."""
        log.debug("on_list_view_selected called with event: %s", event)
        if not isinstance(event.item, ActionListItem):
            log.warning("Selected item is not an ActionListItem: %s", event.item)
            return
        selected_action_class = event.item.data
        log.debug("Selected action class: %s", selected_action_class)
        if selected_action_class:
            try:
                resource_obj = self.app.store.get_one(
                    self.resource_key,
                    self.namespace,
                    self.resource_name,
                )
                if resource_obj:
                    action_instance = selected_action_class(
                        app=self.app,
                        resource=resource_obj,
                        object_name=self.resource_name,
                        resource_key=self.resource_key,
                    )
                    self.app.run_worker(
                        action_instance.run(),
                        name=f"action_{selected_action_class.__name__}",
                        group="actions",
                    )
                else:
                    self.app.notify(
                        f"Could not find resource {self.resource_name}",
                        title="Error",
                        severity="error",
                    )
            except Exception:
                log.critical("Caught exception during action execution:", exc_info=True)
                self.app.notify(
                    "Action failed! See crash output in terminal for details.",
                    title="Action Error",
                    severity="error",
                )

    async def _update_output(self, output: str) -> None:
        """Update the output text area."""
        output_area = self.query_one(TextArea)

        # Use batch update to reduce screen redraws
        with self.app.batch_update():
            output_area.load_text(output)
            # Scroll to bottom only if we're already at the bottom
            if (
                output_area.scroll_y
                >= output_area.virtual_size.height - output_area.size.height
            ):
                output_area.scroll_end()

    async def _update_status(self, status: str) -> None:
        """Update the status label."""
        status_label = self.query_one("#status", Label)

        # Use batch update to reduce screen redraws
        with self.app.batch_update():
            status_label.renderable = status
