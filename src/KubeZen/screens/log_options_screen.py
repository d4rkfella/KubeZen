from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional, Sequence

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static, Select

if TYPE_CHECKING:
    from textual.app import App


ALL_CONTAINERS_CODE = "[all containers]"


class LogOptionsScreen(ModalScreen[dict[str, Any] | None]):
    """A modal screen for selecting multiple log viewing options."""

    def __init__(
        self,
        target_name: str,
        allow_follow: bool = True,
        containers: Optional[Sequence[str]] = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.target_name = target_name
        self.allow_follow = allow_follow
        self.containers = containers

    def compose(self) -> ComposeResult:
        with Vertical(id="log_options_dialog"):
            yield Static(f"Log Options for: {self.target_name}", id="log_options_title")

            if self.containers:
                container_options = [(c, c) for c in self.containers]
                container_options.insert(0, ("[all containers]", ALL_CONTAINERS_CODE))
                yield Label("Select container:")
                yield Select(
                    container_options, value=ALL_CONTAINERS_CODE, id="container_select"
                )

            with Vertical(classes="option_group"):
                if self.allow_follow:
                    yield Checkbox("Follow logs (live)", id="follow")
                yield Checkbox("Show timestamps", id="timestamps")
                yield Checkbox("View previous terminated container", id="previous")

            with Vertical(classes="option_group"):
                yield Label("Tail lines (e.g., 500):")
                yield Input(placeholder="all", id="tail")

                yield Label("Only logs since duration (e.g., 5m, 2h):")
                yield Input(placeholder="disabled", id="since")

            with Horizontal(id="log_options_buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            options: dict[str, Any] = {}

            # Checkboxes
            if self.allow_follow:
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
                options["container"] = self.query_one("#container_select", Select).value

            self.dismiss(options)
