from typing import Any, Type

from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label
from textual.app import ComposeResult
from textual.message import Message

from ..actions.action_registry import ACTION_REGISTRY


class ActionListItem(ListItem):
    def __init__(self, *args: Any, data: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.data = data


class ActionScreen(Screen[None]):
    """A screen to display available actions for a selected resource."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back to Resource List"),
    ]

    class ActionSelected(Message):
        """Message to indicate a specific action has been selected."""

        # action_class: Type[Any]
        # resource_key: str
        # namespace: str
        # resource_name: str

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

        if not available_actions:
            list_view.append(ListItem(Label("No actions available.")))
        else:
            for action_info in available_actions:
                emoji = action_info.get("emoji", "▶️")
                display_text = f"{emoji} {action_info['name']}"
                list_item = ActionListItem(
                    Label(display_text), data=action_info["class"]
                )
                list_view.append(list_item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Event handler for when an action is selected."""
        if not isinstance(event.item, ActionListItem):
            return
        selected_action_class = event.item.data
        if selected_action_class:
            self.post_message(
                self.ActionSelected(
                    action_class=selected_action_class,
                    resource_key=self.resource_key,
                    ns=self.namespace,
                    resource_name=self.resource_name,
                )
            )
