from __future__ import annotations
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener

from textual.app import App

import yappi  # type: ignore[import-untyped]

from .config import AppConfig
from .core.kubernetes_client import KubernetesClient
from .core.kubernetes_watch_manager import KubernetesWatchManager
from .core.tmux_manager import TmuxManager
from .core.watched_resource_store import WatchedResourceStore
from .core.store_factory import create_resource_event_source
from .screens.action_screen import ActionScreen
from .screens.namespace_screen import NamespaceScreen, NamespaceSelected
from .screens.quit_screen import QuitScreen
from .screens.resource_list_screen import ResourceListScreen
from .screens.resource_type_screen import ResourceTypeScreen, ResourceTypeSelected


# Set up a logger for this module
log = logging.getLogger(__name__)


class AppLogger:
    """Manages the application's logging setup."""

    def __init__(self) -> None:
        self.log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
        self.log_listener: QueueListener | None = None
        log_file = os.environ.get("KUBEZEN_LOG_FILE")
        if log_file:
            log_handler = logging.FileHandler(log_file, mode="w")
            log_formatter = logging.Formatter(
                "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
            )
            log_handler.setFormatter(log_formatter)

            self.log_listener = QueueListener(self.log_queue, log_handler)
            root_logger = logging.getLogger()
            root_logger.addHandler(QueueHandler(self.log_queue))
            root_logger.setLevel(logging.DEBUG)

            self.log_listener.start()

            log.info("--- KubeZen TUI Logger Initialized ---")

            # Suppress noisy debug logs from the Kubernetes client
            k8s_client_logger = logging.getLogger("kubernetes_asyncio.client.rest")
            k8s_client_logger.setLevel(logging.INFO)

    def stop(self) -> None:
        """Stops the log listener and performs cleanup."""
        if self.log_listener:
            self.log_listener.stop()


