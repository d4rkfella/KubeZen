from __future__ import annotations
from typing import Dict, Type, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from KubeZen.ui.views.view_base import BaseUIView


class ViewRegistry:
    """
    A central registry for mapping view keys (strings) to view classes.
    This allows for dynamic lookup and instantiation of views, decoupling
    the NavigationCoordinator from direct knowledge of all view classes.
    """

    DEFAULT_VIEW = "NamespaceSelectionView"

    def __init__(self) -> None:
        self._views: Dict[str, Type[BaseUIView]] = {}
        self._default_view_registered = False

    def register_view(self, view_key: str, view_class: Type[BaseUIView]) -> None:
        """
        Registers a view class with a given key.

        Args:
            view_key: The string key to associate with the view.
            view_class: The view class itself.
        """
        if view_key in self._views:
            # Potentially log a warning or raise an error if a key is overwritten,
            # depending on desired behavior. For now, we'll allow overwriting.
            pass
        self._views[view_key] = view_class

        # Track if the default view has been registered
        if view_key == self.DEFAULT_VIEW:
            self._default_view_registered = True

    def get_view_class(self, view_key: str) -> Optional[Type[BaseUIView]]:
        """
        Retrieves a view class by its key.

        Args:
            view_key: The string key of the view to retrieve.

        Returns:
            The view class if found, otherwise None.
        """
        return self._views.get(view_key)

    def get_default_view(self) -> str:
        """
        Returns the default view key that should be used as the entry point.
        This is guaranteed to be a valid view key as it's set during registration.

        Raises:
            RuntimeError: If the default view has not been registered.
        """
        if not self._default_view_registered:
            available_views = ", ".join(sorted(self._views.keys()))
            raise RuntimeError(
                f"Default view '{self.DEFAULT_VIEW}' has not been registered! "
                f"Available views: {available_views}"
            )
        return self.DEFAULT_VIEW
