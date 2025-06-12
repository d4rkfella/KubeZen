from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from types import FrameType
import signal
import asyncio

from KubeZen.core.app_services import AppServices
from KubeZen.core.events import FzfExitRequestEvent
from KubeZen.core.service_base import ServiceBase

if TYPE_CHECKING:
    from KubeZen.config import AppConfig
    from KubeZen.core.event_bus import EventBus
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator
    from KubeZen.core.fzf_ui_manager import FzfUIManager
    from KubeZen.core.kubernetes_client import KubernetesClient
    from KubeZen.core.kubernetes_watch_manager import KubernetesWatchManager


class AppController(ServiceBase):
    """
    Orchestrates the application lifecycle: initializes services, runs the main event loop,
    coordinates navigation, and manages graceful shutdown and error handling.

    Responsibilities:
    - Initialize and shut down all core services and managers
    - Run the main event loop, dispatch events, and handle signals (like SIGINT)
    - Wire up services, registries, and coordinators (but not own their logic)
    - Catch and log critical errors, trigger shutdowns, and display user-facing errors
    - Delegate view transitions to the NavigationCoordinator
    - Should not contain resource-specific or UI-specific logic
    """

    def __init__(
        self,
        config: AppConfig,
        app_services: "AppServices",
    ):
        super().__init__(app_services)
        self.config = config

        # The presence of event_bus is now guaranteed by the ServiceBase parent class.
        assert self.app_services.event_bus is not None, "EventBus must be initialized"
        self.event_bus: EventBus = self.app_services.event_bus

        assert (
            self.app_services.kubernetes_client
        ), "KubernetesClient service is missing from AppServices"
        self.kubernetes_client: KubernetesClient = self.app_services.kubernetes_client

        assert (
            self.app_services.kubernetes_watch_manager
        ), "KubernetesWatchManager service is missing from AppServices"
        self.kubernetes_watch_manager: KubernetesWatchManager = (
            self.app_services.kubernetes_watch_manager
        )

        assert (
            app_services.navigation_coordinator
        ), "NavigationCoordinator service is missing from AppServices"
        self.navigation_coordinator: NavigationCoordinator = app_services.navigation_coordinator

        assert self.app_services.fzf_ui_manager, "FzfUIManager service is missing from AppServices"
        self.fzf_ui_manager: FzfUIManager = self.app_services.fzf_ui_manager

        self.shutdown_requested = asyncio.Event()
        self._fzf_last_healthy: bool = True

        # Subscribe to application lifecycle events
        self.event_bus.subscribe(FzfExitRequestEvent, self.handle_fzf_exit_request)

        self.logger.info(
            f"AppController initialized. NavigationCoordinator: {self.navigation_coordinator}"
        )

    async def run_main_loop(self) -> None:
        self.logger.info("AppController: Starting run sequence.")
        self.shutdown_requested.clear()
        original_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self.handle_signal)

        try:
            # --- Startup logic (start services, navigation, FZF, etc.) ---
            await self._wait_for_services_ready()

            if self.kubernetes_watch_manager:
                await self.kubernetes_watch_manager.setup_watches_based_on_config()
            else:
                self.logger.error("KubernetesWatchManager not available, cannot start watches.")
                self.shutdown_requested.set()
                return

            if not self.fzf_ui_manager:
                self.logger.error("FZF UI Manager not available. Cannot start FZF.")
                self.shutdown_requested.set()
                return

            # FzfUIManager is now self-sufficient. It will call the
            # NavigationCoordinator and manage its own startup.
            if not await self.fzf_ui_manager.start_fzf():
                self.logger.error("FZF UI Manager failed to start. Requesting shutdown.")
                self.shutdown_requested.set()
                return

            self.logger.info("FZF UI started. Entering main event loop.")

            if self.fzf_ui_manager:
                asyncio.create_task(self._monitor_fzf_health())

            self.logger.info(
                "AppController: Main loop is now passively waiting for shutdown signal."
            )
            await self.shutdown_requested.wait()

        finally:
            signal.signal(signal.SIGINT, original_sigint_handler)
            self.logger.info(
                "AppController: Run sequence fully finished and SIGINT handler restored."
            )

    async def _wait_for_services_ready(self) -> None:
        """Wait for core services to be fully ready before launching FZF."""
        # This method now primarily serves as a safeguard to ensure critical
        # services were successfully injected from the core_ui_runner.
        if not all([self.fzf_ui_manager, self.kubernetes_client, self.navigation_coordinator]):
            self.logger.error("AppController: One or more critical services are not available.")
            self.shutdown_requested.set()
            raise RuntimeError("A critical service was not initialized.")

        self.logger.info("AppController: Core services are ready.")

    async def shutdown(self) -> None:
        """Coordinate the shutdown of all services in the correct order."""

        self.logger.info("AppController: Starting shutdown sequence...")
        self.shutdown_requested.set()

        # Define shutdown order - most dependent services first
        services_to_stop = [
            self.app_services.fzf_ui_manager,
            self.app_services.kubernetes_watch_manager,
            self.app_services.ui_event_handler,
            self.app_services.kubernetes_client,
        ]

        for service in services_to_stop:
            if service and hasattr(service, "stop"):
                try:
                    self.logger.info(f"Stopping {service.__class__.__name__}")
                    await asyncio.wait_for(service.stop(), timeout=5.0)
                    self.logger.info(f"Successfully stopped {service.__class__.__name__}")
                except asyncio.TimeoutError:
                    self.logger.warning(f"Timeout stopping {service.__class__.__name__}")
                except Exception as e:
                    self.logger.error(f"Error stopping {service.__class__.__name__}: {e}")

        self.logger.info("AppController: Shutdown sequence completed.")

    async def handle_fzf_exit_request(self, event: FzfExitRequestEvent) -> None:
        """Handles a user-initiated request to exit FZF."""
        self.shutdown_requested.set()

    def handle_signal(self, signum: int, frame: Optional[FrameType]) -> None:
        """Handle termination signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")

        # Immediately kill the UI to provide instant feedback to the user.
        # This is done in a fire-and-forget manner.
        if self.app_services.tmux_ui_manager:
            asyncio.create_task(self.app_services.tmux_ui_manager.shutdown_ui())

        if not self.shutdown_requested.is_set():
            self.shutdown_requested.set()
            self.logger.info(
                "AppController: shutdown_requested event set due to SIGINT. Main loop will terminate and trigger full shutdown."
            )
        else:
            self.logger.info(
                "AppController: shutdown_requested event already set (SIGINT likely handled or shutdown in progress)."
            )

    async def _monitor_fzf_health(self) -> None:
        """Background task: monitors FZF health and triggers shutdown if FZF dies unexpectedly."""
        while not self.shutdown_requested.is_set():
            try:
                if self.fzf_ui_manager:
                    is_healthy = await self.fzf_ui_manager.is_running()
                    if not is_healthy and self._fzf_last_healthy:
                        self.logger.error("FZF server died unexpectedly! Shutting down app.")
                        self.shutdown_requested.set()
                        break
                    self._fzf_last_healthy = is_healthy
            except Exception as e:
                self.logger.error("Exception during FZF health monitoring: %s", e, exc_info=True)
            await asyncio.sleep(3)  # Check every 3 seconds
