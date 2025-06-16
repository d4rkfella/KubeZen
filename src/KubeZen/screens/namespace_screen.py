from typing import Any
import logging

from textual.widgets import DataTable
from textual.message import Message

from ..core.resource_events import ResourceEventSource
from ..utils.formatting import format_age
from .action_screen import ActionScreen
from .base_screen import BaseResourceScreen
from ..core.resource_registry import RESOURCE_REGISTRY

log = logging.getLogger(__name__)


class NamespaceSelected(Message):
    """Message to indicate a namespace has been selected."""

    def __init__(self, namespace: str) -> None:
        super().__init__()
        self.active_namespace = namespace


class NamespaceScreen(BaseResourceScreen):
    """A screen to display Kubernetes namespaces."""

    BINDINGS = [
        ("ctrl+a", "open_actions", "Actions"),
    ]

    def __init__(self, event_source: ResourceEventSource) -> None:
        super().__init__(event_source=event_source, namespace="--all-namespaces--")
        self.RESOURCE_TYPE = "namespaces"
        self.COLUMNS = RESOURCE_REGISTRY["namespaces"]["columns"]
        self.resource_emoji = RESOURCE_REGISTRY["namespaces"]["emoji"]

    def _format_row(self, item: dict[str, Any]) -> list[Any]:
        return [
            item.get("metadata", {}).get("name"),
            item.get("status", {}).get("phase"),
            format_age(item.get("metadata", {})),
        ]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Event handler for when a namespace is selected."""
        if event.row_key.value is not None:
            self.post_message(NamespaceSelected(event.row_key.value))

    def action_open_actions(self) -> None:
        """Show the action screen for the selected namespace."""
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            try:
                row_key = list(table.rows.keys())[table.cursor_row]
                if row_key.value is not None:
                    namespace_name = row_key.value
                    self.app.push_screen(
                        ActionScreen(
                            resource_key="namespaces",
                            namespace=namespace_name,
                            resource_name=namespace_name,
                        )
                    )
            except IndexError:
                log.warning("Cursor row %s is out of bounds.", table.cursor_row)
