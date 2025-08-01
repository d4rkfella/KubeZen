from __future__ import annotations
import logging
import os
import queue
import importlib
import inspect
import pkgutil
import asyncio
from itertools import chain
from logging.handlers import QueueHandler, QueueListener
from typing import Any, ClassVar, cast
import re
import aiohttp
from aiohttp import (
    ClientConnectorError,
    ClientOSError,
    ServerDisconnectedError,
    ClientPayloadError,
)
import urllib3
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.widgets import (
    Header,
    Footer,
    TabbedContent,
)
from textual.reactive import reactive
from textual.widgets.tree import TreeNode
from KubeZen.core.watch_manager import WatchManager
from KubeZen.config import AppConfig
from KubeZen.core.kubernetes_client import KubernetesClient
from KubeZen.core.model_discovery import discover_standard_models, discover_crd_models
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from KubeZen.screens.manifest_editor_screen import ManifestEditorScreen
from KubeZen.containers.resource_tab_pane import ResourceTabPane
from KubeZen.core.age_tracker import AgeTracker
from KubeZen.containers.sidebar import Sidebar
from KubeZen.containers.resource_list import ResourceList
from KubeZen.actions.base_action import BaseAction
from KubeZen.screens.action_screen import ActionScreen
from KubeZen.models.base import UIRow


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
        """Initialize the logger."""
        self.log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
        self.log_listener: QueueListener | None = None

        # Get log level from env, default to DEBUG if not set or invalid
        log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

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
            root_logger.setLevel(log_level)  # set from env

            app_logger = logging.getLogger("KubeZen")
            app_logger.setLevel(log_level)  # set from env

            self.log_listener.start()

            log.info("--- KubeZen TUI Logger Initialized ---")

            k8s_client_logger = logging.getLogger("kubernetes_asyncio.client.rest")
            # Maybe set kubernetes client log level separately or from env too
            k8s_client_logger.setLevel(logging.INFO)

        def stop(self) -> None:
            if self.log_listener:
                self.log_listener.stop()

    def stop(self) -> None:
        """Stop the log listener."""
        if self.log_listener:
            self.log_listener.stop()


