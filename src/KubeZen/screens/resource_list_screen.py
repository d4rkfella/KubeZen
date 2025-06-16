import logging
from typing import Any

from textual.widgets import DataTable
from textual.message import Message

from ..core.resource_events import ResourceEventSource
from ..core.resource_registry import RESOURCE_REGISTRY
from .action_screen import ActionScreen
from .base_screen import BaseResourceScreen


log = logging.getLogger(__name__)


class RowSelected(Message):
    def __init__(self, row_key: str, cursor_row: int) -> None:
        super().__init__()
        self.row_key = row_key
        self.cursor_row = cursor_row


class ResourceListScreen(BaseResourceScreen):
    """A generic screen to display a list of Kubernetes resources."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Go Back"),
    ]

    def __init__(
        self,
        event_source: ResourceEventSource,
        resource_key: str,
        namespace: str,
    ) -> None:
        super().__init__(event_source=event_source, namespace=namespace)
        self.resource_key = resource_key
        resource_meta = RESOURCE_REGISTRY[resource_key]
        self.resource_meta = resource_meta

        # Set properties on the instance, which will be used by the base class
        self.RESOURCE_TYPE = resource_key
        self.COLUMNS = self.resource_meta["columns"]

        self.resource_emoji = self.resource_meta["emoji"]
        display_name = self.resource_meta["display_name"]
        self.title = f"{self.resource_emoji} {display_name} in: {self.active_namespace}"

    def _format_row(self, item: dict[str, Any]) -> list[Any]:
        """Format a resource item into a list of values for a table row."""
        formatter = self.resource_meta["formatter"]
        return formatter(item)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """When a resource is selected, show the available actions for it."""
        if event.row_key.value is None:
            return
        resource_name = event.row_key.value

        selected_item = next(
            (
                item
                for item in self.items
                if isinstance(item, dict)
                and item.get("metadata", {}).get("name") == resource_name
            ),
            None,
        )

        if not selected_item:
            log.warning(
                "Could not find selected item '%s' in the item list.", resource_name
            )
            return

        actual_namespace = selected_item.get("metadata", {}).get("namespace")
        if not isinstance(actual_namespace, str):
            log.warning("Namespace for %s is not a string.", resource_name)
            return

        self.app.push_screen(
            ActionScreen(
                resource_key=self.resource_key,
                namespace=actual_namespace,
                resource_name=resource_name,
                resource_emoji=str(self.resource_meta.get("emoji", "❓")),
            )
        )

    def action_show_actions(self) -> None:
        """Show the action screen for the selected resource."""
        table = self.query_one(DataTable)
        try:
            # This will raise TypeError if cursor_row is None, or IndexError if out of bounds.
            row_key = list(table.rows.keys())[table.cursor_row]
        except (IndexError, TypeError):
            # This safely handles the case where the cursor is not on a valid row.
            log.warning(
                "Action triggered with invalid cursor position: %s", table.cursor_row
            )
            return

        if row_key.value is None:
            return

        resource_name = row_key.value
        selected_item = next(
            (
                item
                for item in self.items
                if isinstance(item, dict)
                and item.get("metadata", {}).get("name") == resource_name
            ),
            None,
        )

        if not selected_item:
            log.warning(
                "Could not find selected item '%s' in the item list.", resource_name
            )
            return

        actual_namespace = selected_item.get("metadata", {}).get("namespace")
        if not isinstance(actual_namespace, str):
            log.warning("Namespace for %s is not a string.", resource_name)
            return

        self.app.push_screen(
            ActionScreen(
                resource_key=self.resource_key,
                namespace=actual_namespace,
                resource_name=resource_name,
                resource_emoji=str(self.resource_meta.get("emoji", "❓")),
            )
        )
