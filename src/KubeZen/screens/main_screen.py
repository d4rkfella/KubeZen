from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Container
from textual.screen import Screen
from textual.widgets import Header, Footer, Tree, Static, Label, Input, SelectionList
from textual.events import Click
from textual.message import Message

from ..core.resource_registry import RESOURCE_REGISTRY
from ..core.resource_events import (
    ResourceAddedSignal, 
    ResourceModifiedSignal, 
    ResourceDeletedSignal, 
    ResourceFullRefreshSignal
)
from .resource_list_screen import ResourceListWidget

import logging

log = logging.getLogger(__name__)


class Sidebar(Container):
    def compose(self) -> ComposeResult:
        """Compose the sidebar layout."""
        yield Tree("KubeZen", id="resource-tree")

    def on_mount(self) -> None:
        """Handle mount event."""
        self.add_class("sidebar")
        tree = self.query_one("#resource-tree", Tree)
        tree.show_root = False
        tree.show_guides = False

class EmptyStateWidget(Static):
    """Widget to display when no namespaces are selected."""
    
    DEFAULT_CSS = """
    EmptyStateWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
        background: $surface;
    }
    """
    
    def __init__(self) -> None:
        super().__init__("Item list is empty")

class MainContent(Container):
    """Main content area of the application."""
    
    def compose(self) -> ComposeResult:
        with Horizontal(id="top-controls-row"):
            yield Label("Select Namespace", id="namespace-button")
            yield Input(placeholder="Search....", id="search")
        yield Container(id="main-content-container")

    def update_namespace_button(self, namespace: str | None = None, additional_count: int = 0) -> None:
        """Update the namespace button text with consistent arrow placement."""
        button = self.query_one("#namespace-button")
        button_width = 24  # Reduced to ensure arrow visibility
        
        if namespace == "all":
            text = "All Namespaces"
        elif namespace == "No namespaces selected":
            text = namespace
        elif namespace and additional_count > 0:
            text = f"{namespace} +{additional_count}"
        elif namespace:
            text = namespace
        else:
            text = "Select Namespace"
            
        padding = max(1, button_width - len(text) - 1)
        padded_text = f"{text}{' ' * padding}▼"
        button.update(padded_text)


