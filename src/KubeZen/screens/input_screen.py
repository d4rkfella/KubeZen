from __future__ import annotations
from typing import Optional, Dict, List
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


@dataclass
class InputInfo:
    """A simple dataclass to hold input field information."""

    name: str
    label: str
    initial_value: Optional[str] = None


class InputScreen(ModalScreen[Optional[Dict[str, str]]]):
    """A modal screen that dynamically creates an input form."""

    def __init__(
        self,
        title: str,
        inputs: List[InputInfo],
        *,
        static_text: str | None = None,
        confirm_button_text: str | None = None,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.title_text = title
        self.inputs_info = inputs
        self.static_text = static_text
        self.confirm_button_text = confirm_button_text

    def compose(self) -> ComposeResult:
        input_fields = [
            widget
            for info in self.inputs_info
            for widget in (
                Label(info.label),
                Input(value=info.initial_value or "", id=info.name),
                Static(""),
            )
        ]

        if self.static_text:
            input_fields.insert(0, Static(self.static_text, id="input_static_text"))

        yield Grid(
            Static(self.title_text, id="input_title"),
            Vertical(*input_fields, id="input_fields_container"),
            Grid(
                Button(
                    self.confirm_button_text or "OK", variant="primary", id="input_ok"
                ),
                Button("Cancel", variant="default", id="input_cancel"),
                id="input_buttons",
            ),
            id="input_dialog",
        )

    def on_mount(self) -> None:
        """Focus the first input widget when the screen is mounted."""
        first_input = self.query(Input).first()
        if first_input:
            first_input.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "input_ok":
            results = {
                inp.id: inp.value for inp in self.query(Input) if inp.id is not None
            }
            self.dismiss(results)
        else:
            self.dismiss(None)
