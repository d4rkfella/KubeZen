from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any, TYPE_CHECKING, cast
from rich.text import Text
from textual.events import Click
from textual import on
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    SelectionList,
    Label,
    Footer,
    Input,
    TabbedContent,
    TabPane,
)
from textual.reactive import reactive
from textual.widgets.selection_list import Selection
from textual.css.query import NoMatches
from textual.widgets.tree import TreeNode

from KubeZen.actions.base_action import BaseAction
from KubeZen.containers.sidebar import Sidebar
from KubeZen.core.watch_manager import WatchManager
from KubeZen.containers.resource_list import ResourceList
from KubeZen.screens.action_screen import ActionScreen

if TYPE_CHECKING:
    from KubeZen.app import KubeZenTuiApp
    from KubeZen.models import UIRow

log = logging.getLogger(__name__)


class MainScreen(Screen[None]):
    """Main screen of the application."""

    # Use type ignore here since we know KubeZenTuiApp is a valid subclass of App[Any]
    app: KubeZenTuiApp  # type: ignore[assignment]

    BINDINGS = [
        ("tab", "toggle_sidebar", "Toggle Sidebar"),
        ("ctrl+c", "request_quit", "Quit"),
        ("ctrl+w", "close_current_tab", "Close Tab"),
    ]

    _connected_to_context: bool = False
    _is_updating_selection: bool = False
    _namespaces_watch_manager: WatchManager | None = None
    _namespaces_subscriptions: list = []
    _actions: dict[str, list[BaseAction]] = {}

    available_namespaces: reactive[list[str]] = reactive([], layout=False, init=False)

    DEFAULT_CSS = """
    Screen {
        layers: overlay;
    }

    MainScreen {
        height: 100%;
        width: 100%;
        padding: 0;
        margin: 0;
    }

    Sidebar {
        width: 50;
        height: 100%;
        background: $boost;
        border-right: round $primary;
        padding: 1;
        dock: left;
        layer: overlay;
        transition: offset 170ms in_out_cubic;
        offset-x: 0;
    }

    Sidebar Tree > .tree-node.--cursor {
        background: $accent;
    }

    Sidebar.-hidden {
        offset-x: -50;
    }

    .namespace-button {
        border: round $primary;
        width: 30;
        padding: 0 1;
        offset-x: 1;
        dock: top;
        background: transparent;
    }

    .namespace-button.-active {
        border: round $accent;
    }

    .namespace-select {
        width: 30;
        max-height: 15;
        padding: 0;
        dock: top;
        background: transparent;
        border: round $accent;
        margin-left: 1;
        layer: overlay;
        margin-top: 3;
    }

    .namespace-select.-hidden {
        display: none;
    }

    .search-bar.-namespaced {
        width: 30;
        background: transparent;
        border: round $primary;
        margin-left: 32;
        dock: top;
    }
    .search-bar.-non-namespaced {
        width: 30;
        background: transparent;
        border: round $primary;
        dock: top;
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the main screen layout."""
        yield TabbedContent(id="main-content-container")
        yield Sidebar("Contexts")
        yield Footer()

    def on_mount(self) -> None:
        self._discover_actions()

    def action_toggle_sidebar(self) -> None:
        """Toggle the sidebar visibility."""
        self.query_one(Sidebar).toggle_class("-hidden")

    async def _connect_to_context(self, node: TreeNode) -> None:
        """Connect to the Kubernetes context and update the UI."""
        if not self._connected_to_context:
            original_label = node.label
            await self.app.initialize_resources()
            connected_label = Text.assemble(original_label, (" ●", "green"))
            node.set_label(connected_label)

            await self.query_one(Sidebar).update_tree()
            self._connected_to_context = True

    @on(Sidebar.NodeExpanded)
    async def on_tree_node_expanded(self, event: Sidebar.NodeExpanded) -> None:
        """Handle node expansion events."""
        if self._connected_to_context:
            return
        if event.node.data and event.node.data.get("type") == "context":
            await self._connect_to_context(event.node)

    @on(Sidebar.NodeSelected)
    async def on_tree_node_selected(self, event: Sidebar.NodeSelected) -> None:
        """Handle tree node selection events."""
        if self.app.focused:
            self.app.focused.blur()

        node = event.node
        if not node or not node.data:
            return

        if node.data.get("type") == "resource":

            model_class: type[UIRow] = node.data.get("model_class")

            if not self._namespaces_watch_manager and model_class.namespaced:
                namespace_model_class = self.app.resource_models["namespaces"]

                self._namespaces_watch_manager = WatchManager(self.app, namespace_model_class)
                self._namespaces_watch_manager.namespaces = ["all"]

                if future := self._namespaces_watch_manager.current_update:
                    new_resources = await future
                    if new_resources:  # Only update if we got resources back
                        self.available_namespaces = sorted(
                            [ns.name for ns in new_resources if ns and ns.name is not None]
                        )
                self._namespaces_subscriptions.append(
                    self._namespaces_watch_manager.signals.resource_added.subscribe(
                        self, self.on_namespace_added
                    )
                )
                self._namespaces_subscriptions.append(
                    self._namespaces_watch_manager.signals.resource_deleted.subscribe(
                        self, self.on_namespace_deleted
                    )
                )

            plural = model_class.plural.lower()
            tab_id = f"resource-list-{plural}"

            content_switcher = self.query_one("#main-content-container", TabbedContent)
            if (
                content_switcher.query(f"#{tab_id}")
                and content_switcher.active != tab_id
            ):
                content_switcher.active = tab_id
                return
            if content_switcher.active == tab_id:
                return

            await self._create_tab(model_class, tab_id)

    @on(Click)
    def on_click(self, event: Click) -> None:
        """Handle click events to close the namespace selector when clicking outside."""
        active_pane = self.query_one(
            "#main-content-container", TabbedContent
        ).active_pane
        if not active_pane:
            return

        try:
            namespace_select = active_pane.query_one(".namespace-select", SelectionList)
            namespace_button = active_pane.query_one(".namespace-button", Label)
        except NoMatches:
            return

        if namespace_select.has_class("-hidden"):
            return

        # Determine which widget was clicked at the event's coordinates.
        target_widget, _ = self.get_widget_at(*event.screen_offset)

        clicked_in_selector = False
        current_widget = target_widget
        while current_widget:
            if current_widget is namespace_select or current_widget is namespace_button:
                clicked_in_selector = True
                break
            current_widget = current_widget.parent

        # If the click was not inside the selector or on the button, hide the selector.
        if not clicked_in_selector:
            namespace_select.add_class("-hidden")
            namespace_button.remove_class("-active")

    async def action_close_current_tab(self) -> None:
        """Close the currently active tab and clean up associated resources."""
        tabbed_content = self.query_one("#main-content-container", TabbedContent)
        active_pane = tabbed_content.active_pane
        if not active_pane:
            return

        await tabbed_content.remove_pane(active_pane.id)

        if self.app.focused:
            self.app.focused.blur()

    def on_namespace_added(self, data: dict[str, Any]) -> None:
        """A signal handler for when a namespace is added."""
        resource = data["resource"]
        if resource.name:
            self.available_namespaces = sorted(
                self.available_namespaces + [resource.name]
            )

    def on_namespace_deleted(self, data: dict[str, Any]) -> None:
        """A signal handler for when a namespace is deleted."""
        resource = data["resource"]
        self.available_namespaces = sorted(
            [ns for ns in self.available_namespaces if ns != resource.name]
        )

    @on(Click, ".namespace-button")
    def on_namespace_button_click(self, event: Click) -> None:
        """Handle clicks on the namespace button."""
        active_pane = self.query_one(
            "#main-content-container", TabbedContent
        ).active_pane
        if not active_pane:
            return
        namespace_button = active_pane.query_one(".namespace-button", Label)
        namespace_select = active_pane.query_one(".namespace-select", SelectionList)
        if namespace_select.has_class("-hidden"):
            namespace_button.add_class("-active")
            namespace_select.remove_class("-hidden")
        else:
            namespace_button.remove_class("-active")
            namespace_select.add_class("-hidden")

        event.stop()

    @staticmethod
    def _update_namespace_selection_state(
        resource_list: ResourceList,
        namespace_select: SelectionList,
        current_selection: set[str],
        previous_selection: set[str],
    ) -> None:
        """Update the selection list based on the user's interaction."""
        changed_items = previous_selection.symmetric_difference(current_selection)
        if not changed_items:
            return

        item_clicked = changed_items.pop()
        user_toggled_all = item_clicked == "all"

        if user_toggled_all:
            resource_list.first_selected_namespace = None
            if "all" in current_selection:
                namespace_select.select_all()
            else:
                namespace_select.deselect_all()
        elif "all" in previous_selection:
            resource_list.first_selected_namespace = item_clicked
            namespace_select.deselect_all()
            namespace_select.select(item_clicked)
        else:
            if not getattr(resource_list, "first_selected_namespace", None):
                resource_list.first_selected_namespace = item_clicked
            elif (
                getattr(resource_list, "first_selected_namespace", None)
                not in current_selection
            ):
                specific_selections = sorted(
                    [ns for ns in current_selection if ns != "all"]
                )
                resource_list.first_selected_namespace = (
                    specific_selections[0] if specific_selections else None
                )

    @staticmethod
    def _prepare_display_label(
        resource_list: ResourceList, final_selection: list[str]
    ) -> list[str]:
        """Prepare the properly ordered list of namespaces for the display label."""
        first_selected = getattr(resource_list, "first_selected_namespace", None)
        if first_selected and first_selected in final_selection:
            return [first_selected] + sorted(
                [item for item in final_selection if item != first_selected]
            )
        return sorted(final_selection)

    @on(SelectionList.SelectedChanged, ".namespace-select")
    def on_namespace_selection_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        """Handle changes to the namespace selection list."""
        if getattr(self, "_is_updating_selection", False):
            return

        try:
            self._is_updating_selection = True
            namespace_select = event.selection_list
            if not (active_pane := namespace_select.parent):
                return
            resource_list = active_pane.query_one(ResourceList)

            previous_selection = set(resource_list.selected_namespaces)
            current_selection = set(namespace_select.selected)

            self._update_namespace_selection_state(
                resource_list, namespace_select, current_selection, previous_selection
            )

            final_selection = namespace_select.selected
            resource_list.selected_namespaces = sorted(list(final_selection))
            selected_for_display = self._prepare_display_label(
                resource_list, final_selection
            )
            self.update_namespace_label(selected_for_display)
        finally:
            self._is_updating_selection = False

    def watch_available_namespaces(self, available_namespaces: list[str]) -> None:
        log.debug("The list of available namespaces changed: %s", available_namespaces)
        valid_namespaces = [ns for ns in available_namespaces if ns is not None]

        tab_container = self.query_one("#main-content-container", TabbedContent)

        with self.app.batch_update():

            for pane in tab_container.query(TabPane):
                tab_id = pane.id
                if not tab_id:
                    continue

                resource_list = pane.query_one(ResourceList)
                if not resource_list.model_class.namespaced:
                    continue

                namespace_select = pane.query_one(".namespace-select", SelectionList)
                if not namespace_select:
                    continue

                namespace_select.clear_options()
                namespace_select.add_options(
                    [Selection("All Namespaces", "all")]
                    + [Selection(name, name) for name in valid_namespaces]
                )

                current_selection = cast(
                    list[str], resource_list.selected_namespaces
                )

                if "all" in current_selection:
                    selection = ["all"] + sorted(valid_namespaces)
                    namespace_select.toggle_all()
                else:
                    selection = [
                        ns for ns in current_selection if ns in valid_namespaces
                    ]
                    for ns in selection:
                        namespace_select.toggle(ns)

                resource_list.selected_namespaces = selection

    def update_namespace_label(self, selected_for_display: list[str]) -> None:
        """Update the namespace label based on the current selection."""
        active_pane = self.query_one(
            "#main-content-container", TabbedContent
        ).active_pane
        if not active_pane:
            return
        if not selected_for_display:
            text = "Select Namespace"
        elif "all" in selected_for_display:
            text = "All Namespaces"
        elif len(selected_for_display) == 1:
            text = selected_for_display[0]
        else:
            text = f"{selected_for_display[0]} +{len(selected_for_display) - 1}"

        namespace_button = active_pane.query_one(".namespace-button", Label)
        button_width = 25
        padding = max(1, button_width - len(text) - 1)
        padded_text = f"{text}{' ' * padding}▼"
        namespace_button.update(padded_text)

    @on(Input.Changed, ".search-bar")
    def on_search_input_changed(self) -> None:
        """Handle search input changes for the active tab."""
        active_pane = self.query_one(
            "#main-content-container", TabbedContent
        ).active_pane
        if not active_pane:
            return
        search_input = (
            active_pane.query_one(".search-bar", Input).value.replace(" ", "").lower()
        )
        active_list = active_pane.query_one(ResourceList)
        active_list.search_input = search_input

    async def _create_tab(
        self, model_class: type[UIRow], tab_id: str
    ) -> None:
        """Create a new tab for the given model class."""
        content_switcher = self.query_one("#main-content-container", TabbedContent)

        tab_title = model_class.display_name
        new_resource_list = ResourceList(model_class=model_class)

        search_bar = Input(placeholder=f"Search {model_class.display_name}...")

        if model_class.namespaced:
            label = Label(classes="namespace-button")
            namespaces_list = self.available_namespaces
            selections = [Selection("All Namespaces", "all", True)] + [
                Selection(ns, ns, True) for ns in namespaces_list
            ]
            namespaces_selection_list = SelectionList(
                *selections, classes="namespace-select -hidden"
            )
            new_resource_list.selected_namespaces = ["all"] + namespaces_list
            search_bar.add_class("search-bar", "-namespaced")
            tab_pane = TabPane(
                tab_title,
                label,
                namespaces_selection_list,
                search_bar,
                new_resource_list,
                id=tab_id,
            )

        else:
            search_bar.add_class("search-bar", "-non-namespaced")
            tab_pane = TabPane(
                tab_title,
                search_bar,
                new_resource_list,
                id=tab_id,
            )
            new_resource_list.selected_namespaces = ["all"]

        await content_switcher.add_pane(pane=tab_pane)
        content_switcher.active = tab_id

        if new_resource_list.model_class.namespaced:
            self.update_namespace_label(["all"])

    @on(ResourceList.RowSelected)
    def on_row_selected(self, event: ResourceList.RowSelected) -> None:
        """Handle row selection events."""
        if event.row_key.value is None:
            return

        resource_list = cast(ResourceList, event.data_table)
        row_info = resource_list.resources[event.row_key.value]

        if row_info:
            # Get actions for the specific resource type and generic ("*") actions.
            actions_for_type = self._actions.get(row_info.plural, [])
            generic_actions = self._actions.get("*", [])
            # Use a set to handle potential duplicates and then sort for consistent order.
            potential_actions = sorted(
                list(set(actions_for_type + generic_actions)), key=lambda a: a.name
            )

            # Filter by runtime state: Can this action run on this specific resource?
            executable_actions = [
                action for action in potential_actions if action.can_perform(row_info)
            ]

            if executable_actions:
                action_screen = ActionScreen(row_info, executable_actions)
                self.app.push_screen(action_screen)

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

        log.debug(f"Discovering actions in package: {package_name} ({package_path})")

        for _, module_name, _ in pkgutil.walk_packages(
            package_path, prefix=f"{package.__name__}."
        ):
            if "base_action" in module_name:
                continue

            try:
                module = importlib.import_module(module_name)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseAction) and obj is not BaseAction:
                        action_instance = obj(self.app)
                        supported_types = getattr(obj, "supported_resource_types", set())
                        for resource_type in supported_types:
                            if resource_type not in self._actions:
                                self._actions[resource_type] = []
                            self._actions[resource_type].append(action_instance)

            except Exception as e:
                log.error(f"Failed to load action module {module_name}: {e}")
