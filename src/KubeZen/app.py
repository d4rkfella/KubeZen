from __future__ import annotations
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener
from typing import Any, ClassVar, cast, Optional

import yaml
from textual.app import App
from textual.widget import Widget

import yappi  # type: ignore[import-untyped]

from KubeZen.config import AppConfig
from KubeZen.core.kubernetes_client import KubernetesClient
from KubeZen.core.model_discovery import discover_resource_models, discover_crd_models
from KubeZen.screens.main_screen import MainScreen
from KubeZen.screens.action_screen import ActionScreen
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from KubeZen.screens.manifest_editor_screen import ManifestEditorScreen
from KubeZen.core.age_tracker import AgeTracker

from KubeZen.core.tmux_manager import TmuxManager

log = logging.getLogger(__name__)


class AppLogger:
    """Manages the application's logging setup."""

    # --- Singleton Pattern ---
    _instance: ClassVar[AppLogger | None] = None

    @classmethod
    def get_instance(cls) -> AppLogger:
        """Returns the singleton instance of the AppLogger."""
        if cls._instance is None:
            cls._instance = AppLogger()
            log.info("AppLogger singleton initialized.")
        return cls._instance

    def __init__(self) -> None:
        """Initialize the logger.

        Note: Use get_instance() instead of calling this directly.
        """
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
            app_logger = logging.getLogger("KubeZen")
            app_logger.setLevel(logging.DEBUG)

            self.log_listener.start()

            log.info("--- KubeZen TUI Logger Initialized ---")

            k8s_client_logger = logging.getLogger("kubernetes_asyncio.client.rest")
            k8s_client_logger.setLevel(logging.INFO)

    def stop(self) -> None:
        """Stop the log listener."""
        if self.log_listener:
            self.log_listener.stop()


