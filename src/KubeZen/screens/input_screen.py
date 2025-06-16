from __future__ import annotations
from typing import Awaitable, Callable, TYPE_CHECKING, Optional, Any

from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

if TYPE_CHECKING:
    from textual.app import App


class InputScreen(ModalScreen[Optional[str]]):
    """A screen that allows the user to input text.
    
    This screen provides a simple text input interface with a prompt and
    validation callback. It can be used to get user input for various purposes.
    """

    def __init__(
        self,
        title: str,
        prompt: str,
        initial_value: str | None = None,
        callback: Callable[[Optional[str]], Awaitable[None]] | None = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.title_text = title
        self.prompt_text = prompt
        self.initial_value = initial_value
        self.callback = callback

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.title_text, id="input_title"),
            Label(self.prompt_text, id="input_prompt"),
            Input(value=self.initial_value or "", id="input_field"),
            Grid(
                Button("OK", variant="primary", id="input_ok"),
                Button("Cancel", variant="default", id="input_cancel"),
                id="input_buttons",
            ),
            id="input_dialog",
        )

    def on_mount(self) -> None:
        """Focus the input widget when the screen is mounted."""
        self.query_one(Input).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "input_ok":
            value = self.query_one(Input).value
            await self._handle_input_ok(value)
        else:
            await self._handle_other_button(None)

    async def _handle_input_ok(self, value: Any) -> None:
        if self.callback:
            await self.callback(value)
        else:
            self.dismiss(value)

    async def _handle_other_button(self, value: Any) -> None:
        if self.callback:
            await self.callback(value)
        else:
            self.dismiss(value)
