from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.events import Click
from textual.reactive import reactive
from textual.widgets import Input, Label, SelectionList, TabPane
from textual.widgets.selection_list import Selection
from textual.widget import Widget

from KubeZen.containers.resource_list import ResourceList

if TYPE_CHECKING:
    from KubeZen.models import UIRow


log = logging.getLogger(__name__)


class ResourceTabPane(TabPane):
    """A tab pane for displaying a list of resources."""

    DEFAULT_CSS = """
    ResourceTabPane Label {
        border: round $primary;
        width: 30;
        padding: 0 1;
        offset-x: 1;
        dock: top;

        &.-active {
            border: round $accent;
        }
    }

    ResourceTabPane SelectionList {
        width: 30;
        max-height: 15;
        padding: 0;
        dock: top;
        border: round $accent;
        layer: overlay;
        margin-left: 1;
        margin-top: 3;

        &.-hidden {
            display: none;
        }
    }

    ResourceTabPane Input {
        width: 30;
        border: round $primary;
        dock: top;

        &:focus {
            border: round $accent;
        }

        &.-namespaced {
            margin-left: 32;
        }

        &.-non-namespaced {
            margin-left: 1;
        }
    }
    """

    available_namespaces: reactive[set[str]] = reactive(set(), init=False)
    show_namespaces_list = reactive(False, init=False)
    _is_updating_selection: bool = False

    def __init__(
        self,
        title: str,
        model_class: type[UIRow],
        available_namespaces: set[str],
        id: str,
    ) -> None:
        super().__init__(
            title,
            id=id,
        )
        self.model_class = model_class
        self.available_namespaces = available_namespaces

    def compose(self) -> ComposeResult:
        """Compose the resource tab pane layout."""
        yield ResourceList(model_class=self.model_class)
        yield Input(
            placeholder=f"Search {self.model_class.display_name}...",
        )

        if self.model_class.namespaced:
            yield Label()
            selections = [Selection("All Namespaces", "all", True)] + [
                Selection(ns, ns, True) for ns in sorted(self.available_namespaces)
            ]
            yield SelectionList[str](*selections, classes="namespace-select -hidden")

    def on_mount(self) -> None:
        """Configure widgets after they have been mounted."""
        resource_list = self.query_one(ResourceList)
        search_bar = self.query_one(Input)

        if self.model_class.namespaced:
            resource_list.selected_namespaces = {"all"} | self.available_namespaces
            search_bar.add_class("-namespaced")
            self.update_namespace_label(["all"])
        else:
            resource_list.selected_namespaces = {"all"}
            search_bar.add_class("-non-namespaced")

    @on(Click)
    def on_click(self, event: Click) -> None:
        search_bar = self.query_one(Input)
        namespace_select: SelectionList | None = None
        namespace_button: Label | None = None

        if self.model_class.namespaced:
            try:
                namespace_select = self.query_one(SelectionList)
                namespace_button = self.query_one(Label)
            except NoMatches:
                pass  # Should not happen, but good practice

        target_node, _ = self.screen.get_widget_at(*event.screen_offset)

        current_widget: Widget | None = cast(Widget, target_node)
        clicked_on_interactive_widget = False

        while current_widget is not None:
            if (
                current_widget is search_bar
                or current_widget is namespace_select
                or current_widget is namespace_button
            ):
                clicked_on_interactive_widget = True
                break

            parent = current_widget.parent
            if not isinstance(parent, Widget):
                break
            current_widget = parent

        if not clicked_on_interactive_widget:
            if self.app.focused is search_bar:
                self.screen.set_focus(None)
            if self.model_class.namespaced and self.show_namespaces_list:
                self.show_namespaces_list = False

    @on(Click, "Label")
    def on_namespace_button_click(self, event: Click) -> None:
        self.show_namespaces_list = not self.show_namespaces_list

    def watch_show_namespaces_list(self, show_namespaces_list: bool) -> None:
        self.query_one(Label).set_class(show_namespaces_list, "-active")
        self.query_one(SelectionList).set_class(not show_namespaces_list, "-hidden")

    @staticmethod
    def _update_namespace_selection_state(
        resource_list: ResourceList,
        namespace_select: SelectionList,
        current_selection: set[str],
        previous_selection: set[str],
    ) -> None:
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
        first_selected = getattr(resource_list, "first_selected_namespace", None)
        if first_selected and first_selected in final_selection:
            return [first_selected] + sorted(
                [item for item in final_selection if item != first_selected]
            )
        return sorted(final_selection)

    @on(SelectionList.SelectedChanged)
    def on_namespace_selection_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if self._is_updating_selection:
            return

        try:
            self._is_updating_selection = True
            namespace_select = event.selection_list

            resource_list = self.query_one(ResourceList)

            previous_selection = set(resource_list.selected_namespaces)
            current_selection = set(namespace_select.selected)

            self._update_namespace_selection_state(
                resource_list, namespace_select, current_selection, previous_selection
            )

            final_selection = namespace_select.selected
            resource_list.selected_namespaces = set(final_selection)
            selected_for_display = self._prepare_display_label(
                resource_list, final_selection
            )
            self.update_namespace_label(selected_for_display)
        finally:
            self._is_updating_selection = False

    def watch_available_namespaces(self, available_namespaces: set[str]) -> None:
        if not self.model_class.namespaced:
            return
        try:
            namespace_select = self.query_one(SelectionList)
            resource_list = self.query_one(ResourceList)

            namespace_select.clear_options()
            namespace_select.add_options(
                [Selection("All Namespaces", "all")]
                + [Selection(name, name) for name in sorted(available_namespaces)]
            )
            current_selection = cast(set[str], resource_list.selected_namespaces)

            if "all" in current_selection:
                resource_list.selected_namespaces = {"all"} | available_namespaces
                namespace_select.select_all()
            else:
                resource_list.selected_namespaces = {
                    ns for ns in current_selection if ns in available_namespaces
                }
                for ns in resource_list.selected_namespaces:
                    namespace_select.select(ns)
        except NoMatches:
            log.debug("No matches exception")
            pass

    def update_namespace_label(self, selected_for_display: list[str]) -> None:
        if not selected_for_display:
            text = "Select Namespace"
        elif "all" in selected_for_display:
            text = "All Namespaces"
        elif len(selected_for_display) == 1:
            text = selected_for_display[0]
        else:
            text = f"{selected_for_display[0]} +{len(selected_for_display) - 1}"

        namespace_button = self.query_one(Label)
        button_width = 25
        padding = max(1, button_width - len(text) - 1)
        padded_text = f"{text}{' ' * padding}▼"
        namespace_button.update(padded_text)

    @on(Input.Changed)
    def on_search_input_changed(self, event: Input.Changed) -> None:
        resource_list = self.query_one(ResourceList)
        resource_list.search_input = event.input.value.replace(" ", "").lower()

    def __del__(self) -> None:
        """Log when the resource tab pane is destroyed."""
        log.debug("ResourceTabPane for destroyed")