class MainScreen(Screen[None]):
    """The main screen for the KubeZen TUI."""
    
    BINDINGS = [
        ("tab", "toggle_sidebar", "Toggle Sidebar"),
    ]

    CSS = """
    Screen {
        layers: base overlay sidebar;
    }

    #resource-tree {
        margin: 1;
        height: 1fr;
        overflow-y: auto;
    }

    #resource-tree .tree--guides {
        display: none;
    }

    #resource-tree .tree--guide-intersection {
        display: none !important;
    }

    #resource-tree .tree--guide-child {
        display: none !important;
    }

    #resource-tree .tree--guide-parent {
        display: none !important;
    }

    #resource-tree .tree--guide-leaf {
        display: none !important;
    }

    .sidebar {
        width: 30;
        height: 100%;
        dock: left;
        background: $boost;
        border-right: round $primary;
        padding: 0;
        layer: sidebar;
        transition: offset 300ms in_out_cubic;
        offset-x: 0;
    }

    .sidebar.-hidden {
        offset-x: -30;
    }

    MainContent {
        height: 100%;
        width: 100%;
        padding: 0;
        margin: 0;
        layer: base;
        dock: bottom;
    }

    #main-content-container {
        height: 90%;
        width: 1fr;
    }

    #top-controls-row {
        height: 5;
        align: left middle;
        padding: 1 0;
    }

    #namespace-button {
        border: round $primary;
        width: 30;
        padding: 0 1;
        margin-right: 1;
    }

    #namespace-button:hover {
        border: round $accent;
    }

    #namespace-button.-active {
        border: round $accent;
    }

    #namespace-select {
        background: transparent;
        border: round $accent;
        overflow-y: auto;
        max-height: 15;
        dock: top;
        width: 30;
        margin-top: 4;
    }

    #namespace-select.-hidden {
        display: none;
    }

    #namespace-select--search {
        dock: top;
        width: 100%;
        padding: 0 1;
        background: $boost;
        border-bottom: heavy $primary;
    }

    #namespace-select--container {
        padding: 0;
    }

    #namespace-select--option {
        padding: 0 1;
    }

    #namespace-select--option:hover {
        background: $accent;
        color: $text;
    }

    #namespace-select--empty {
        padding: 1;
        color: $text-muted;
    }
    """

    # Widget references
    _resource_tree: Tree | None = None

    # State
    _current_namespaces: set[str] = {"all"}
    _namespace_selection_order: list[str] = ["all"]  # Track selection order
    _current_resource_key: str | None = None
    _current_resource_type: str | None = None
    _initializing: bool = True  # Flag to prevent selection events during init
    _namespace_select_visible: bool = False  # Track dropdown visibility

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_resource_type = None

    def compose(self) -> ComposeResult:
        """Compose the main screen layout."""
        yield MainContent()
        yield SelectionList(("All Namespaces", "all", True), id="namespace-select", classes="-hidden")
        yield Sidebar()

    @on(SelectionList.SelectedChanged, "#namespace-select")
    async def on_namespace_select_changed(self, event: SelectionList.SelectedChanged) -> None:
        """Handle namespace selection changes."""
        # Skip selection events during initialization
        if self._initializing:
            return
            
        log.debug("Namespace selection changed. Current selections: %s", event.selection_list.selected)
        
        # Get current state
        selection_list = event.selection_list
        selected = list(selection_list.selected)  # Keep as list to preserve order
        selected_set = set(selected)
        
        # Skip if nothing changed
        if selected_set == self._current_namespaces:
            return
            
        # Get the most recently highlighted value
        changed_value = None
        if selection_list.highlighted is not None:
            changed_value = selection_list.get_option_at_index(selection_list.highlighted).value
            
        # Handle "all" selection
        if changed_value == "all":
            if "all" in selected_set:
                # Select all namespaces
                self._current_namespaces = set(opt.value for opt in selection_list.options)
                self._namespace_selection_order = ["all"]
                # Visually select all options
                for option in selection_list.options:
                    selection_list.select(option.value)
            else:
                # Deselect all namespaces
                self._current_namespaces = set()
                self._namespace_selection_order = []
                # Visually deselect all options
                for option in selection_list.options:
                    selection_list.deselect(option.value)
        else:
            # If "all" was selected and we clicked a specific namespace
            if "all" in self._current_namespaces and changed_value:
                # First clear all selections
                self._current_namespaces = set()
                self._namespace_selection_order = []
                for option in selection_list.options:
                    selection_list.deselect(option.value)
                # Then select just the clicked namespace
                self._current_namespaces = {changed_value}
                self._namespace_selection_order = [changed_value]
                selection_list.select(changed_value)
            else:
                # Normal selection handling
                self._current_namespaces = selected_set
                # Update selection order
                if changed_value:
                    if changed_value in self._namespace_selection_order:
                        # Remove from order if deselected
                        if changed_value not in selected_set:
                            self._namespace_selection_order.remove(changed_value)
                    else:
                        # Add to order if selected
                        if changed_value in selected_set:
                            self._namespace_selection_order.append(changed_value)
            
        # Update button text
        main_content = self.query_one(MainContent)
        if not self._current_namespaces:
            main_content.update_namespace_button()  # Will show "Select Namespace"
        elif "all" in self._current_namespaces:
            main_content.update_namespace_button("all")
        elif self._namespace_selection_order:
            first_ns = self._namespace_selection_order[0]
            additional_count = len(self._current_namespaces) - 1
            main_content.update_namespace_button(first_ns, additional_count)
            
        # Update resource list if we have a current resource type
        if self._current_resource_type:
            namespace_to_set = None if "all" in self._current_namespaces else list(self._current_namespaces)
            await self._update_resource_list(self._current_resource_type, namespace_to_set)

    @on(Click, "#namespace-button")
    def handle_namespace_button_click(self) -> None:
        """Handle namespace button clicks."""
        namespace_select = self.query_one("#namespace-select")
        namespace_button = self.query_one("#namespace-button")
        self._namespace_select_visible = not self._namespace_select_visible
        
        if self._namespace_select_visible:
            namespace_select.remove_class("-hidden")
            namespace_button.add_class("-active")
        else:
            namespace_select.add_class("-hidden")
            namespace_button.remove_class("-active")

    async def on_click(self, event: Click) -> None:
        """Handle clicks outside dropdowns and inputs."""
        namespace_select = self.query_one("#namespace-select", SelectionList)
        namespace_button = self.query_one("#namespace-button", Label)
        search_input = self.query_one("#search", Input)

        # Handle namespace dropdown
        if self._namespace_select_visible:
            # Check if click was outside both the button and dropdown
            if (event.control not in (namespace_select, namespace_button) and 
                not any(parent in (namespace_select, namespace_button) for parent in event.control.ancestors)):
                # Hide the dropdown
                namespace_select.add_class("-hidden")
                namespace_button.remove_class("-active")
                self._namespace_select_visible = False

        # Handle search input focus
        if (event.control != search_input and 
            not any(parent == search_input for parent in event.control.ancestors)):
            # Remove focus from search input
            search_input.blur()

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle_class("-hidden")

    def on_screen_suspend(self) -> None:
        """Propagate suspend to the resource list widget."""
        resource_list = self.query(ResourceListWidget)
        if resource_list:
            resource_list.first().on_screen_suspend()

    def on_screen_resume(self) -> None:
        """Propagate resume to the resource list widget."""
        resource_list = self.query(ResourceListWidget)
        if resource_list:
            resource_list.first().on_screen_resume()

    async def on_mount(self) -> None:
        """Handle mount event."""
        self._resource_tree = self.query_one("#resource-tree", Tree)
        await self._update_tree()
        await self._start_namespace_watch()
        self._initializing = False

    async def _update_tree(self) -> None:
        """Update the resource tree with contexts and resources."""
        # Get available contexts and current context
        contexts = await self.app.kubernetes_client.get_available_contexts()
        current_context = await self.app.kubernetes_client.get_current_context()

        # Clear and rebuild tree
        tree = self.query_one("#resource-tree", Tree)
        tree.clear()

        # Add contexts as top-level nodes
        for ctx in contexts:
            node = tree.root.add(ctx, {"type": "context", "name": ctx})
            if ctx == current_context:
                # Expand current context and add resource groups
                node.expand()
                # Add resource groups under the current context
                workloads = node.add("Workloads", {"type": "group", "name": "workloads"})
                workloads.add_leaf("Pods", {"type": "resource", "resource_key": "pods"})
                workloads.add_leaf("Deployments", {"type": "resource", "resource_key": "deployments"})
                workloads.add_leaf("StatefulSets", {"type": "resource", "resource_key": "statefulsets"})
                workloads.add_leaf("DaemonSets", {"type": "resource", "resource_key": "daemonsets"})

                network = node.add("Network", {"type": "group", "name": "network"})
                network.add_leaf("Services", {"type": "resource", "resource_key": "services"})

                storage = node.add("Storage", {"type": "group", "name": "storage"})
                storage.add_leaf("PersistentVolumeClaims", {"type": "resource", "resource_key": "pvcs"})

                config = node.add("Config", {"type": "group", "name": "config"})
                config.add_leaf("Namespaces", {"type": "resource", "resource_key": "namespaces"})

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle node selection in the tree."""
        if not event.node.data:
            return

        node_type = event.node.data.get("type")
        if node_type == "context":
            # Switch context
            context_name = event.node.data.get("name")
            if context_name:
                # Switch context and refresh tree
                await self.app.kubernetes_client.connect(context_name)
                await self._update_tree()
                # After switching context, refresh namespaces
                await self._start_namespace_watch()
        elif node_type == "resource":
            # Handle resource selection
            resource_key = event.node.data.get("resource_key")
            if resource_key:
                self._current_resource_type = resource_key
                namespace_to_set = None if "all" in self._current_namespaces else list(self._current_namespaces)
                await self._update_resource_list(resource_key, namespace_to_set)
                self.action_toggle_sidebar()

    async def _update_resource_list(self, resource_key: str, namespace: str | list[str] | None) -> None:
        """Update the resource list with the selected resource type."""
        log.debug("Updating resource list. Key: %s, Namespace: %s", resource_key, namespace)
        container = self.query_one("#main-content-container")
        await container.remove_children()
        
        # Show empty state if no namespaces are selected
        if not namespace and not self._current_namespaces:
            await container.mount(EmptyStateWidget())
        else:
            widget = ResourceListWidget(resource_key, namespace=namespace)
            await container.mount(widget)
        log.debug("Resource list updated")

    @on(Input.Changed, "#search")
    async def on_search_input_changed(self, event: Input.Changed) -> None:
        search_text = event.value
        container = self.query_one("#main-content-container")
        resource_list = container.query(ResourceListWidget)
        if resource_list:
            await resource_list.first()._filter_items(search_text)

    async def _start_namespace_watch(self) -> None:
        """Start watching for namespace events and populate the selector."""
        initial_namespaces, _ = await self.app._event_source.subscribe_and_get_list(
            resource_type="namespaces", listener=self
        )
        await self._update_namespace_select(initial_namespaces)

    async def _update_namespace_select(self, namespaces: list[dict[str, Any]]) -> None:
        """Updates the namespace select widget."""
        # Get the current SelectionList
        selection_list = self.query_one("#namespace-select", SelectionList)
        
        # Store current selection state
        was_all_selected = "all" in self._current_namespaces
        current_selections = self._current_namespaces.copy()
        current_order = self._namespace_selection_order.copy()
        
        # Set initializing flag to prevent selection events
        self._initializing = True
        
        try:
            # Clear existing options
            selection_list.clear_options()
            
            # Add "All Namespaces" option first
            selection_list.add_option(("All Namespaces", "all", "all" in current_selections))
            
            # Add namespace options
            for ns in sorted(namespaces, key=lambda x: x["metadata"]["name"]):
                name = ns["metadata"]["name"]
                selection_list.add_option((name, name, name in current_selections))
                
            # Restore selection state without triggering events
            self._current_namespaces = current_selections
            self._namespace_selection_order = current_order
            
            # Update button text
            main_content = self.query_one(MainContent)
            if not self._current_namespaces:
                main_content.update_namespace_button()  # Will show "Select Namespace"
            elif "all" in self._current_namespaces:
                main_content.update_namespace_button("all")
            elif self._namespace_selection_order:
                first_ns = self._namespace_selection_order[0]
                additional_count = len(self._current_namespaces) - 1
                main_content.update_namespace_button(first_ns, additional_count)
        finally:
            # Reset initializing flag
            self._initializing = False

    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Handle namespace added event."""
        if event.identifier.resource_type == "namespaces":
            all_namespaces, _ = await self.app._event_source.get_current_list(resource_type="namespaces")
            await self._update_namespace_select(all_namespaces)

    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Handle namespace modified event."""
        if event.identifier.resource_type == "namespaces":
            all_namespaces, _ = await self.app._event_source.get_current_list(resource_type="namespaces")
            await self._update_namespace_select(all_namespaces)

    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Handle namespace deleted event."""
        if event.identifier.resource_type == "namespaces":
            all_namespaces, _ = await self.app._event_source.get_current_list(resource_type="namespaces")
            await self._update_namespace_select(all_namespaces)
            
    async def on_resource_full_refresh(self, event: ResourceFullRefreshSignal) -> None:
        """Handle namespace full refresh event."""
        if event.identifier.resource_type == "namespaces":
            all_namespaces, _ = await self.app._event_source.get_current_list(resource_type="namespaces")
            await self._update_namespace_select(all_namespaces)

    async def _populate_resource_tree(self) -> None:
        """Populate the resource tree with contexts and their resources."""
        tree = self.query_one("#resource-tree", Tree)
        tree.clear()

        # Get available contexts
        contexts = await self.app.kubernetes_client.get_available_contexts()
        current_context = await self.app.kubernetes_client.get_current_context()

        # Add contexts to tree
        for ctx in contexts:
            context_node = tree.root.add(ctx, {"type": "context", "name": ctx})
            if ctx == current_context:
                context_node.expand()
                # Add resource categories under the current context
                workloads = context_node.add("Workloads", {"type": "category"})
                workloads.add("Pods", {"type": "resource", "resource_key": "pods"})
                workloads.add("Deployments", {"type": "resource", "resource_key": "deployments"})
                workloads.add("StatefulSets", {"type": "resource", "resource_key": "statefulsets"})
                workloads.add("DaemonSets", {"type": "resource", "resource_key": "daemonsets"})

                config = context_node.add("Config", {"type": "category"})
                config.add("Namespaces", {"type": "resource", "resource_key": "namespaces"})

                network = context_node.add("Network", {"type": "category"})
                network.add("Services", {"type": "resource", "resource_key": "services"})

                storage = context_node.add("Storage", {"type": "category"})
                storage.add("PersistentVolumeClaims", {"type": "resource", "resource_key": "pvcs"})
