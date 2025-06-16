from __future__ import annotations
from typing import Awaitable, Callable, TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Input

if TYPE_CHECKING:
    from textual.app import App


class ConfirmationScreen(ModalScreen[bool]):
    """A modal screen that asks for user confirmation.
    Can optionally include an input field.
    """

    def __init__(
        self,
        title: str,
        prompt: str,
        callback: Callable[..., Awaitable[None]],
        input_widget: Input | None = None,
        *,
        name: str | None = None,
        screen_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, screen_id, classes)
        self.title_text = title
        self.prompt_text = prompt
        self.callback = callback
        self.input_widget = input_widget

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.title_text, id="confirm_title"),
            Label(self.prompt_text, id="confirm_prompt"),
            Grid(
                Button("Yes", variant="error", id="confirm_yes"),
                Button("No", variant="primary", id="confirm_no"),
                id="confirm_buttons",
            ),
            id="confirmation_dialog",
        )
        if self.input_widget:
            yield self.input_widget

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_yes":
            if self.input_widget:
                # To satisfy mypy, we need to cast the callback to the correct type
                input_callback = cast(Callable[[str], Awaitable[None]], self.callback)
                await input_callback(self.input_widget.value)
            else:
                # Cast for no-input case
                no_input_callback = cast(Callable[[], Awaitable[None]], self.callback)
                await no_input_callback()
        elif event.button.id == "confirm_no":
            self.app.pop_screen()