class KubeZenTuiApp(App[None]):
    """A Textual application for KubeZen."""

    SHOW_TRACEBACK = True
    SUPPRESS_EXCEPTION_HANDLER = True
    CAPTURE_EXCEPTIONS = False

    TITLE = "KubeZen"
    SUB_TITLE = "Kubernetes TUI"
    KEY_TIMEOUT = 0.1

    SCREENS = {
        "main": MainScreen,
        "action": ActionScreen,
    }

    BINDINGS = [
        ("ctrl+d", "toggle_dark", "Toggle Dark Mode"),
        ("ctrl+c", "request_quit", "Quit"),
        ("ctrl+n", "create_resource", "Create Resource"),
        ("ctrl+p", "start_profiling", "Start Profiler"),
        ("ctrl+s", "stop_profiling", "Stop Profiler"),
        ("ctrl+i", "inspect_widgets", "Show Widget Tree"),
    ]

    CSS = """
    Tooltip {
        background: transparent;
        color: auto 90%;
        offset-x: 3;
        offset-y: -2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._age_tracker = None
        self._config = AppConfig.get_instance()
        self._resource_models = discover_resource_models()
        assert self._resource_models, "No Kubernetes resource models were discovered."
        self._kubernetes_client = KubernetesClient.get_instance(self)
        self._is_profiling = False
        self._tmux_manager = TmuxManager.get_instance(self._config.session_name)

        # Initialize the singleton services
        self._app_logger = AppLogger.get_instance()
        
        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.sub_title = "KubeZen (Debug Mode)"

    @property
    def kubernetes_client(self) -> KubernetesClient:
        """Returns the Kubernetes client."""
        return self._kubernetes_client

    @property
    def config(self) -> AppConfig:
        """Returns the app configuration."""
        return self._config

    @property
    def main_screen(self) -> MainScreen:
        """Returns the main screen."""
        return cast(MainScreen, self.get_screen("main"))

    @property
    def resource_models(self):
        """Returns the resource models."""
        return self._resource_models

    @property
    def age_tracker(self) -> AgeTracker:
        """Returns the age tracker instance."""
        return self._age_tracker

    @property
    def tmux_manager(self) -> TmuxManager:
        """Returns the tmux manager."""
        return self._tmux_manager
    
    async def on_mount(self) -> None:
        await self.push_screen("main")


    def action_start_profiling(self) -> None:
        if self._is_profiling:
            return
        try:
            yappi.set_clock_type("cpu")
            yappi.clear_stats()
            yappi.start(builtins=False)
            log.info("Profiler started.")
            self._is_profiling = True
            self.notify("Profiling started", title="Profiling", severity="information")
        except Exception as e:
            log.exception("Failed to start profiling")
            self.notify(
                f"Failed to start profiling: {str(e)}", title="Error", severity="error"
            )

    def action_stop_profiling(self) -> None:
        if not self._is_profiling:
            return
        try:
            yappi.stop()
            self._is_profiling = False
            func_stats = yappi.get_func_stats()
            prof_file = os.path.join(self.config.paths.temp_dir, "kubezen.prof")
            func_stats.save(prof_file, "CALLGRIND")
            log.info("Profiler data saved to %s", prof_file)
            self.notify(
                f"Profiling data saved to {prof_file}",
                title="Profiling Stopped",
                severity="information",
            )
        except Exception as e:
            log.exception("Failed to stop profiling")
            self.notify(
                f"Failed to stop profiling: {str(e)}", title="Error", severity="error"
            )

    def _handle_create_resource(self, yaml_content: Optional[str]) -> None:
        """Callback to handle the result from the manifest editor."""
        if not yaml_content:
            return  # User cancelled

        async def apply() -> None:
            try:
                parsed = yaml.safe_load(yaml_content)

                result = await self.kubernetes_client.create_resource(parsed)

                if not result:
                    raise RuntimeError("Resource creation returned no result.")

                # Handle single or multiple results
                resources = result if isinstance(result, list) else [result]

                for res in resources:
                    metadata = getattr(res, "metadata", None)
                    name = getattr(metadata, "name", "Unknown") if metadata else "Unknown"
                    kind = getattr(res, "kind", "Unknown")
                    self.notify(
                        f"Successfully created {kind} '{name}'",
                        title="Success",
                        severity="information",
                    )

            except Exception as e:
                self.notify(
                    f"Failed to create resource: {e}",
                    title="Error",
                    severity="error",
                    timeout=10,
                )

        self.run_worker(apply(), exclusive=True)

    def action_create_resource(self) -> None:
        """Action to open the new resource editor."""
        self.push_screen(ManifestEditorScreen(), self._handle_create_resource)

    def action_request_quit(self) -> None:
        """Action to display the quit dialog."""
        buttons = [
            ButtonInfo(label="Quit", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]
        screen = ConfirmationScreen(
            prompt="Are you sure you want to quit KubeZen?",
            buttons=buttons,
        )
        self.push_screen(screen, self._handle_quit_confirm)

    def _handle_quit_confirm(self, confirmed: Any) -> None:
        """Handle the result of the quit confirmation dialog."""
        if confirmed:
            self.exit()

    def action_inspect_widgets(self) -> None:
        """Show the widget tree in a notification."""

        def format_widget(widget: Widget, level: int = 0) -> str:
            indent = "  " * level
            info = f"{indent}{widget.__class__.__name__}"
            if widget.id:
                info += f" (id={widget.id})"
            return info

        def build_tree(widget: Widget, level: int = 0) -> list[str]:
            tree = [format_widget(widget, level)]
            for child in widget.children:
                tree.extend(build_tree(child, level + 1))
            return tree

        tree_str = "\n".join(build_tree(self.screen))
        self.notify(tree_str, title="Widget Tree", timeout=30)

    def _handle_exception(self, error: Exception) -> None:
        """Log unhandled exceptions."""
        log.critical("Unhandled exception in Textual app", exc_info=error)
        self.exit(message=str(error))

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        self._app_logger.stop()
        if self._kubernetes_client:
            await self._kubernetes_client.close()

    async def initialize_resources(self) -> None:
        """Initialize the resources."""
        await self._kubernetes_client.connect()
        crd_models = await discover_crd_models(self._kubernetes_client)
        self._resource_models.update(crd_models)
        self._age_tracker = AgeTracker.get_instance(self)


def main() -> None:
    """Main function to run the KubeZen TUI app."""
    # Ensure this runs within a Tmux session
    #if "TMUX" not in os.environ:
        #print("KubeZen must be run inside a Tmux session.")
        #return

    # Set up yappi for profiling if debug mode is enabled
    if os.environ.get("KUBEZEN_DEBUG") == "1":
        yappi.set_clock_type("wall")

    app = KubeZenTuiApp()
    app.run()

if __name__ == "__main__":
    main()