class KubeZenTuiApp(App[None]):
    """The main application class for KubeZen TUI."""

    SHOW_TRACEBACK = True  # Show Python traceback for debugging
    #SUPPRESS_EXCEPTION_HANDLER = True  # Disable Textual's exception handling completely
    #CAPTURE_EXCEPTIONS = False  # Tell Textual not to capture exceptions at all

    TITLE = "KubeZen"

    KEY_TIMEOUT = 0.1

    CSS_PATH = "app.css"

    BINDINGS = [
        ("ctrl+d", "toggle_dark", "Toggle Dark/Light mode"),
        ("ctrl+q", "request_quit", "Quit"),
    ]

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.store = WatchedResourceStore(self)
        self._event_source = create_resource_event_source(self.store)
        self.kubernetes_client = KubernetesClient()
        self.watch_manager = KubernetesWatchManager(
            kubernetes_client=self.kubernetes_client,
            store=self.store,
        )
        self.tmux_manager = TmuxManager()

        # Set the title for debug mode. Bindings are handled in on_mount.
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.title = f"{self.TITLE} [DEBUG MODE]"

        self.app_logger = AppLogger()  # Use the new AppLogger class

    async def on_mount(self) -> None:
        """Event handler called when app is mounted."""
        # Conditionally add profiler bindings if in debug mode.
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.bind("f2", "start_profiling", description="Start Profiler", show=True)
            self.bind("f3", "stop_profiling", description="Stop Profiler", show=True)

        # Connect to services - let exceptions propagate up
        await self.kubernetes_client.connect()  # Pass no args since we set them in __init__
        await self.tmux_manager.connect()
        self.run_worker(self.watch_manager.start_and_monitor_watches())

        # Start with the namespace selection screen
        self.push_screen(NamespaceScreen(event_source=self._event_source))

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        if self.watch_manager:
            await self.watch_manager.stop()
        if self.kubernetes_client:
            await self.kubernetes_client.close()
        self.app_logger.stop()  # Call stop on the AppLogger instance

        # Stop yappi profiler if it was running and save data
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            try:
                if yappi.is_running():
                    yappi.stop()
                    stats = yappi.get_func_stats()  # pylint: disable=no-member
                    stats.save(  # pylint: disable=no-member
                        str(self.config.paths.yappi_stats_path),
                        type="callgrind"
                    )
                    log.info(
                        "Profiler data saved to %s", self.config.paths.yappi_stats_path
                    )
            except NameError:
                pass  # Yappi not installed, nothing to stop/save

    def action_start_profiling(self) -> None:
        """Starts the yappi profiler."""
        self.notify("Starting profiler...", title="Profiler")
        try:
            yappi.set_clock_type("cpu")
            yappi.start()
            log.info("Profiler started.")
        except NameError:
            self.notify(
                "Yappi is not installed. Profiler functionality is unavailable.",
                title="Profiler Error",
                severity="error",
            )

    def action_stop_profiling(self) -> None:
        """Stops the yappi profiler and saves the results."""
        try:
            if not yappi.is_running():
                self.notify(
                    "Profiler is not running.", title="Profiler", severity="warning"
                )
                return

            self.notify("Stopping profiler and saving results...", title="Profiler")
            yappi.stop()
            log.info("Profiler stopped.")

            # Use config for output path
            output_file = str(self.config.paths.yappi_stats_path)
            stats = yappi.get_func_stats()  # pylint: disable=no-member
            stats.save(output_file, type="callgrind")  # pylint: disable=no-member
            self.notify(f"Profiler data saved to {output_file}", title="Profiler")
            log.info("Profiler data saved to %s", output_file)
        except NameError:
            self.notify(
                "Yappi is not installed. Profiler functionality is unavailable.",
                title="Profiler Error",
                severity="error",
            )
        except Exception as e:
            log.error("Failed to save profiler data: %s", e, exc_info=True)
            self.notify(
                f"Error saving profiler data: {e}",
                title="Profiler Error",
                severity="error",
            )

        # Clear stats for the next profiling session
        try:
            yappi.clear_stats()
        except NameError:
            pass  # Yappi not installed, nothing to clear

    def action_request_quit(self) -> None:
        """Action to display the quit dialog."""
        self.push_screen(QuitScreen())

    def on_namespace_selected(self, message: NamespaceSelected) -> None:
        """Event handler for when a namespace is selected in the NamespaceScreen."""
        if message.active_namespace:
            self.push_screen(ResourceTypeScreen(namespace=message.active_namespace))

    def on_resource_type_selected(self, message: ResourceTypeSelected) -> None:
        """Event handler for when a resource type is selected."""
        # When a resource type is selected, we always show the generic list screen for it.
        self.push_screen(
            ResourceListScreen(
                event_source=self._event_source,
                resource_key=message.resource_key,
                namespace=message.active_namespace,
            )
        )

    def on_action_screen_action_selected(
        self, message: ActionScreen.ActionSelected
    ) -> None:
        """Event handler for when an action is selected from the ActionScreen."""
        try:
            action_class = message.action_class
            action_instance = None

            resource_obj = self.store.get_one(
                message.resource_key,
                message.namespace,
                message.resource_name,
            )
            if resource_obj:
                action_instance = action_class(
                    app=self,
                    resource=resource_obj,
                    object_name=message.resource_name,
                    resource_key=message.resource_key,
                )
            else:
                self.notify(
                    f"Could not find resource {message.resource_name}",
                    title="Error",
                    severity="error",
                )
                return

            if action_instance:
                self.run_worker(
                    action_instance.run(),
                    name=f"action_{action_class.__name__}",
                    group="actions",
                )
        except Exception:
            log.critical("Caught exception during action execution:", exc_info=True)
            self.notify(
                "Action failed! See crash output in terminal for details.",
                title="Action Error",
                severity="error",
            )

    def _handle_exception(self, error: Exception) -> None:
        """Handles exceptions that occur within the Textual event loop.
        
        Args:
            error: The exception that was raised.
        """
        log.critical("Unhandled exception in Textual app", exc_info=error)
        self.exit(message=str(error))


def main() -> None:
    """Main entry point for the application."""
    try:
        app = KubeZenTuiApp()
        app.run()
    except Exception:
        # Let the kubernetes client handle the error display and exit
        pass
