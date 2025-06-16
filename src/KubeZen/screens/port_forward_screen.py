from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Sequence

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, Select
from textual.reactive import reactive

from ..core.resource_registry import PortInfo

if TYPE_CHECKING:
    from textual.app import App


class PortForwardScreen(ModalScreen[dict[str, str] | None]):
    """A modal screen for configuring a port forward."""

    remote_port_value = reactive("")

    def __init__(
        self,
        target_name: str,
        ports: Optional[Sequence[PortInfo]] = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.target_name = target_name
        self.ports = ports

    def compose(self) -> ComposeResult:
        with Vertical(id="pf_dialog"):
            yield Static(f"Port Forward for: {self.target_name}", id="pf_title")

            if self.ports:
                port_options = [
                    (f"{p['name']} {p['number']}/{p['protocol']}", str(p["number"]))
                    for p in self.ports
                ]
                yield Label("Select a discovered port (optional):")
                yield Select(
                    port_options,
                    prompt="None",
                    allow_blank=True,
                    id="port_select",
                )

            with Horizontal(classes="input_group"):
                with Vertical():
                    yield Label("Local Port:")
                    yield Input(placeholder="e.g. 8080", id="local_port")
                with Vertical():
                    yield Label("Remote Port:")
                    yield Input(
                        placeholder="e.g. 80",
                        id="remote_port",
                    )

            with Horizontal(id="pf_buttons"):
                yield Button("Start", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Set initial values for inputs after the DOM is ready."""
        self.query_one("#remote_port", Input).value = self.remote_port_value
        self.query_one("#local_port", Input).value = self.remote_port_value

    def watch_remote_port_value(self, new_value: str) -> None:
        """Update the input when the reactive variable changes."""
        self.query_one("#remote_port", Input).value = new_value

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle changes to the port selection."""
        if event.value is Select.BLANK:
            self.remote_port_value = ""
        else:
            self.remote_port_value = str(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            local_port = self.query_one("#local_port", Input).value
            remote_port = self.query_one("#remote_port", Input).value

            if not remote_port:
                self.app.notify("Remote port is required.", severity="error")
                return

            # If local port is empty, default it to the remote port.
            if not local_port:
                local_port = remote_port

            self.dismiss({"local_port": local_port, "remote_port": remote_port})
