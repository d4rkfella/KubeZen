from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class QuitScreen(ModalScreen):
    """Centered Modal Quit Dialog."""

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Are you sure you want to quit?", id="question")
            with Horizontal():
                yield Button("Quit", variant="error", id="quit")
                yield Button("Cancel", variant="primary", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        else:
            self.app.pop_screen()
