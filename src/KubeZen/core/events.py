from __future__ import annotations
from typing import Dict, Any
from dataclasses import dataclass

from KubeZen.core.event_bus import Event


class FzfSelectionEvent(Event):
    """Event triggered when an item is selected in FZF."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


class EnterKeyEvent(Event):
    """Event triggered when the Enter key is pressed in FZF."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


@dataclass
class FzfRefreshRequestEvent(Event):
    """Event indicating a manual refresh (e.g., Ctrl-R) was triggered in FZF."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


class UnhandledEvent(Event):
    """Event for event keys that are not explicitly handled."""

    def __init__(self, data: Dict[str, Any]):
        self.event_key = data.get("event_key")
        self.data = data


class FzfQueryChangeEvent(Event):
    """Event triggered when the FZF query string changes."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


class FzfClearQueryEvent(Event):
    """Event triggered when the FZF query is cleared (e.g., by ctrl-u)."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


class ResourceStoreUpdateEvent(Event):
    """Event indicating that a resource in the WatchedResourceStore has changed."""

    def __init__(self, resource_kind_plural: str, namespace: str, change_details: Dict[str, Any]):
        self.resource_kind_plural = resource_kind_plural
        self.namespace = namespace
        self.change_details = change_details


class FzfExitRequestEvent(Event):
    """Event indicating the user has requested to exit FZF (e.g., via Ctrl+C)."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