class KubeZen(App[None]):
    """A Textual application for KubeZen."""

    CSS = """
    Screen {
        layers: sidebar overlay;
    }
    Tooltip {
        background: transparent;
        color: auto 90%;
        offset-x: 3;
        offset-y: -2;
    }
    TabbedContent:empty {
        display: none;
    }
    """

    TITLE = "KubeZen"
    SUB_TITLE = "Kubernetes TUI"
    AUTO_FOCUS = ""
    # KEY_TIMEOUT = 0.1

    _connected_to_context: bool = False
    _namespaces_watch_manager: WatchManager | None = None
    _namespaces_subscriptions: list = []
    _actions: dict[str, list[BaseAction]] = {}

    available_namespaces: reactive[set[str]] = reactive(set(), layout=False, init=False)
    show_sidebar = reactive(False)

    BINDINGS = [
        ("s", "toggle_sidebar", "Toggle Sidebar"),
        ("ctrl+d", "toggle_dark", "Toggle Dark Mode"),
        ("ctrl+n", "create_resource", "Create Resource"),
        ("ctrl+w", "close_current_tab", "Close Tab"),
        ("ctrl+q", "request_quit", "Quit App"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._app_logger = AppLogger.get_instance()
        self._config = AppConfig.get_instance()
        self._resource_models = dict(discover_standard_models())
        assert self._resource_models, "No Kubernetes resource models were discovered."
        self._kubernetes_client: KubernetesClient | None = None
        self._tmux_manager: TmuxManager | None = None
        self._age_tracker: AgeTracker | None = None

        if os.environ.get("KUBEZEN_DEBUG") == "1":
            self.sub_title = "KubeZen (Debug Mode)"

    def compose(self) -> ComposeResult:
        """Compose the main screen layout."""
        yield Header()
        yield TabbedContent()
        yield Sidebar("Contexts")
        yield Footer()

    @property
    def kubernetes_client(self) -> KubernetesClient:
        """Returns the Kubernetes client."""
        assert (
            self._kubernetes_client is not None
        ), "Kubernetes client is not initialized"
        return self._kubernetes_client

    @property
    def config(self) -> AppConfig:
        """Returns the app configuration."""
        return self._config

    @property
    def resource_models(self):
        """Returns the resource models."""
        return self._resource_models

    @property
    def age_tracker(self) -> AgeTracker:
        """Returns the age tracker instance."""
        if not self._age_tracker:
            self._age_tracker = AgeTracker.get_instance(self)
        return self._age_tracker

    @property
    def tmux_manager(self) -> TmuxManager:
        """Returns the tmux manager."""
        if not self._tmux_manager:
            self._tmux_manager = TmuxManager.get_instance(self._config.session_name)
        return self._tmux_manager

    async def on_load(self) -> None:
        self._discover_actions()
        self._kubernetes_client = await KubernetesClient.get_instance()

    def action_toggle_sidebar(self) -> None:
        """Toggle the sidebar visibility."""
        self.show_sidebar = not self.show_sidebar

    def watch_show_sidebar(self, show_sidebar: bool) -> None:
        """Set or unset visible class when reactive changes."""
        self.query_one(Sidebar).set_class(show_sidebar, "-visible")

    async def _connect_to_context(self, node: TreeNode) -> None:
        """Connect to the Kubernetes context and update the UI."""
        if self._connected_to_context:
            return
        
        original_label = node.label
        try:
            node.set_label(Text.assemble(original_label, (" ●", "yellow")))

            async for key, model in discover_crd_models(self.kubernetes_client):
                self._resource_models[key] = model

            connected_label = Text.assemble(original_label, (" ●", "green"))
            node.set_label(connected_label)

            await self.query_one(Sidebar).update_tree()
            self._connected_to_context = True

        except asyncio.TimeoutError:
            node.set_label(Text.assemble(original_label, (" ●", "red")))
            self.notify(
                "Connection timed out.",
                severity="error",
                timeout=10,
            )

    def subscribe_and_track(self, signal, callback):
        signal.subscribe(self, callback)
        self._namespaces_subscriptions.append((signal, callback))
    
    def _normalize_label(self, label: str) -> str:
        return re.sub(r"\W|^(?=\d)", "_", label)

    async def on_tree_node_expanded(self, event: Sidebar.NodeExpanded) -> None:
        """Handle node expansion events."""
        if event.node.data and event.node.data.get("type") == "context":
            await self._connect_to_context(event.node)
    
    async def on_tree_node_selected(self, event: Sidebar.NodeSelected) -> None:
        """Handle tree node selection events."""
        node = event.node
        if not node or not node.data:
            return

        if node.data["type"] == "context":
            await self._connect_to_context(event.node)

        if node.data["type"] == "resource":

            model_class: type[UIRow] = node.data["model_class"]

            if not self._namespaces_watch_manager and model_class.namespaced:
                self._namespaces_watch_manager = WatchManager(
                    self, self.resource_models["namespaces"]
                )

                self.subscribe_and_track(
                    self._namespaces_watch_manager.signals.resource_added,
                    self.on_namespace_added,
                )
                self.subscribe_and_track(
                    self._namespaces_watch_manager.signals.resource_deleted,
                    self.on_namespace_deleted,
                )

                resources, resource_version = (
                    await self._namespaces_watch_manager.get_initial_list("all")
                )

                self.available_namespaces = {
                    ns.name for ns in resources if ns and ns.name is not None
                }
                await self._namespaces_watch_manager.create_watch_task(
                    "all", resource_version
                )

            tab_id = self._normalize_label(node.data["label"])

            tabbed_content = self.query_one(TabbedContent)
            if not tabbed_content.query(f"#{tab_id}"):
                await tabbed_content.add_pane(
                    ResourceTabPane(
                        title=model_class.display_name,
                        model_class=model_class,
                        available_namespaces=self.available_namespaces,
                        id=tab_id,
                    )
                )
            tabbed_content.active = tab_id
            tabbed_content.active_pane.query_one(ResourceList).focus()
    
    async def action_close_current_tab(self) -> None:
        tabbed_content = self.query_one(TabbedContent)

        if not tabbed_content.active:
            return

        await tabbed_content.remove_pane(tabbed_content.active)

        if self._namespaces_watch_manager:
            namespaced_lists_remain = False
            for pane in tabbed_content.query(ResourceTabPane):
                if pane:
                    resource_list = pane.query_one(ResourceList)
                    if resource_list.model_class.namespaced:
                        namespaced_lists_remain = True
                        break

            if not namespaced_lists_remain:
                await self._namespaces_watch_manager.stop()
                self._namespaces_subscriptions.clear()
                self._namespaces_watch_manager = None
                self.available_namespaces.clear()

        sidebar = self.query_one(Sidebar)

        if not tabbed_content.active_pane:
            sidebar.select_node(None)
            return

        def find_node_by_label(node, tab_id):
            data = getattr(node, "data", {})
            if isinstance(data, dict) and self._normalize_label(data.get("label", "")) == tab_id:
                return node
            for child in node.children:
                found = find_node_by_label(child, tab_id)
                if found:
                    return found
            return None

        node_to_select = find_node_by_label(sidebar.root, tabbed_content.active)
        sidebar.select_node(node_to_select)

    def on_namespace_added(self, data: dict[str, Any]) -> None:
        """A signal handler for when a namespace is added."""
        resource = data["resource"]
        self.available_namespaces = self.available_namespaces | {resource.name}

    def on_namespace_deleted(self, data: dict[str, Any]) -> None:
        """A signal handler for when a namespace is deleted."""
        resource = data["resource"]
        self.available_namespaces = {
            ns for ns in self.available_namespaces if ns != resource.name
        }

    def watch_available_namespaces(self, available_namespaces: set[str]) -> None:
        log.debug("The list of available namespaces changed: %s", available_namespaces)

        tab_container = self.query_one(TabbedContent)

        for pane in tab_container.query(ResourceTabPane):
            if pane.model_class.namespaced:
                pane.available_namespaces = available_namespaces

    @on(ResourceList.RowSelected)
    def on_row_selected(self, event: ResourceList.RowSelected) -> None:
        """Handle row selection events."""
        if event.row_key.value is None:
            return

        resource_list = cast(ResourceList, event.data_table)
        row_info = resource_list.resources[event.row_key.value]

        if not row_info:
            return

        all_actions = set(
            chain(self._actions.get(row_info.plural, []), self._actions.get("*", []))
        )

        executable_actions = sorted(
            (a for a in all_actions if a.can_perform(row_info)), key=lambda a: a.name
        )

        if executable_actions:
            action_screen = ActionScreen(row_info, executable_actions)
            self.push_screen(action_screen)

    def _discover_actions(self) -> None:
        package_name = "KubeZen.actions"
        if not package_name:
            log.error("Could not determine package for action discovery.")
            return

        package = importlib.import_module(package_name)
        package_path = getattr(package, "__path__", None)
        if not package_path:
            log.error(f"Could not get path for package {package_name}")
            return

        for _, module_name, _ in pkgutil.walk_packages(
            package_path, prefix=f"{package.__name__}."
        ):
            if "base_action" in module_name:
                continue

            try:
                module = importlib.import_module(module_name)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseAction) and obj is not BaseAction:
                        action_instance = obj(self)
                        supported_types: set[str] = getattr(
                            obj, "supported_resource_types", set()
                        )
                        for resource_type in supported_types:
                            if resource_type not in self._actions:
                                self._actions[resource_type] = []
                            self._actions[resource_type].append(action_instance)

            except Exception as e:
                log.error(f"Failed to load action module {module_name}: {e}")

    def action_create_resource(self) -> None:
        """Action to open the new resource editor."""
        self.push_screen(ManifestEditorScreen())

    @work
    async def action_request_quit(self) -> None:
        """Action to display the quit dialog."""
        buttons = [
            ButtonInfo(label="Quit", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]
        screen = ConfirmationScreen(
            prompt="Are you sure you want to quit KubeZen?",
            buttons=buttons,
        )
        if await self.app.push_screen_wait(screen):
            self.exit()

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        self._app_logger.stop()
        await self.kubernetes_client.close()


async def main() -> None:
    """The main entry point for the KubeZen TUI application."""
    app = KubeZen()
    await app.run_async()
    import sys

    sys.exit(app.return_code or 0)


if __name__ == "__main__":
    asyncio.run(main())
