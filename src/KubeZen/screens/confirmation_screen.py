from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal

from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Label


@dataclass
class ButtonInfo:
    """Stores information about a button for the confirmation screen."""

    label: str
    result: Any
    variant: Literal["default", "primary", "success", "warning", "error"] = "primary"


class ConfirmationScreen(ModalScreen[Any]):
    """A configurable modal screen for user confirmation."""

    DEFAULT_CSS = """
    ConfirmationScreen {
        align: center middle;
    }

    #confirmation-container {
        width: 60;
        height: auto;
        padding: 1;
        border: thick $primary;
        background: $boost;
    }

    #title {
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
        text-style: bold;
    }

    #prompt {
        width: 100%;
        padding-bottom: 1;
        content-align: center middle;
    }

    #buttons {
        width: 100%;
        height: auto;
        align: center middle;
        padding-top: 1;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        buttons: list[ButtonInfo],
        prompt: str,
        title: str | None = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.title_text = title
        self.prompt_text = prompt
        self.buttons_info = buttons

    def compose(self) -> ComposeResult:
        button_widgets = [
            Button(info.label, variant=info.variant, id=f"button_{i}")
            for i, info in enumerate(self.buttons_info)
        ]

        with Grid(id="confirmation-container"):
            if self.title_text:
                yield Label(self.title_text, id="title")
            if self.prompt_text:
                yield Label(self.prompt_text, id="prompt")
            yield Grid(*button_widgets, id="buttons")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_index = int(event.button.id.split("_")[1])
        result = self.buttons_info[button_index].result
        self.dismiss(result)
