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
from .screens.main_screen import MainScreen
from .screens.quit_screen import QuitScreen

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

            # Set textual logger to DEBUG
            textual_logger = logging.getLogger("textual")
            textual_logger.setLevel(logging.DEBUG)

            # Set our app loggers to DEBUG
            app_logger = logging.getLogger("KubeZen")
            app_logger.setLevel(logging.DEBUG)

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
    """The main TUI application class."""

    SHOW_TRACEBACK = True  # Show Python traceback for debugging
    SUPPRESS_EXCEPTION_HANDLER = True  # Disable Textual's exception handling completely
    CAPTURE_EXCEPTIONS = False  # Tell Textual not to capture exceptions at all

    TITLE = "KubeZen"
    KEY_TIMEOUT = 0.1

    BINDINGS = [
        ("ctrl+d", "toggle_dark", "Toggle Dark/Light mode"),
        ("ctrl+q", "request_quit", "Quit"),
        ("ctrl+i", "inspect_widgets", "Show Widget Tree"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.kubernetes_client = KubernetesClient()
        self.tmux_manager = TmuxManager()
        self.store = WatchedResourceStore(app=self)
        self._event_source = create_resource_event_source(self.store)
        self.watch_manager = KubernetesWatchManager(
            kubernetes_client=self.kubernetes_client,
            store=self.store,
            allow_watch_bookmarks=self.config.watch_allow_bookmarks,
            list_chunk_size=self.config.watch_chunk_size,
            retry_delay_seconds=self.config.watch_retry_delay,
        )
        self._is_profiling = False

        # Set the title for debug mode
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.title = f"{self.TITLE} [DEBUG MODE]"

        self.app_logger = AppLogger()

    async def on_mount(self) -> None:
        """Event handler called when app is mounted."""
        # Conditionally add profiler bindings if in debug mode.
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.bind("f2", "start_profiling", description="Start Profiler", show=True)
            self.bind("f3", "stop_profiling", description="Stop Profiler", show=True)

        # Connect to services - let exceptions propagate up
        await self.kubernetes_client.connect()
        await self.tmux_manager.connect()

        # Start the watch manager and wait for initial lists to complete
        self.run_worker(self.watch_manager.start_and_monitor_watches())
        await self.watch_manager._initial_lists_complete.wait()

        # Now that we have data, show the main screen
        await self.push_screen(MainScreen())

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        if self.watch_manager:
            await self.watch_manager.stop()
        if self.kubernetes_client:
            await self.kubernetes_client.close()
        self.app_logger.stop()

        # Stop yappi profiler if it was running and save data
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            try:
                if yappi.is_running():
                    yappi.stop()
                    stats = yappi.get_func_stats()  # pylint: disable=no-member
                    stats.save(  # pylint: disable=no-member
                        str(self.config.paths.yappi_stats_path), type="callgrind"
                    )
                    log.info(
                        "Profiler data saved to %s", self.config.paths.yappi_stats_path
                    )
            except NameError:
                pass  # Yappi not installed, nothing to stop/save

    def action_start_profiling(self) -> None:
        """Starts the yappi profiler."""
        if self._is_profiling:
            return

        try:
            # Configure yappi for more meaningful profiling
            yappi.set_clock_type("cpu")  # Use CPU time
            yappi.clear_stats()  # Clear any previous stats

            # Profile our code and relevant Textual calls
            def filter_func(info: str) -> bool:
                # Include our code and Textual-related calls
                return info.startswith("KubeZen") or "textual" in info.lower()

            yappi.filter_callback = filter_func
            yappi.start(builtins=False)  # Don't profile Python builtins
            log.info(
                "Profiler started. Output will be saved to %s",
                self.config.paths.temp_dir,
            )
            self._is_profiling = True
            self.notify(
                "Profiling started",
                title="Profiling",
                severity="information",
            )
        except Exception as e:
            log.exception("Failed to start profiling")
            self.notify(
                f"Failed to start profiling: {str(e)}",
                title="Error",
                severity="error",
            )

    def action_stop_profiling(self) -> None:
        """Stop profiling and save results."""
        if not self._is_profiling:
            return

        try:
            # Stop profiling before getting stats
            yappi.stop()
            self._is_profiling = False

            # Get stats after stopping
            func_stats = yappi.get_func_stats()

            # Save to file
            prof_file = os.path.join(self.config.paths.temp_dir, "kubezen.prof")
            func_stats.save(prof_file, "CALLGRIND")

            # Print top 10 functions by total time to the log
            log.info("Top 10 functions by total time:")
            # Redirect yappi output to a string
            import io

            output = io.StringIO()
            func_stats.print_all(out=output)
            log.info("\n%s", output.getvalue())
            output.close()

            self.notify(
                f"Profiling data saved to {prof_file}",
                title="Profiling Stopped",
                severity="information",
            )
        except Exception as e:
            log.exception("Failed to stop profiling")
            self.notify(
                f"Failed to stop profiling: {str(e)}",
                title="Error",
                severity="error",
            )

    def action_request_quit(self) -> None:
        """Action to display the quit dialog."""
        self.push_screen(QuitScreen())

    def action_inspect_widgets(self) -> None:
        """Show the widget tree in a notification."""
        def format_widget(widget, level=0):
            indent = "  " * level
            info = f"{indent}{widget.__class__.__name__}"
            if widget.id:
                info += f" (id={widget.id})"
            return info

        def build_tree(widget, level=0):
            tree = [format_widget(widget, level)]
            for child in widget.children:
                tree.extend(build_tree(child, level + 1))
            return tree

        tree = build_tree(self.screen)
        self.notify("\n".join(tree), title="Widget Tree", timeout=10)

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
        config = AppConfig.get_instance()
        app = KubeZenTuiApp(config=config)
        app.run()
    except Exception:
        # Let the kubernetes client handle the error display and exit
        pass
