from __future__ import annotations
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

if TYPE_CHECKING:
    from textual.app import App


class ManifestEditorScreen(ModalScreen[str | None]):
    """A modal screen for creating a new Kubernetes resource from a YAML manifest."""

    DEFAULT_CSS = """
    ManifestEditorScreen {
        align: center middle;
    }

    #dialog {
        width: 80%;
        height: 80%;
        border: thick $primary;
        background: $boost;
    }

    #editor-container {
        padding: 1;
        height: 1fr;
    }

    TextArea {
        border: round $primary;
        height: 1fr;
        width: 1fr;
    }

    #buttons {
        height: auto;
        padding: 0 1;
        align-horizontal: right;
    }

    Button {
        margin: 1;
    }
    """

    BINDINGS = [("escape", "app.pop_screen", "Dismiss")]

    def __init__(self, initial_text: str = "") -> None:
        super().__init__()
        self.initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Create Resource from Manifest", classes="action-title")
            with Vertical(id="editor-container"):
                yield TextArea(
                    text=self.initial_text,
                    language="yaml",
                    theme="monokai",
                    id="manifest-editor",
                )
            with Horizontal(id="buttons"):
                yield Button("Create", variant="success", id="create")
                yield Button("Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        """Focus the text area on mount."""
        self.query_one(TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "create":
            text_area = self.query_one(TextArea)
            self.dismiss(text_area.text)
