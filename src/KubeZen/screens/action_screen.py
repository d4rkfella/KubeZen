from __future__ import annotations
import re

from textual import on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import ListView, ListItem, Static, Label
from textual.containers import Container
from textual.events import Click

from KubeZen.models.base import UIRow

import logging

log = logging.getLogger(__name__)


class ActionScreen(ModalScreen[None]):
    """A modal screen that displays a list of available actions for a resource."""

    BINDINGS = [("escape", "dismiss", "Dismiss")]

    DEFAULT_CSS = """
    ActionScreen {
        align: center middle;
    }

    #modal-container {
        width: 60;
        height: auto;
        border: round $primary;
        background: $boost;
    }

    #action-title {
        content-align: center middle;
        width: 100%;
        padding: 1;
    }

    #action-list {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, row_info, executable_actions) -> None:
        super().__init__(name="action_screen")
        self.row_info: UIRow = row_info
        self.executable_actions = executable_actions

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Static(f"Actions for {self.row_info.name}", id="action-title")
            yield ListView(
                *[
                    ListItem(Label(action.name), id=self._sanitize_id(action.name))
                    for action in self.executable_actions
                ],
                id="action-list",
            )

    @staticmethod
    def _sanitize_id(text: str) -> str:
        """Convert text to a valid widget ID."""
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
        return f"action_{sanitized.lower()}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection of an action."""
        selected_action = next(
            (
                action
                for action in self.executable_actions
                if self._sanitize_id(action.name) == event.item.id
            ),
            None,
        )
        if selected_action:
            self.dismiss(None)
            self.app.run_worker(selected_action.execute(self.row_info))

    def __del__(self) -> None:
        log.debug("Action screen destroyed")

    @on(Click)
    def dismiss_on_click_outside(self, event: Click) -> None:
        """Dismisses the screen when clicking outside the modal container."""
        modal_container = self.query_one("#modal-container")
        if not modal_container.region.contains(event.screen_x, event.screen_y):
            self.dismiss()
