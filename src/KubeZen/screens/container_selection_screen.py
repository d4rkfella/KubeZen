from __future__ import annotations
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, ListView, ListItem, Label


class ActionListItem(ListItem):
    """A ListItem that holds arbitrary data."""

    def __init__(self, *args: Any, data: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.data = data


class ContainerSelectionScreen(ModalScreen[str | None]):
    """Screen for selecting a container from a pod."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        containers: list[str],
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.title_text = title
        self.containers = containers

    def compose(self) -> ComposeResult:
        with Vertical(id="list_selection_dialog"):
            yield Static(self.title_text)
            yield ListView()
            yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Focus the list view and populate it with choices."""
        list_view = self.query_one(ListView)
        for container in self.containers:
            list_view.append(ActionListItem(Label(container), data=container))
        list_view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """When a list item is selected, pop the screen and call the callback."""
        if isinstance(event.item, ActionListItem):
            self.dismiss(event.item.data)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the cancel button."""
        if event.button.id == "cancel":
            self.dismiss(None)
        self.app.notify("Exec cancelled.", title="Exec")
