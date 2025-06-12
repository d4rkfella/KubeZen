from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from dataclasses import dataclass
import logging

from KubeZen.core.kubernetes_watch_manager import KubernetesWatchManager

if TYPE_CHECKING:
    from KubeZen.config import AppConfig
    from KubeZen.core.kubernetes_client import KubernetesClient
    from KubeZen.core.user_input_manager import UserInputManager
    from KubeZen.core.fzf_ui_manager import FzfUIManager
    from KubeZen.core.tmux_ui_manager import TmuxUIManager
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator
    from KubeZen.core.ui_event_handler import UiEventHandler
    from KubeZen.core.event_bus import EventBus


@dataclass
class AppServices:
    """A container for shared application services passed to managers and views."""

    # Core Services
    config: Optional[AppConfig] = None
    logger: Optional[logging.Logger] = None
    event_bus: Optional[EventBus] = None
    fzf_ui_manager: Optional[FzfUIManager] = None
    user_input_manager: Optional[UserInputManager] = None
    tmux_ui_manager: Optional[TmuxUIManager] = None
    navigation_coordinator: Optional[NavigationCoordinator] = None
    kubernetes_client: Optional[KubernetesClient] = None
    kubernetes_watch_manager: Optional[KubernetesWatchManager] = None
    ui_event_handler: Optional[UiEventHandler] = None

    # Runtime state
    current_namespace: Optional[str] = None
    shutdown_requested: bool = False

    def set_current_namespace(self, namespace: Optional[str]) -> None:
        old_namespace = self.current_namespace
        self.current_namespace = namespace
        if self.logger:
            self.logger.info(
                f"Current namespace changed from '{old_namespace}' to '{self.current_namespace}'."
            )
