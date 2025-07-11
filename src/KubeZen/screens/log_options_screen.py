from __future__ import annotations
from typing import TYPE_CHECKING, Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static, SelectionList
from textual.widgets.selection_list import Selection
from KubeZen.models.base import UIRow
from KubeZen.models.core import PodRow
from textual.events import Key

if TYPE_CHECKING:
    from textual.app import App

ALL_CONTAINERS_CODE = "all_containers_magic_string"


class LogOptionsScreen(ModalScreen[dict[str, Any] | None]):
    """A modal screen for selecting multiple log viewing options."""

    DEFAULT_CSS = """
    LogOptionsScreen {
        align: center middle;
    }
    LogOptionsScreen #log_options_dialog {
        max-width: 80;
        max-height: 40;
        overflow-y: auto;
        overflow-x: auto;
        border: thick $primary;
        background: $surface;
    }
    #log_options_title {
        content-align: center top;
        text-style: bold;
        padding-bottom: 1;
    }
    .center_container {
        align: center middle;
        height: auto;
    }
    #container_label {
        width: 1fr;
        content-align: center top;
    }
    #container_selection_list {
        height: 7;
        width: 50%;
        border: round $primary;
        margin-bottom: 1;
        background: transparent;
    }
    #checkbox_group {
       width: 1fr;
       margin-left: 1;
       margin-right: 1;
       height: 3;
       margin-bottom: 1;
    }
    #checkbox_group > Checkbox {
        width: 1fr;
    }
    .input_group {
        width: 1fr;
        height: 6;
    }
    .input_group Label {
        width: 1fr;
        margin-top: 1;
        margin-bottom: 1;
        margin-left: 1;
    }
    #log_options_buttons{
        align: center middle;
        margin-top: 2;
    }
    """

    def __init__(
        self,
        row_info: UIRow,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.row_info = row_info
        self.target_name = row_info.name
        self.containers = []
        if isinstance(row_info, PodRow):
            # Extract container names from the raw object's attributes, including init containers
            containers = [c.name for c in row_info.raw.spec.containers if c.name]
            init_containers = [
                c.name for c in (row_info.raw.spec.init_containers or []) if c.name
            ]
            self.containers = containers + init_containers

    def compose(self) -> ComposeResult:
        with Vertical(id="log_options_dialog"):
            yield Static(f"Log Options for: {self.target_name}", id="log_options_title")

            if self.containers:
                yield Label("Select container:", id="container_label")
                with Horizontal(classes="center_container"):
                    yield SelectionList(id="container_selection_list")

            with Horizontal(id="checkbox_group"):
                yield Checkbox("Follow logs", id="follow")
                yield Checkbox("Timestamps", id="timestamps")
                yield Checkbox("View previous", id="previous")

            with Vertical(classes="input_group"):
                yield Label("Tail lines (e.g., 500):")
                yield Input(placeholder="all", id="tail")
            with Vertical(classes="input_group"):
                yield Label("Since duration (e.g., 5m):")
                yield Input(placeholder="disabled", id="since")
            with Horizontal(id="log_options_buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Populate the container selection list."""
        if self.containers:
            selection_list = self.query_one("#container_selection_list", SelectionList)

            # Add the "all" option first with a descriptive and safe label
            selection_list.add_option(
                Selection(
                    f"All Containers ({len(self.containers)})",
                    ALL_CONTAINERS_CODE,
                    True,
                )
            )

            # Add the rest of the containers
            for c in self.containers:
                selection_list.add_option(Selection(c, c, False))

    @on(SelectionList.SelectedChanged, "#container_selection_list")
    def on_container_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        """Enforce single selection in the list."""
        if len(event.selection_list.selected) > 1:
            # Get the last selected item (the one the user just clicked)
            last_selected = event.selection_list.selected[-1]
            # Deselect all and then re-select only the last one
            event.selection_list.deselect_all()
            event.selection_list.select(last_selected)

    def on_key(self, event: Key) -> None:
        """Handle key presses."""
        if event.key == "escape":
            self.dismiss(None)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            options: dict[str, Any] = {}

            # Checkboxes
            options["follow"] = self.query_one("#follow", Checkbox).value
            options["timestamps"] = self.query_one("#timestamps", Checkbox).value
            options["previous"] = self.query_one("#previous", Checkbox).value

            # Inputs
            tail_value = self.query_one("#tail", Input).value
            if tail_value.isdigit():
                options["tail"] = int(tail_value)

            since_value = self.query_one("#since", Input).value
            if since_value:
                options["since"] = since_value

            if self.containers:
                selection_list = self.query_one(
                    "#container_selection_list", SelectionList
                )
                if selection_list.selected:
                    options["container"] = selection_list.selected[0]
                else:
                    # Default to all if nothing is selected
                    options["container"] = ALL_CONTAINERS_CODE
            else:
                options["container"] = None

            self.dismiss(options)
