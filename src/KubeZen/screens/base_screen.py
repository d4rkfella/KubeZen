from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast, Awaitable
import asyncio

# import textual

from textual.app import ComposeResult
from textual.events import Resize

from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input
from textual.widgets._data_table import CellDoesNotExist, DuplicateKey, RowDoesNotExist
from textual.containers import Container
from textual.binding import Binding
from textual import events

from ..core.resource_events import (
    ResourceEventListener,
    ResourceEventSource,
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
)
from ..utils.formatting import _get_datetime_from_metadata, format_age

log = logging.getLogger(__name__)




class BaseResourceScreen(Screen[None]):
    """A base screen for displaying a list of Kubernetes resources."""

    list_resource_version: str | None = None

    BINDINGS = [
        Binding("backspace", "handle_backspace", "Delete", show=False),
    ]

    def __init__(
        self, event_source: ResourceEventSource, namespace: str | None = None
    ) -> None:
        super().__init__()
        self._event_source = event_source
        self.active_namespace = namespace
        self.resource_emoji = "❓"
        self._layout_mode: str | None = None
        self._is_suspended = False
        self.search_query = ""

        # Age tracking
        self.age_timer: Timer | None = None
        self._items_to_update_secs: list[tuple[str, datetime]] = []
        self._items_to_update_mins: list[tuple[str, datetime]] = []

        # Event batching support
        self._pending_updates: set[str] = set()  # Track pending updates
        self._batch_update_timer: Timer | None = None
        self._batch_update_interval = 0.1  # 100ms

        self.RESOURCE_TYPE: str = ""
        self.COLUMNS: list[Any] = []

        self._current_sort_column_key: str = "Name"  # Initialize with default sort column
        self._current_sort_reverse_order: bool = False  # Initialize with ascending order
        self._column_key_to_index: dict[str, int] = {}  # New: stores column key to its index in row_data

        # Create a ResourceEventListener implementation for this screen
        self._event_listener = _ScreenResourceEventListener(self)

    @property
    async def items(self) -> list[dict[str, Any]]:
        """Get the current list of items from the store."""
        items, _ = await self._event_source.get_current_list(
            self.RESOURCE_TYPE, namespace=self.active_namespace
        )
        if self.search_query:
            search_lower = self.search_query.lower()
            return [
                item for item in items
                if search_lower in item.get("metadata", {}).get("name", "").lower()
            ]
        return items

    async def _schedule_batch_update(self) -> None:
        """Schedule a batch update if one isn't already pending"""
        if not self._batch_update_timer:
            self._batch_update_timer = self.set_timer(self._batch_update_interval, self._process_batch_updates)

    async def _process_batch_updates(self) -> None:
        """Process all pending updates at once"""
        if not self._pending_updates:
            return
        
        # Get fresh data for all pending updates
        table = self.query_one(DataTable)
        items = await self.items  # Get current state once
        
        for resource_key in self._pending_updates:
            resource = next(
                (item for item in items if item.get("metadata", {}).get("name") == resource_key),
                None
            )
            if resource:
                formatted_data = self._format_row(resource)
                try:
                    # Update the row
                    for i, col_key in enumerate(list(table.columns.keys())[1:]):
                        try:
                            current_value = table.get_cell(str(resource_key), col_key)
                            new_value = formatted_data[i]
                            if current_value != new_value:
                                table.update_cell(str(resource_key), col_key, new_value)
                        except CellDoesNotExist:
                            continue
                    self._add_item_to_age_tracker(resource)
                except Exception:
                    log.exception(f"Error updating row for key: {resource_key}")

        # Clear pending updates
        self._pending_updates.clear()
        self._batch_update_timer = None
        
        # Re-sort once after all updates
        table.sort(
            self._current_sort_column_key,
            reverse=self._current_sort_reverse_order,
            key=lambda cell_value: self._get_sortable_value_from_row(
                self._current_sort_column_key, cell_value
            ),
        )

    def on_key(self, event: events.Key) -> None:
        """Handle key events for direct typing into search."""
        # If it's a single character (not a special key) and not a control character
        if (
            len(event.key) == 1 
            and not event.key.startswith("ctrl+")
            and not event.key.startswith("shift+")
            and not event.key.startswith("alt+")
            and event.key.isprintable()
        ):
            search_input = self.query_one("#search", Input)
            search_input.value = search_input.value + event.key
            self.search_query = search_input.value
            self._filter_items(self.search_query)

    def action_handle_backspace(self) -> None:
        """Handle backspace key for search input."""
        search_input = self.query_one("#search", Input)
        if search_input.value:
            search_input.value = search_input.value[:-1]
            self.search_query = search_input.value
            self._filter_items(self.search_query)

    def compose(self) -> ComposeResult:
        """Create child widgets for the screen."""
        yield Header(show_clock=False)
        with Container(id="main"):
            input_widget = Input(
                placeholder="Search by name... (type anywhere)", 
                id="search"
            )
            input_widget.styles.width = "25%"
            input_widget.styles.margin = (0, 1, 0, 1)
            input_widget.styles.padding = (0, 1, 0, 1)
            input_widget.styles.pointer_events = "none"
            input_widget.can_focus = False
            yield input_widget
            yield DataTable(id="table")
        yield Footer()

    async def _filter_items(self, search_query: str) -> None:
        """Filter items based on the search query, looking only at the name column."""
        self.search_query = search_query
        await self._populate_table_async(self.items)

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Handle changes to the search input."""
        if event.input.id == "search":
            self.search_query = event.value
            await self._filter_items(self.search_query)

    async def on_mount(self) -> None:
        """Event handler for when the screen is mounted."""
        table = self.query_one(DataTable)
        table.cursor_type = "row"

        # Set up initial columns before populating data.
        table.add_column(" ", key="emoji", width=3)
        for col_data in self.COLUMNS:
            table.add_column(
                label=col_data.get("label"),
                width=col_data.get("width"),
                key=col_data.get("key", col_data.get("label")),
            )

        # Populate _column_key_to_index after columns are added
        for i, (key, _) in enumerate(table.columns.items()):
            self._column_key_to_index[cast(str, key.value)] = i

        # Subscribe to events and get initial list
        await self._event_source.subscribe(self.RESOURCE_TYPE, self._event_listener)
        items_future = self.items  # Get future for items
        self.list_resource_version = (await self._event_source.get_current_list(
            self.RESOURCE_TYPE, namespace=self.active_namespace
        ))[1]
        await self._populate_table_async(items_future)
        
        # Default sort by Name after initial population
        table.sort(
            self._current_sort_column_key,
            reverse=self._current_sort_reverse_order,
            key=lambda cell_value: self._get_sortable_value_from_row(
                self._current_sort_column_key, cell_value
            ),
        )

        # Set up age update timer that creates a task for the async update
        self.age_timer = self.set_interval(1.0, self._schedule_age_update)
        table.focus()

    def _schedule_age_update(self) -> None:
        """Schedule an async age update."""
        # Create task for the async update
        try:
            asyncio.create_task(self._update_ages())
        except Exception:
            log.exception("Error scheduling age update")

    async def on_unmount(self) -> None:
        """Called when the screen is unmounted."""
        log.debug("%s age_timer paused.", self.__class__.__name__)
        self._is_suspended = True
        if self.age_timer:
            self.age_timer.pause()

        # Unsubscribe from resource events
        if self._event_source and self._event_listener:
            await self._event_source.unsubscribe(self.RESOURCE_TYPE, self._event_listener)

    def on_screen_suspend(self) -> None:
        self._is_suspended = True
        if self.age_timer:
            self.age_timer.pause()
        log.debug("%s age_timer paused.", self.__class__.__name__)

    def on_screen_resume(self) -> None:
        self._is_suspended = False
        if self.age_timer:
            self.age_timer.resume()
        log.debug("%s age_timer resumed.", self.__class__.__name__)

    async def on_resize(self, event: Resize) -> None:
        """Handle resize events."""
        PROPORTIONAL_LAYOUT_MIN_WIDTH = 80
        new_mode = (
            "proportional"
            if event.size.width > PROPORTIONAL_LAYOUT_MIN_WIDTH
            else "auto"
        )

        if new_mode == "auto" and self._layout_mode == "auto":
            return

        self._layout_mode = new_mode
        table = self.query_one(DataTable)

        for key in list(table.columns.keys()):
            table.remove_column(key)

        table.add_column(" ", key="emoji", width=3)

        if new_mode == "proportional":
            EMOJI_WIDTH = 3
            CELL_PADDING = 2
            total_min_width = sum(col.get("min_width", 5) for col in self.COLUMNS)
            available_width = event.size.width - EMOJI_WIDTH
            leftover_space = available_width - total_min_width
            total_ratio = sum(col.get("ratio", 1) for col in self.COLUMNS) or 1

            for col_data in self.COLUMNS:
                min_width = col_data.get("min_width", 5)
                ratio = col_data.get("ratio", 1)
                share = (
                    (leftover_space * ratio) // total_ratio if leftover_space > 0 else 0
                )
                final_width = min_width + share
                table.add_column(
                    label=col_data.get("label"),
                    width=max(0, final_width - CELL_PADDING),
                    key=col_data.get("key", col_data.get("label")),
                )
        else:
            for col_data in self.COLUMNS:
                table.add_column(
                    label=col_data.get("label"),
                    width=col_data.get("width"),
                    key=col_data.get("key", col_data.get("label")),
                )

        # Rebuild _column_key_to_index after columns are re-added
        self._column_key_to_index.clear()  # Clear existing mapping
        for i, (key, _) in enumerate(table.columns.items()):
            self._column_key_to_index[cast(str, key.value)] = i

        await self._populate_table_async(self.items)
        # Re-sort after resize, keeping current sort order
        table.sort(
            self._current_sort_column_key,
            reverse=self._current_sort_reverse_order,
            key=lambda cell_value: self._get_sortable_value_from_row(
                self._current_sort_column_key, cell_value
            ),
        )

    async def on_data_table_header_selected(
        self, message: DataTable.HeaderSelected
    ) -> None:
        """Handle column header clicks for interactive sorting."""
        table = self.query_one(DataTable)

        # If the same column is clicked, toggle the sort order
        if message.column_key.value == self._current_sort_column_key:
            self._current_sort_reverse_order = not self._current_sort_reverse_order
        else:
            # If a new column is clicked, set it as the current sort column and reset to ascending
            self._current_sort_column_key = cast(str, message.column_key.value)
            self._current_sort_reverse_order = False

        table.sort(
            self._current_sort_column_key,
            reverse=self._current_sort_reverse_order,
            key=lambda cell_value: self._get_sortable_value_from_row(
                self._current_sort_column_key, cell_value
            ),
        )

    def _get_sortable_value_from_row(self, column_key: str, cell_value: Any) -> Any:
        """Extracts and converts the value from a row for sorting based on column_key."""
        if column_key == "Age":
            # Convert age string (e.g., "5m", "2h", "3d") to seconds for sorting
            if isinstance(cell_value, str):
                if cell_value == "-":  # No age/unknown
                    return -1  # Sort to the beginning

                match = re.match(r"(\d+)([smhd])", cell_value)
                if match:
                    value, unit = match.groups()
                    value = int(value)
                    if unit == "s":
                        return value
                    if unit == "m":
                        return value * 60
                    if unit == "h":
                        return value * 60 * 60
                    if unit == "d":
                        return value * 60 * 60 * 24
            return 0  # Default for unparseable age

        if column_key == "Status":
            # Assign a numeric priority for status strings
            status_priority = {
                "Running": 0,
                "Active": 0,
                "Completed": 1,
                "Succeeded": 1,
                "Pending": 2,
                "Terminating": 3,
                "Failed": 4,
                "Error": 5,
                "Unknown": 6,
                "CrashLoopBackOff": 7,
                "Evicted": 8,
            }
            return status_priority.get(cell_value, 99)

        # For other columns, return the value directly for natural sorting
        return cell_value

    def _add_item_to_age_tracker(self, item: dict[str, Any]) -> None:
        """Add an item to the age tracker."""
        row_key = item.get("metadata", {}).get("name")
        ts_str = item.get("metadata", {}).get("creationTimestamp")
        if not row_key or not ts_str:
            return

        try:
            creation_ts = _get_datetime_from_metadata(ts_str)
            if not creation_ts:
                return

            # Ensure creation_ts has timezone info
            if creation_ts.tzinfo is None:
                creation_ts = creation_ts.replace(tzinfo=timezone.utc)

            # Remove from both lists first to avoid duplicates
            self._remove_item_from_age_tracker(row_key)

            ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
            if creation_ts > ten_minutes_ago:
                self._items_to_update_secs.append((row_key, creation_ts))
            else:
                self._items_to_update_mins.append((row_key, creation_ts))
        except (ValueError, KeyError) as e:
            log.warning("Could not parse timestamp '%s': %s", ts_str, e)

    def _remove_item_from_age_tracker(self, row_key: str) -> None:
        self._items_to_update_secs = [
            item for item in self._items_to_update_secs if item[0] != row_key
        ]
        self._items_to_update_mins = [
            item for item in self._items_to_update_mins if item[0] != row_key
        ]

    async def _update_ages(self) -> None:
        """Update the age column for items that need it."""
        table = self.query_one(DataTable)
        if not table.is_mounted or "Age" not in table.columns:
            return

        now = datetime.now(timezone.utc)
        ten_minutes_ago = now - timedelta(minutes=10)

        still_updating_secs = []
        for row_key, creation_ts in self._items_to_update_secs:
            if creation_ts < ten_minutes_ago:
                self._items_to_update_mins.append((row_key, creation_ts))
            else:
                try:
                    age_delta = now - creation_ts
                    if age_delta.total_seconds() < 0:
                        age_str = "0s"
                    else:
                        age_str = format_age(creation_ts)
                    table.update_cell(row_key, "Age", age_str)
                    still_updating_secs.append((row_key, creation_ts))
                except CellDoesNotExist:
                    # This can happen if the row is deleted between the timer
                    # firing and this code running. It's safe to ignore.
                    pass
                except Exception as e:
                    log.exception("Error updating age for %s: %s", row_key, e)
        self._items_to_update_secs = still_updating_secs

        if now.second == 0:
            still_updating_mins = []
            for row_key, creation_ts in self._items_to_update_mins:
                try:
                    age_delta = now - creation_ts
                    if age_delta.total_seconds() < 0:
                        age_str = "0s"
                    else:
                        age_str = format_age(creation_ts)
                    table.update_cell(row_key, "Age", age_str)
                    still_updating_mins.append((row_key, creation_ts))
                except CellDoesNotExist:
                    # This can happen if the row is deleted between the timer
                    # firing and this code running. It's safe to ignore.
                    pass
                except Exception as e:
                    log.exception("Error updating age for %s: %s", row_key, e)
            self._items_to_update_mins = still_updating_mins

    def _format_row(self, item: dict[str, Any]) -> list[Any]:
        raise NotImplementedError("Subclasses must implement _format_row")

    def _get_static_rows(self) -> list[tuple[str, list[Any]]]:
        """Returns a list of static rows to be added to the table.
        
        Returns:
            A list of tuples, each containing a row key and a list of values.
            By default, returns an empty list.
        """
        return []

    async def _populate_table_async(self, items_future: Awaitable[list[dict[str, Any]]]) -> None:
        """Populate the table with the given items."""
        items = await items_future
        table = self.query_one(DataTable)
        table.clear()
        for item in items:
            name = item.get("metadata", {}).get("name", "")
            row_data = [self.resource_emoji] + self._format_row(item)
            table.add_row(*row_data, key=name)
            self._add_item_to_age_tracker(item)
        
        # Re-sort after populating, maintaining current sort order
        if self._current_sort_column_key:
            table.sort(
                self._current_sort_column_key,
                reverse=self._current_sort_reverse_order,
                key=lambda cell_value: self._get_sortable_value_from_row(
                    self._current_sort_column_key, cell_value
                ),
            )

    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Handle resource added signal."""
        if self._is_suspended or event.resource_type != self.RESOURCE_TYPE:
            return

        log.info(
            "HANDLER 'on_resource_added' TRIGGERED for: %s",
            event.resource_key
        )

        # Get the resource from the store
        items = await self.items
        resource = next(
            (item for item in items if item.get("metadata", {}).get("name") == event.resource_key),
            None
        )
        if not resource:
            log.warning("Resource %s not found in store after add signal", event.resource_key)
            return

        table = self.query_one(DataTable)
        formatted_data = self._format_row(resource)
        try:
            table.add_row(self.resource_emoji, *formatted_data, key=str(event.resource_key))
            self._add_item_to_age_tracker(resource)
            # Re-sort after adding a new item
            table.sort(
                self._current_sort_column_key,
                reverse=self._current_sort_reverse_order,
                key=lambda cell_value: self._get_sortable_value_from_row(
                    self._current_sort_column_key, cell_value
                ),
            )
        except DuplicateKey:
            log.warning(
                "Duplicate key %s for ADDED signal, treating as MODIFIED.",
                event.resource_key,
            )
            await self.on_resource_modified(ResourceModifiedSignal(
                resource_type=event.resource_type,
                resource_key=event.resource_key
            ))
        except Exception:
            log.exception("Error adding row for key: %s", event.resource_key)

    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Handle resource modified signal."""
        if self._is_suspended or event.resource_type != self.RESOURCE_TYPE:
            return

        log.info(
            "HANDLER 'on_resource_modified' TRIGGERED for: %s",
            event.resource_key
        )

        # Add to pending updates and schedule batch update
        self._pending_updates.add(event.resource_key)
        await self._schedule_batch_update()

    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Handle resource deleted signal."""
        if self._is_suspended or event.resource_type != self.RESOURCE_TYPE:
            return

        log.info(
            "HANDLER 'on_resource_deleted' TRIGGERED for: %s",
            event.resource_key
        )
        
        # Remove from pending updates if present
        self._pending_updates.discard(event.resource_key)
        
        table = self.query_one(DataTable)
        self._remove_item_from_age_tracker(event.resource_key)

        try:
            table.remove_row(str(event.resource_key))
        except RowDoesNotExist:
            log.warning("Delete signal for non-existent row %s.", event.resource_key)
        except Exception:
            log.exception("Error deleting row for key: %s", event.resource_key)

    async def on_resource_full_refresh(self, event: ResourceFullRefreshSignal) -> None:
        """Handle resource full refresh signal."""
        if self._is_suspended or event.resource_type != self.RESOURCE_TYPE:
            return

        # Skip if we've already seen this version
        if (
            self.list_resource_version is not None
            and self.list_resource_version == event.resource_version
        ):
            log.debug(
                "%s: Skipping full refresh, already at version %s (event: %s)",
                self.__class__.__name__,
                self.list_resource_version,
                event.resource_version,
            )
            return
        
        self.list_resource_version = event.resource_version
        await self._populate_table_async(self.items)

class _ScreenResourceEventListener(ResourceEventListener):
    """Private implementation of ResourceEventListener that delegates to a BaseResourceScreen."""

    def __init__(self, screen: BaseResourceScreen) -> None:
        self._screen = screen

    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Delegate resource added signal to screen."""
        await self._screen.on_resource_added(event)

    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Delegate resource modified signal to screen."""
        await self._screen.on_resource_modified(event)

    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Delegate resource deleted signal to screen."""
        await self._screen.on_resource_deleted(event)

    async def on_resource_full_refresh(self, event: ResourceFullRefreshSignal) -> None:
        """Delegate resource full refresh signal to screen."""
        await self._screen.on_resource_full_refresh(event)


