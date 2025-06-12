from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Any, Dict, Type, TYPE_CHECKING

# This is the standard way to resolve circular imports for type hints
if TYPE_CHECKING:
    from KubeZen.ui.views.view_base import BaseUIView


# Base class for all navigation signals
@dataclass
class NavigationSignal:
    """Base class for all navigation signals."""

    context: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.context is None:
            self.context = {}


# Specific signal classes inheriting from the base
@dataclass
class StaySignal(NavigationSignal):
    """Signal to stay on the current view, possibly requesting a data reload."""

    fzf_actions: Optional[List[str]] = None


@dataclass
class ToParentSignal(NavigationSignal):
    """Signal to navigate to the parent view in the stack."""

    pass


@dataclass(init=False)
class ToParentWithResultSignal(ToParentSignal):
    """
    Signal to navigate to the parent view and pass a result back to it.
    The parent view is expected to handle this result in its `on_view_popped_with_result` method.
    """

    result: Dict[str, Any]  # type: ignore[misc]

    def __init__(self, result: Dict[str, Any], context: Optional[Dict[str, Any]] = None):
        super().__init__(context=context)
        self.result = result


@dataclass
class PushViewSignal(NavigationSignal):
    """Signal to push a new view onto the stack."""

    # Allow either a direct class or a string key for flexibility
    view_class: Optional[Type["BaseUIView"]] = None
    view_key: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.view_class is None and self.view_key is None:
            raise ValueError("PushViewSignal requires either view_class or view_key.")


@dataclass
class ReloadSignal(NavigationSignal):
    """Signal that the current view should be reloaded."""

    pass


@dataclass
class ExitApplicationSignal(NavigationSignal):
    """Signal that the application should exit gracefully."""

    pass


@dataclass
class PopViewSignal(NavigationSignal):
    """
    Signal that the current view's context is now invalid (e.g., resource was
    deleted) and the view should be popped, returning to the parent.
    """

    pass
