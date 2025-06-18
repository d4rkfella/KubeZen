import logging
from typing import Any, ClassVar, Optional, cast

from textual import events
from textual.widgets import DataTable, Input, Static
from textual.widget import Widget
from textual.message import Message
from textual.app import ComposeResult
from textual.widgets._data_table import CellDoesNotExist, DuplicateKey, RowDoesNotExist
from textual.css.query import NoMatches
from enum import Enum, auto
from datetime import datetime, timezone
from textual.timer import Timer
from dataclasses import dataclass
from collections import deque
import asyncio
import time
import math
import re


from ..core.resource_events import ResourceEventSource
from ..core.resource_registry import RESOURCE_REGISTRY
from .action_screen import ActionScreen
from ..utils.formatting import _get_datetime_from_metadata, format_age
from ..utils.logging import log_batch_timing

from ..core.resource_events import (
    ResourceEventSource,
    ResourceAddedSignal,
    ResourceModifiedSignal,
    ResourceDeletedSignal,
    ResourceFullRefreshSignal,
    ResourceSignal,
)

log = logging.getLogger(__name__)


class EventType(Enum):
    """Type of resource event."""

    ADDED = auto()
    MODIFIED = auto()
    DELETED = auto()


@dataclass
class BatchedEvent:
    """Represents a batched resource event."""

    event_type: EventType
    resource_key: str
    resource: dict[str, Any] | None = None


# Add a class variable to track the last batch update time
_last_batch_time = 0.0

class RowSelected(Message):
    def __init__(self, row_key: str, cursor_row: int) -> None:
        super().__init__()
        self.row_key = row_key
        self.cursor_row = cursor_row


