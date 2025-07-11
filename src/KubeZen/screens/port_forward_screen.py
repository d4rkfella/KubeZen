from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Sequence, Any
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, Select
from textual.reactive import reactive
from textual import on

if TYPE_CHECKING:
    from textual.app import App


@dataclass(frozen=True)
class PortInfo:
    """A simple dataclass to hold port forwarding information."""

    container_port: int
    local_port: int | None = None
    protocol: str = "TCP"


class PortForwardScreen(ModalScreen[list[PortInfo] | None]):
    """A modal screen for configuring a port forward."""

    remote_port_value = reactive("")

    def __init__(
        self,
        target_name: str,
        ports: Optional[Sequence[Any]] = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=screen_id, classes=classes)
        self.target_name = target_name
        self.ports: Sequence[Any] = ports if ports is not None else []

    def compose(self) -> ComposeResult:
        with Vertical(id="pf_dialog"):
            yield Static(f"Port Forward for: {self.target_name}", id="pf_title")

            if self.ports:
                port_options = []
                for p in self.ports:
                    # Handle both V1ServicePort and V1ContainerPort
                    port_number = getattr(p, "container_port", getattr(p, "port", None))
                    if port_number is None:
                        continue

                    port_name = getattr(p, "name", "")
                    protocol = getattr(p, "protocol", "TCP")
                    label = f"{port_name} {port_number}/{protocol}".strip()
                    port_options.append((label, str(port_number)))

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
            local_port_str = self.query_one("#local_port", Input).value
            remote_port_str = self.query_one("#remote_port", Input).value

            if not remote_port_str or not self._is_valid_port(remote_port_str):
                self.app.notify(
                    "Remote port is required and must be a valid port number.",
                    severity="error",
                )
                return

            local_port = (
                int(local_port_str)
                if local_port_str and self._is_valid_port(local_port_str)
                else None
            )

            port_info = PortInfo(
                container_port=int(remote_port_str), local_port=local_port
            )
            self.dismiss([port_info])

    @staticmethod
    def _is_valid_port(value: str) -> bool:
        """Validate if a string is a valid port number."""
        try:
            port = int(value)
            return 1 <= port <= 65535
        except (ValueError, TypeError):
            return False
