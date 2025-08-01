from __future__ import annotations
import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea
import json


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

    BINDINGS = [
        ("escape", "app.pop_screen", "Dismiss"),
    ]

    def __init__(self, initial_text: str = "") -> None:
        super().__init__()
        self.initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Create resource", classes="action-title")
            with Vertical(id="editor-container"):
                yield TextArea.code_editor(
                    text=self.initial_text,
                    language="yaml",
                    theme="monokai",
                    id="manifest-editor",
                )
            with Horizontal(id="buttons"):
                yield Button("Create", variant="success", id="create")
                yield Button("Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "create":
            await self._validate_and_submit()

    async def _validate_and_submit(self) -> None:
        text_area = self.query_one(TextArea)
        yaml_content = text_area.text

        try:
            output = await self._run_kubectl_apply(yaml_content)
            data = json.loads(output)
            name = data.get("metadata", {}).get("name", "Unknown")
            kind = data.get("kind", "Unknown")

            self.app.notify(
                f"Successfully created {kind} '{name}'",
                severity="information",
            )

        except Exception as api_error:
            self.app.notify(
                f"Failed to apply manifest:\n{api_error}",
                severity="error",
                timeout=10,
            )

    async def _run_kubectl_apply(self, yaml_content: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "kubectl",
            "apply",
            "-f",
            "-",
            "-o",
            "json",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(input=yaml_content.encode())

        if process.returncode != 0:
            raise RuntimeError(stderr.decode().strip())

        return stdout.decode().strip()