class ResourceListWidget(Widget):
    """A widget to display a list of Kubernetes resources."""

    DEFAULT_CSS = """
    ResourceListWidget {
        height: 100%;
        width: 100%;
        border: none;
    }
    DataTable {
        height: 100%;
        width: 100%;
        border: none;
    }

    DataTable > .datatable--header {
        color: $text;
        text-style: bold;
        height: 3;
    }
    """
    
    BATCH_WINDOW_SECONDS: ClassVar[float] = 0.1
    
    BINDINGS = [
        ("backspace", "handle_backspace", "Delete last character")
    ]
    
    def __init__(
        self,
        resource_key: str,
        namespace: str | list[str] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._event_source = self.app._event_source
        self.resource_key = resource_key
        # Convert single namespace to list for consistency
        self.active_namespaces = [namespace] if isinstance(namespace, str) else namespace
        self._is_suspended = False
        self.resource_meta = RESOURCE_REGISTRY[resource_key]
        self._table: DataTable | None = None

        log.debug(
            "Initializing ResourceListWidget for %s in namespaces %s",
            resource_key,
            self.active_namespaces
        )

        self.age_timer: Timer | None = None
        self._age_update_lock = asyncio.Lock()  # Lock for age updates

        # Event batching
        self._age_tracker: dict[str, datetime] = {}
        self._pending_events: deque[BatchedEvent] = deque()
        self._batch_timer: Optional[asyncio.TimerHandle] = None
        self._batch_lock = asyncio.Lock()
        self._current_sort_column_key: str | None = None
        self._current_sort_reverse_order = False

        # Column tracking
        self._column_key_to_index: dict[str, int] = {}

        # Age tracking with optimized update intervals
        self._items_to_update_secs: list[tuple[str, datetime]] = []  # < 2 minutes, update every second
        self._items_to_update_min_sec: list[tuple[str, datetime]] = []  # 2-10 minutes, update every second
        self._items_to_update_mins: list[tuple[str, datetime]] = []  # 10-60 minutes, update every minute
        self._items_to_update_hour_min: list[tuple[str, datetime]] = []  # 1-10 hours, update every minute
        self._items_to_update_hours: list[tuple[str, datetime]] = []  # 10-24 hours, update every hour
        self._items_to_update_day_hour: list[tuple[str, datetime]] = []  # 1-10 days, update every hour
        self._items_to_update_days: list[tuple[str, datetime]] = []  # >10 days, update every day

        # Track last update times for each bucket type
        self._last_update_times = {
            "seconds": 0.0,  # Update every second
            "minutes:seconds": 0.0,  # Update every second
            "minutes": 0.0,  # Update every minute
            "hours:minutes": 0.0,  # Update every minute
            "hours": 0.0,  # Update every hour
            "days:hours": 0.0,  # Update every hour
            "days": 0.0,  # Update every day
        }
    
    def compose(self) -> ComposeResult:
        """Create child widgets."""
        log.info("Creating DataTable with selection enabled")
        table = DataTable(show_cursor=True, show_header=True)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.can_focus = True
        log.info("DataTable configuration: cursor_type=%s, can_focus=%s", table.cursor_type, table.can_focus)
        yield table

    async def on_mount(self) -> None:
        """Set up the widget when mounted."""
        self._table = self.query_one(DataTable)
        
        log.debug("Setting up columns")
        with log_batch_timing(self.app):
            # Only set up columns if they don't exist yet
            if not self._table.columns:
                log.debug("Table has no columns, setting them up")
                # Set up initial columns before populating data.
                self._table.add_column(" ", key="emoji", width=3)
                
                # Add Name column first
                name_col = next(col for col in self.resource_meta["columns"] if col["key"] == "Name")
                self._table.add_column(
                    label=name_col.get("label"),
                    width=name_col.get("width"),
                    key=name_col.get("key", name_col.get("label")),
                )
                
                # Add Namespace column if resource is namespaced
                if self.resource_meta["is_namespaced"]:
                    self._table.add_column(
                        label="Namespace",
                        width=15,
                        key="Namespace",
                    )
                
                # Add remaining columns
                for col_data in self.resource_meta["columns"]:
                    if col_data["key"] != "Name":  # Skip Name as we already added it
                        log.debug("Adding column: %s", col_data)
                        self._table.add_column(
                            label=col_data.get("label"),
                            width=col_data.get("width"),
                            key=col_data.get("key", col_data.get("label")),
                        )

                # Populate _column_key_to_index after columns are added
                for i, (key, _) in enumerate(self._table.columns.items()):
                    self._column_key_to_index[cast(str, key.value)] = i
                log.debug(
                    "Column setup complete. Column indices: %s",
                    self._column_key_to_index,
                )
            else:
                log.debug("Table already has columns, skipping column setup")

        log.debug("Subscribing to events and getting initial items")
        try:
            all_items = []
            latest_resource_version = None

            # If no namespaces specified or active_namespaces is None, get all namespaces
            if not self.active_namespaces:
                items, resource_version = await self._event_source.subscribe_and_get_list(
                    resource_type=self.resource_key,
                    listener=self,
                    namespace=None,
                )
                all_items.extend(items)
                latest_resource_version = resource_version
            else:
                # Get items for each namespace
                for namespace in self.active_namespaces:
                    items, resource_version = await self._event_source.subscribe_and_get_list(
                        resource_type=self.resource_key,
                        listener=self,
                        namespace=namespace,
                    )
                    all_items.extend(items)
                    # Keep track of the latest resource version
                    if latest_resource_version is None or resource_version > latest_resource_version:
                        latest_resource_version = resource_version

            self.list_resource_version = latest_resource_version
            log.debug(
                "Got %d items with resource version %s",
                len(all_items),
                self.list_resource_version,
            )
        except Exception as e:
            log.exception("Failed to subscribe and get initial items: %s", e)
            raise

        # Populate and sort table in a single batch
        with log_batch_timing(self.app):
            log.debug("Starting table population")
            await self._populate_table(all_items)

            # Default sort by Name after initial population
            log.debug("Setting default sort")
            self._current_sort_column_key = "Name"
            self._table.sort(
                "Name",
                reverse=self._current_sort_reverse_order,
                key=lambda cell_value: self._get_sortable_value_from_row(
                    "Name", cell_value
                ),
            )

        log.debug("Setting up age timer")
        self.age_timer = self.set_interval(1.0, self._schedule_age_update)
        self._table.focus()
        log.debug("ResourceListWidget on_mount completed")
    
    def on_unmount(self) -> None:
        log.debug("Unmounting ResourceListWidget")
        # Unsubscribe from each namespace
        if self.active_namespaces:
            for namespace in self.active_namespaces:
                self.app.run_worker(self._event_source.unsubscribe(
                    resource_type=self.resource_key,
                    namespace=namespace,
                    listener=self
                ))
        else:
            # Unsubscribe from all namespaces
            self.app.run_worker(self._event_source.unsubscribe(
                resource_type=self.resource_key,
                namespace=None,
                listener=self
            ))
        if self.age_timer:
            self.age_timer.stop()
    
    def on_screen_suspend(self) -> None:
        log.debug("Suspending ResourceListWidget")
        self._is_suspended = True
        if self.age_timer:
            self.age_timer.pause()
        log.debug("%s age_timer paused.", self.__class__.__name__)
        
    
    def on_screen_resume(self) -> None:
        log.debug("Resuming ResourceListWidget")
        self._is_suspended = False
        if self.age_timer:
            self.age_timer.resume()
        log.debug("%s age_timer resumed.", self.__class__.__name__)
    
    async def _populate_table(self, items: list[dict[str, Any]]) -> None:
        """Populate the table with items."""
        log.debug("Starting table population with %d items", len(items))
        table = self.query_one(DataTable)

        # Use a single batch update for all table operations
        with log_batch_timing(self.app, log_changes=True):
            # Clear existing rows
            table.clear()

            # Add all rows in a single batch
            rows_to_add = []
            for item in items:
                row_data = [self.resource_meta.get("emoji", "❓")] + self._format_row(item)
                name = item.get("metadata", {}).get("name", "")
                namespace = item.get("metadata", {}).get("namespace", "")
                if name:
                    log.debug("Processing row for resource: %s in namespace %s", name, namespace)
                    # Store both name and namespace in the row key, separated by a delimiter
                    row_key = f"{namespace}:{name}" if namespace else name
                    rows_to_add.append((row_key, row_data))
                    self._add_item_to_age_tracker(item)

            if rows_to_add:
                log.debug("Preparing to add %d rows to table", len(rows_to_add))
                # Sort the data before adding if needed
                if self._current_sort_column_key is not None:
                    log.debug("Sorting by column: %s", self._current_sort_column_key)
                    # Extract the column index for the sort key
                    sort_col_idx = self._column_key_to_index.get(
                        self._current_sort_column_key, 0
                    )
                    # Sort the rows data based on the sort key
                    rows_to_add.sort(
                        key=lambda x: self._get_sortable_value_from_row(
                            self._current_sort_column_key, x[1][sort_col_idx]
                        ),
                        reverse=self._current_sort_reverse_order,
                    )

                # Add all rows at once
                for key, row_data in rows_to_add:
                    table.add_row(*row_data, key=key)

                log.debug("Added %d rows to table", len(rows_to_add))

        log.debug("Table population completed")
    
    def _get_sortable_value_from_row(
        self, column_key: str | None, cell_value: Any
    ) -> Any:
        """Extracts and converts the value from a row for sorting based on column_key."""
        if column_key is None:
            return cell_value

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
    
    def _format_row(self, item: dict[str, Any]) -> list[Any]:
        """Format a resource item into a list of values for a table row."""
        formatter = self.resource_meta["formatter"]
        row_data = formatter(item)
        
        # Insert namespace after name if resource is namespaced
        if self.resource_meta["is_namespaced"]:
            namespace = item.get("metadata", {}).get("namespace", "")
            row_data.insert(1, namespace)  # Insert after name (index 0)
            
        return row_data

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """When a resource is selected, show the available actions for it."""
        log.info("Row selected event received: %s", event)
        
        if event.row_key.value is None:
            log.warning("Row key value is None, ignoring selection")
            return
        
        # Extract namespace and name from the row key
        row_key = event.row_key.value
        if ":" in row_key:
            namespace, resource_name = row_key.split(":", 1)
        else:
            namespace = None
            resource_name = row_key
            
        log.info("Getting resource '%s' from namespace '%s'", resource_name, namespace or "None")
        
        selected_item = await self._event_source.get_one(
            self.resource_key,
            namespace,
            resource_name
        )
        
        if selected_item is None:
            log.warning("Could not find resource '%s' in namespace '%s'", resource_name, namespace or "None")
            return

        self.app.push_screen(
            ActionScreen(
                resource_key=self.resource_key,
                namespace=namespace,
                resource_name=resource_name,
                resource_emoji=str(self.resource_meta.get("emoji", "❓")),
            )
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
            cast(str, self._current_sort_column_key),
            reverse=self._current_sort_reverse_order,
            key=lambda cell_value: self._get_sortable_value_from_row(
                cast(str, self._current_sort_column_key), cell_value
            ),
        )
    
    @property
    async def items(self) -> list[dict[str, Any]]:
        """Get the current list of items from the store."""
        result = await self._event_source.get_current_list(
            self.resource_key, namespace=self.active_namespaces
        )
        items = result[0]  # Extract items from tuple
        if self.search_query:
            search_lower = self.search_query.lower()
            filtered_items = [
                item
                for item in items
                if search_lower in item.get("metadata", {}).get("name", "").lower()
            ]
            return filtered_items
        return items

    async def _filter_items(self, search_query: str) -> None:
        """Filter items based on the search query, looking only at the name column."""
        self.search_query = search_query
        result = await self._event_source.get_current_list(
            self.resource_key, self.active_namespaces
        )
        items = result[0] if result else []  # Extract items from tuple, default to empty list
        if search_query:
            search_lower = search_query.lower()
            filtered_items = [
                item
                for item in items
                if item and search_lower in item.get("metadata", {}).get("name", "").lower()
            ]
            if filtered_items:  # Only update table if we have items
                await self._populate_table(filtered_items)
        else:
            if items:  # Only update table if we have items
                await self._populate_table(items)

    def _schedule_age_update(self) -> None:
        """Schedule an async age update."""
        try:
            # Get current time as integer seconds
            now = int(time.time())
            items_to_update = []

            # Get last update times as integers
            last_seconds_update = int(self._last_update_times.get("seconds", 0))
            last_minutes_update = int(self._last_update_times.get("minutes", 0))
            last_hours_update = int(self._last_update_times.get("hours", 0))
            last_days_update = int(self._last_update_times.get("days", 0))

            # Check seconds buckets (every second)
            if now > last_seconds_update:
                items_to_update.extend(self._items_to_update_secs)
                items_to_update.extend(self._items_to_update_min_sec)
                self._last_update_times["seconds"] = now

            # Check minutes buckets (every minute)
            if now - last_minutes_update >= 60:
                items_to_update.extend(self._items_to_update_mins)
                items_to_update.extend(self._items_to_update_hour_min)
                self._last_update_times["minutes"] = now

            # Check hours buckets (every hour)
            if now - last_hours_update >= 3600:
                items_to_update.extend(self._items_to_update_hours)
                items_to_update.extend(self._items_to_update_day_hour)
                self._last_update_times["hours"] = now

            # Check days bucket (every day)
            if now - last_days_update >= 86400:
                items_to_update.extend(self._items_to_update_days)
                self._last_update_times["days"] = now

            if items_to_update:
                # Create task for immediate update
                asyncio.create_task(self._update_ages(items_to_update))

            # Schedule next update precisely on the next second boundary
            loop = asyncio.get_running_loop()
            next_second = math.ceil(time.time())
            delay = next_second - time.time()
            if delay > 0:  # Only schedule if we haven't passed the next second
                loop.call_later(delay, self._schedule_age_update)

        except Exception:
            log.exception("Error scheduling age update")
    
    def _add_item_to_age_tracker(self, item: dict[str, Any]) -> None:
        """Add an item to the age tracker with optimized update intervals."""
        metadata = item.get("metadata", {})
        name = metadata.get("name")
        namespace = metadata.get("namespace")
        if not name:
            return

        # Use the same key format as the table
        row_key = f"{namespace}:{name}" if namespace else name
        ts_str = metadata.get("creationTimestamp")
        if not ts_str:
            return

        try:
            creation_ts = _get_datetime_from_metadata(ts_str)
            if not creation_ts:
                return

            # Ensure creation_ts has timezone info
            if creation_ts.tzinfo is None:
                creation_ts = creation_ts.replace(tzinfo=timezone.utc)

            # Check if item exists in any bucket with the same timestamp
            for bucket in [
                self._items_to_update_secs,
                self._items_to_update_min_sec,
                self._items_to_update_mins,
                self._items_to_update_hour_min,
                self._items_to_update_hours,
                self._items_to_update_day_hour,
                self._items_to_update_days,
            ]:
                for existing_key, existing_ts in bucket:
                    if existing_key == row_key:
                        # If timestamp hasn't changed, no need to re-add
                        if existing_ts == creation_ts:
                            return
                        # If timestamp changed, we need to update
                        break

            now = datetime.now(timezone.utc)
            age_delta = now - creation_ts
            minutes = age_delta.total_seconds() / 60
            hours = minutes / 60
            days = hours / 24

            # Function to determine which bucket an item belongs in
            def get_target_bucket() -> tuple[list[tuple[str, datetime]], str, str]:
                if minutes < 2:
                    return (
                        self._items_to_update_secs,
                        "seconds",
                        f"{int(age_delta.total_seconds())}s",
                    )
                elif minutes < 10:
                    return (
                        self._items_to_update_min_sec,
                        "minutes:seconds",
                        f"{int(minutes)}m{int(age_delta.total_seconds() % 60)}s",
                    )
                elif minutes < 60:
                    return (self._items_to_update_mins, "minutes", f"{int(minutes)}m")
                elif hours < 10:
                    return (
                        self._items_to_update_hour_min,
                        "hours:minutes",
                        f"{int(hours)}h{int(minutes % 60)}m",
                    )
                elif hours < 24:
                    return (self._items_to_update_hours, "hours", f"{int(hours)}h")
                elif days < 10:
                    return (
                        self._items_to_update_day_hour,
                        "days:hours",
                        f"{int(days)}d{int(hours % 24)}h",
                    )
                else:
                    return (self._items_to_update_days, "days", f"{int(days)}d")

            # Get the target bucket and format info
            target_bucket, bucket_name, age_str = get_target_bucket()

            # Remove from all buckets to avoid duplicates
            was_tracked = self._remove_item_from_age_tracker(row_key)

            # Only log if item is new or was in a different bucket
            if not was_tracked:
                log.debug(
                    "Initially placing %s in %s bucket (age: %s)",
                    row_key,
                    bucket_name,
                    age_str,
                )

            # Add to the appropriate bucket
            target_bucket.append((row_key, creation_ts))

        except (ValueError, KeyError) as e:
            log.warning("Could not parse timestamp '%s': %s", ts_str, e)

    def _remove_item_from_age_tracker(self, row_key: str) -> bool:
        """Remove an item from all age tracking lists.

        Returns:
            bool: True if the item was found and removed from any list, False otherwise.
        """
        was_tracked = False
        # Remove from all lists to avoid duplicates
        for bucket in [
            self._items_to_update_secs,
            self._items_to_update_min_sec,
            self._items_to_update_mins,
            self._items_to_update_hour_min,
            self._items_to_update_hours,
            self._items_to_update_day_hour,
            self._items_to_update_days,
        ]:
            # Use a list comprehension to remove items with matching row_key
            original_len = len(bucket)
            bucket[:] = [x for x in bucket if x[0] != row_key]
            if len(bucket) != original_len:
                was_tracked = True
        return was_tracked

    async def _update_ages(self, items_to_update: list[tuple[str, datetime]]) -> None:
        """Update the ages of the specified items."""
        if not items_to_update or self._is_suspended:
            return

        try:
            table = self.query_one(DataTable)
            age_col_idx = self._column_key_to_index.get("Age")
            if age_col_idx is None:
                return

            with log_batch_timing(self.app, log_changes=False):
                for resource_key, creation_time in items_to_update:
                    try:
                        age_str = format_age(creation_time)
                        if "Age" in self._column_key_to_index:
                            table.update_cell(resource_key, "Age", age_str)
                    except (CellDoesNotExist, RowDoesNotExist):
                        self._remove_item_from_age_tracker(resource_key)
        except NoMatches:
            return
    
    async def _process_resource_events(
        self, events: list[tuple[str, str, dict[str, Any] | None]]
    ) -> None:
        """Process multiple resource events in a single batch."""
        if not events:
            log.debug("No pending events to process")
            return

        log.debug("Processing %d resource events", len(events))
        try:
            table = self.query_one(DataTable)
            log.debug("Got DataTable reference")
        except Exception as e:
            log.error("Failed to get DataTable: %s", str(e), exc_info=True)
            return

        needs_sort = False

        with log_batch_timing(self.app):
            delete_events = [(k, t, r) for k, t, r in events if t == "deleted"]
            if delete_events:
                log.debug("Processing %d delete events", len(delete_events))
                
            for resource_key, event_type, resource in delete_events:
                try:
                    log.debug("Processing DELETE event for key '%s'", resource_key)
                    
                    # Log current table state
                    log.debug("Current table keys before delete: %s", list(table.rows.keys()))
                    
                    # Verify the key exists in the expected format
                    if str(resource_key) not in table.rows:
                        log.warning(
                            "Key '%s' not found in table for deletion. Similar keys: %s",
                            resource_key,
                            [k for k in table.rows.keys() if resource_key in str(k)]
                        )
                        continue
                        
                    # Remove from age tracker first
                    log.debug("Removing '%s' from age tracker", resource_key)
                    self._remove_item_from_age_tracker(str(resource_key))
                    
                    # Then remove from table
                    log.debug("Removing row '%s' from table", resource_key)
                    table.remove_row(str(resource_key))
                    
                    log.debug("Successfully processed DELETE event for '%s'", resource_key)
                except RowDoesNotExist:
                    log.warning(
                        "Delete signal for non-existent row '%s'. Available rows: %s",
                        resource_key,
                        list(table.rows.keys())
                    )
                except Exception as e:
                    log.error(
                        "Error processing delete for '%s': %s",
                        resource_key,
                        str(e),
                        exc_info=True
                    )

            # Then process adds and modifications
            for resource_key, event_type, resource in events:
                if event_type != "deleted" and resource is not None:
                    log.debug(
                        "Processing %s event for %s", event_type.upper(), resource_key
                    )
                    try:
                        # Get namespace and name from the resource
                        metadata = resource.get("metadata", {})
                        name = metadata.get("name")
                        namespace = metadata.get("namespace")
                        # Use consistent key format
                        row_key = f"{namespace}:{name}" if namespace else name
                        
                        row_data = [self.resource_meta.get("emoji", "❓")] + self._format_row(resource)
                        log.debug(
                            "Formatted row data for %s: %s", row_key, row_data
                        )
                    except Exception as e:
                        log.error(
                            "Failed to format row for %s: %s",
                            resource_key,
                            str(e),
                            exc_info=True,
                        )
                        continue

                    try:
                        if event_type == "added":
                            log.debug("Adding row for %s", row_key)
                            table.add_row(*row_data, key=str(row_key))
                            self._add_item_to_age_tracker(resource)
                            needs_sort = True
                        else:  # modified
                            log.debug("Updating row for %s", row_key)
                            # For modified events, try to update if the row exists, otherwise add it
                            try:
                                # Get column keys directly from the table's columns dictionary
                                column_keys = [
                                    key.value
                                    for key in table.columns.keys()
                                    if key.value is not None
                                ]
                                log.debug("Column keys: %s", column_keys)
                                for col_idx, cell_value in enumerate(row_data):
                                    if col_idx < len(column_keys):
                                        log.debug(
                                            "Updating cell %s[%s] = %s",
                                            row_key,
                                            column_keys[col_idx],
                                            cell_value,
                                        )
                                        table.update_cell(
                                            str(row_key),
                                            str(column_keys[col_idx]),
                                            cell_value,
                                        )
                                self._add_item_to_age_tracker(resource)
                            except (CellDoesNotExist, RowDoesNotExist):
                                # If row doesn't exist, treat as an add
                                log.debug(
                                    "Row %s doesn't exist for MODIFIED event, adding it",
                                    row_key,
                                )
                                table.add_row(*row_data, key=str(row_key))
                                self._add_item_to_age_tracker(resource)
                                needs_sort = True
                    except DuplicateKey:
                        log.warning(
                            "Duplicate key %s for %s signal, treating as MODIFIED.",
                            row_key,
                            event_type.upper(),
                        )
                        # Update the row instead
                        column_keys = [
                            key.value
                            for key in table.columns.keys()
                            if key.value is not None
                        ]
                        for col_idx, cell_value in enumerate(row_data):
                            if col_idx < len(column_keys):
                                table.update_cell(
                                    str(row_key),
                                    str(column_keys[col_idx]),
                                    cell_value,
                                )
                        self._add_item_to_age_tracker(resource)
                    except Exception as e:
                        log.error(
                            "Failed to process %s event for %s: %s",
                            event_type.upper(),
                            row_key,
                            str(e),
                            exc_info=True,
                        )

            # Sort once at the end if needed
            if needs_sort and self._current_sort_column_key is not None:
                log.debug("Re-sorting table by %s", self._current_sort_column_key)
                try:
                    table.sort(
                        str(self._current_sort_column_key),
                        reverse=self._current_sort_reverse_order,
                        key=lambda cell_value: self._get_sortable_value_from_row(
                            str(self._current_sort_column_key), cell_value
                        ),
                    )
                except Exception as e:
                    log.error("Failed to sort table: %s", str(e), exc_info=True)

            log.debug("Resource event processing completed")
    
    async def _schedule_batch_update(self) -> None:
        """Schedule a batch update to run after the batching window."""
        if self._batch_timer is not None:
            self._batch_timer.cancel()

        # Log the number of pending events when scheduling a batch
        log.debug(
            "Scheduling batch update with %d pending events", len(self._pending_events)
        )

        self._batch_timer = asyncio.get_running_loop().call_later(
            self.BATCH_WINDOW_SECONDS,
            lambda: asyncio.create_task(self._process_batched_events()),
        )

    async def _process_batched_events(self) -> None:
        """Process all pending batched events."""
        async with self._batch_lock:
            if not self._pending_events:
                log.debug("No pending events to process")
                return

            start_time = time.time()
            initial_event_count = len(self._pending_events)
            log.debug("Starting batch processing of %d events", initial_event_count)

            # Enhanced logging for event coalescing
            coalesced_events: dict[str, BatchedEvent] = {}
            while self._pending_events:
                event = self._pending_events.popleft()
                existing = coalesced_events.get(event.resource_key)
                
                log.debug(
                    "Coalescing %s event for key '%s' (existing=%s)",
                    event.event_type.name,
                    event.resource_key,
                    existing.event_type.name if existing else "None"
                )

                # If we already have a DELETE event for this resource, skip any other events
                if existing and existing.event_type == EventType.DELETED:
                    log.debug("Keeping existing DELETE event for '%s', skipping %s event",
                            event.resource_key, event.event_type.name)
                    continue

                # If this is a DELETE event, it supersedes any existing event
                if event.event_type == EventType.DELETED:
                    log.debug("DELETE event supersedes existing %s event for '%s'",
                            existing.event_type.name if existing else "None",
                            event.resource_key)
                    coalesced_events[event.resource_key] = event
                    continue

                # For ADD events, they should always replace existing events
                if event.event_type == EventType.ADDED:
                    coalesced_events[event.resource_key] = event
                    continue

                # For MODIFY events, only update if we don't have an ADD event
                if event.event_type == EventType.MODIFIED:
                    if not existing or existing.event_type == EventType.MODIFIED:
                        coalesced_events[event.resource_key] = event

            # Log batching effectiveness
            final_event_count = len(coalesced_events)
            reduction_percent = (
                ((initial_event_count - final_event_count) / initial_event_count * 100)
                if initial_event_count > 0
                else 0
            )

            log.info(
                "Batch processing: %d events coalesced to %d (%.1f%% reduction) in %.3f seconds",
                initial_event_count,
                final_event_count,
                reduction_percent,
                time.time() - start_time,
            )

            # Convert coalesced events to the format expected by _process_resource_events
            # Process in order: DELETE -> ADD -> MODIFY
            delete_events = []
            add_events = []
            modify_events = []

            for event in coalesced_events.values():
                if event.event_type == EventType.DELETED:
                    delete_events.append((event.resource_key, "deleted", None))
                elif event.event_type == EventType.ADDED:
                    add_events.append((event.resource_key, "added", event.resource))
                else:  # MODIFIED
                    modify_events.append(
                        (event.resource_key, "modified", event.resource)
                    )

            # Log event type distribution
            log.debug(
                "Event distribution - Deletes: %d, Adds: %d, Modifies: %d",
                len(delete_events),
                len(add_events),
                len(modify_events),
            )

            # Process all events in a single batch, in the correct order
            events_to_process = delete_events + add_events + modify_events
            if events_to_process:
                try:
                    log.debug("Processing %d events", len(events_to_process))
                    await self._process_resource_events(events_to_process)
                    log.debug("Event processing completed")
                except Exception as e:
                    log.error(
                        "Error processing batched events: %s", str(e), exc_info=True
                    )
                    raise  # Re-raise to ensure the error is properly handled
            else:
                log.debug("No events to process after coalescing")

    async def _add_event_to_batch(
        self,
        event_type: EventType,
        resource_key: str,
        resource: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to the pending batch."""
        async with self._batch_lock:
            # For non-delete events, ensure we use the correct key format
            if event_type != EventType.DELETED and resource is not None:
                metadata = resource.get("metadata", {})
                name = metadata.get("name")
                namespace = metadata.get("namespace")
                resource_key = f"{namespace}:{name}" if namespace else name
            
            # Enhanced logging for event batching
            log.debug(
                "Adding %s event for key '%s' to batch (current size: %d, has_resource: %s)",
                event_type.name,
                resource_key,
                len(self._pending_events),
                "Yes" if resource is not None else "No"
            )

            # For delete events, verify the key exists in the table
            if event_type == EventType.DELETED:
                try:
                    table = self.query_one(DataTable)
                    if resource_key in table.rows:
                        log.debug("Verified key '%s' exists in table before queueing delete", resource_key)
                    else:
                        log.warning("Key '%s' not found in table before queueing delete. Current keys: %s", 
                                  resource_key, list(table.rows.keys()))
                except Exception as e:
                    log.error("Error verifying table key: %s", str(e))

            self._pending_events.append(
                BatchedEvent(
                    event_type=event_type, resource_key=resource_key, resource=resource
                )
            )
            await self._schedule_batch_update()
    

    async def on_resource_added(self, event: ResourceAddedSignal) -> None:
        """Handle resource added event."""
        if self._is_suspended:
            return

        resource = await self._get_resource_from_event(event)
        if not resource:
            return

        log.info(
            "HANDLER '%s' TRIGGERED for: %s (namespace: %s)",
            event.__class__.__name__,
            event.resource_key,
            event.identifier.namespace or "None",
        )

        await self._add_event_to_batch(EventType.ADDED, event.resource_key, resource)

    async def on_resource_modified(self, event: ResourceModifiedSignal) -> None:
        """Handle resource modified event."""
        if self._is_suspended:
            return

        resource = await self._get_resource_from_event(event)
        if not resource:
            return

        log.info(
            "HANDLER '%s' TRIGGERED for: %s (namespace: %s)",
            event.__class__.__name__,
            event.resource_key,
            event.identifier.namespace or "None",
        )

        await self._add_event_to_batch(EventType.MODIFIED, event.resource_key, resource)

    async def on_resource_deleted(self, event: ResourceDeletedSignal) -> None:
        """Handle resource deleted event."""
        if self._is_suspended:
            return

        # Enhanced logging for delete events
        log.info(
            "DELETE event received for resource_type=%s, resource_key=%s, namespace=%s",
            event.identifier.resource_type,
            event.resource_key,
            event.identifier.namespace or "None"
        )

        resource_key = f"{event.identifier.namespace}:{event.resource_key}" if event.identifier.namespace else event.resource_key
        log.debug("Constructed table key for delete event: %s", resource_key)

        await self._add_event_to_batch(EventType.DELETED, resource_key)
    
    async def _get_resource_from_event(
        self, event: ResourceSignal
    ) -> dict[str, Any] | None:
        """Get the resource data for an event."""
        if isinstance(event, ResourceFullRefreshSignal):
            return None

        # Get the specific resource directly from the event source
        return await self._event_source.get_one(
            event.identifier.resource_type,
            event.identifier.namespace,
            event.resource_key
        )
