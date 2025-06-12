from __future__ import annotations
from abc import abstractmethod
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple, ClassVar
import uuid
import logging

from KubeZen.core import signals
from KubeZen.ui.view_managers import ViewFileManager, FZFItemFormatter

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator
    from KubeZen.config import AppConfig


class BaseUIView:
    """
    Base class for all UI views in KubeZen.
    Provides common functionality and interface for views.
    """

    # View type identifier, can be overridden by subclasses
    VIEW_TYPE: ClassVar[str] = ""

    # Constants for go back functionality
    GO_BACK_ACTION_CODE = "go_back"
    NO_ITEMS_ACTION_CODE = "no_items"
    NO_ITEMS_ICON = "⚠️"
    ERROR_FETCHING_ACTION_CODE = "error_fetching"
    ERROR_FETCHING_ICON = "❌"

    def __init__(
        self,
        navigation_coordinator: NavigationCoordinator,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the base view with required services and context.

        Args:
            navigation_coordinator: The navigation coordinator for view management
            context: Optional context data for the view
        """
        self._navigation_coordinator = navigation_coordinator
        self._context = context or {}
        self._view_session_id = str(uuid.uuid4())
        self.fzf_formatter = FZFItemFormatter(self._view_session_id)
        self.file_manager = ViewFileManager()

    @property
    def app_services(self) -> "AppServices":
        """Access the app services."""
        return self._navigation_coordinator.app_services

    @property
    def context(self) -> Dict[str, Any]:
        """Access the view context."""
        return self._context

    @context.setter
    def context(self, value: Dict[str, Any]) -> None:
        """Set the view context."""
        self._context = value

    @property
    def logger(self) -> logging.Logger:
        """Access the logger instance."""
        logger_instance = self.app_services.logger
        if logger_instance is None:
            raise RuntimeError("Logger is not available in AppServices.")
        return logger_instance

    @property
    def config(self) -> "AppConfig":
        """Access the app configuration."""
        config = self.app_services.config
        if config is None:
            raise RuntimeError("AppConfig is not available in AppServices.")
        return config

    @abstractmethod
    async def get_fzf_configuration(self) -> Tuple[List[str], Dict[str, Any]]:
        """Get the FZF configuration for this view."""
        pass

    @abstractmethod
    async def process_selection(
        self, action_code: str, display_text: str, selection_context: Dict[str, Any]
    ) -> Optional[signals.NavigationSignal]:
        """Process a user selection."""
        pass

    def get_go_back_fzf_item(self) -> str:
        """Get the formatted 'go back' item for FZF."""
        return self.fzf_formatter.format_go_back_item()

    def write_fzf_items_to_file(self, items: List[str]) -> Optional[str]:
        """Write FZF items to a file."""
        return self.file_manager.write_items(items)

    def get_view_session_id(self) -> str:
        """Get the unique session ID for this view instance."""
        return self._view_session_id

    async def on_view_popped_with_result(
        self, result: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Optional[signals.NavigationSignal]:
        """Handle result from a popped child view."""
        self.logger.debug(f"on_view_popped_with_result hook called with result: {result}")
        return None
