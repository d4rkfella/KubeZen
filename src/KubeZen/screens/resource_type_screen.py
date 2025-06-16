from typing import Any
import logging

from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label
from textual.app import ComposeResult
from textual.message import Message

from KubeZen.core.resource_registry import RESOURCE_REGISTRY, VIEWABLE_RESOURCE_TYPES

log = logging.getLogger(__name__)


class ResourceTypeListItem(ListItem):
    """A ListItem that holds the resource key."""

    def __init__(self, *args: Any, resource_key: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.resource_key = resource_key


class ResourceTypeSelected(Message):
    """Message to indicate a resource type has been selected."""

    def __init__(self, resource_key: str, namespace: str):
        super().__init__()
        self.resource_key = resource_key
        self.active_namespace = namespace


class ResourceTypeScreen(Screen[None]):
    """Screen for selecting a Kubernetes resource type."""

    BINDINGS = [("escape", "app.pop_screen", "Go Back")]

    def __init__(self, namespace: str) -> None:
        super().__init__()
        self.active_namespace = namespace
        self.title = f"📁 Resources in: {self.active_namespace}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ListView(id="resource_type_list")
        yield Footer()

    def on_mount(self) -> None:
        """Event handler for when the screen is mounted."""

        list_view = self.query_one(ListView)
        sorted_resources = sorted(
            [
                (key, RESOURCE_REGISTRY[key])
                for key in VIEWABLE_RESOURCE_TYPES
                if key in RESOURCE_REGISTRY
            ],
            key=lambda item: item[1]["display_name"],
        )

        for key, meta in sorted_resources:
            emoji = meta.get("emoji", "❓")
            display_name = meta.get("display_name", key.capitalize())
            list_view.append(
                ResourceTypeListItem(Label(f"{emoji} {display_name}"), resource_key=key)
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Event handler for when a resource type is selected."""
        if not isinstance(event.item, ResourceTypeListItem):
            return

        resource_key = event.item.resource_key
        log.info(
            "ListView item selected on ResourceTypeScreen. Key: '%s', Namespace: '%s'",
            resource_key,
            self.active_namespace,
        )
        self.post_message(
            ResourceTypeSelected(
                resource_key=resource_key, namespace=self.active_namespace
            )
        )
