from __future__ import annotations
import logging
from typing import (
    Any,
    cast,
    Literal,
    Callable,
)
from datetime import datetime, timezone
from dataclasses import dataclass, field
import re
from functools import total_ordering, lru_cache

from textual import on, work
from textual.widgets import DataTable
from textual.widgets.data_table import RowDoesNotExist, CellDoesNotExist, ColumnKey
from textual.events import MouseMove, Resize
from textual.reactive import reactive
from textual.signal import Signal
import asyncio

from KubeZen.core.watch_manager import WatchManager

from rich.text import Text


from KubeZen.models.base import UIRow
from kubernetes_asyncio.client.exceptions import ApiException
from aiohttp.client_exceptions import ClientConnectorError


log = logging.getLogger(__name__)


@total_ordering
@dataclass
class _SortKey:
    """A rich comparison key that handles None and TypeError during sorting."""

    value: Any = field(compare=False)
    is_none: bool = field(init=False, compare=False)

    def __post_init__(self):
        self.is_none = self.value is None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _SortKey):
            return NotImplemented
        return bool(self.value == other.value)

    def __lt__(self, other: "_SortKey") -> bool:
        if self.is_none and not other.is_none:
            return True
        if not self.is_none and other.is_none:
            return False
        if self.is_none and other.is_none:
            return False
        try:
            return bool(self.value < other.value)
        except TypeError:
            # Fallback to string comparison if types are not comparable
            return str(self.value) < str(other.value)


_AGE_MULTIPLIERS: dict[str, int] = {"d": 24 * 60, "h": 60, "m": 1}
_AGE_REGEX = re.compile(r"(\d+)([dhm])")


def _sort_by_age(value: Any) -> float:
    """Converts an age string (e.g., '5d', '10h3m') into minutes for sorting."""
    if not isinstance(value, str):
        return float("inf")
    total_minutes = 0
    parts = _AGE_REGEX.findall(value)
    for val, unit in parts:
        total_minutes += int(val) * _AGE_MULTIPLIERS[unit]
    return total_minutes


def _sort_by_status(value: Any) -> int:
    """Assigns a numerical priority to a status string for sorting."""
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
    return status_priority.get(str(value), 99)


def _sort_by_ready(value: Any) -> int:
    """Sorts by the number of ready containers indicated by '■'."""
    if isinstance(value, Text):
        return value.plain.count("■")
    return 0


def _sort_by_cpu(value: Any) -> float:
    """Converts a CPU string (in cores) to a float for sorting."""
    try:
        if not value or value == "n/a":
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# A map for memory unit multipliers
_MEMORY_MULTIPLIERS: dict[str, float] = {
    "Ki": 1024.0,
    "Mi": 1024.0**2,
    "Gi": 1024.0**3,
    "Ti": 1024.0**4,
    "Pi": 1024.0**5,
    "Ei": 1024.0**6,
}
# Pre-compiled regex for memory values
_MEMORY_REGEX = re.compile(r"(\d+\.?\d*)\s*([KMGTPE]i)?")


def _sort_by_memory(value: Any) -> float:
    """Converts a memory string (e.g., '512Mi') to bytes for sorting."""
    if not isinstance(value, str) or value == "n/a":
        return 0.0

    match = _MEMORY_REGEX.fullmatch(value.strip())
    if not match:
        return 0.0

    val_str, unit = match.groups()
    try:
        val = float(val_str)
        if unit:
            return val * _MEMORY_MULTIPLIERS.get(unit, 1.0)
        return val
    except (ValueError, TypeError):
        return 0.0


# --- Sorter Dispatch Table ---

# A map from a column key to the function that can parse it for sorting.
SORTER_DISPATCH: dict[str, Callable[[Any], Any]] = {
    "age": _sort_by_age,
    "Status": _sort_by_status,
    "ready": _sort_by_ready,
    "cpu": _sort_by_cpu,
    "memory": _sort_by_memory,
}


@dataclass(frozen=True)
class Columns:
    model_class: type[UIRow]
    metadata: list[dict[str, Any]] = field(init=False)
    column_keys: list[str] = field(init=False)
    time_tracked_fields: dict[str, Literal["age", "countdown"]] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", self.model_class.get_columns())
        object.__setattr__(self, "column_keys", self.model_class.get_column_keys())
        object.__setattr__(
            self, "time_tracked_fields", self.model_class.get_time_tracked_fields()
        )


@dataclass()
class Sorting:
    current_column_key: str | None = None
    reverse_order: bool = False


class ResourceList(DataTable):
    """A data table that displays a list of Kubernetes resources."""

    resources: reactive[dict[str, UIRow]] = reactive({}, layout=False, init=False)
    selected_namespaces: reactive[set[str]] = reactive(
        set[str](), layout=False, init=False
    )
    first_selected_namespace: str | None = None
    visible_uids: reactive[set[str]] = reactive(set[str](), layout=False, init=False)
    search_input: reactive[str] = reactive("", layout=False, init=False)
    pod_metrics: reactive[dict[str, dict[str, Any]]] = reactive(
        {}, layout=False, init=False
    )

    PADDING_PER_COLUMN = 2
    OUTER_PADDING = 2

    DEFAULT_CSS = """
    ResourceList {
        height: 1fr;
        width: 100%;
        background: transparent;
        color: $text;
        border: round $primary;
    }
    ResourceList > .datatable--header {
        background: yellow;
        color: $primary;
        text-style: bold;
    }
    """

    def __init__(
        self,
        model_class: type[UIRow],
    ) -> None:
        """Initialise the resource list."""
        super().__init__(cursor_type="row", cursor_foreground_priority="renderable")
        self._model_class = model_class
        self.subscriptions: dict[str, Signal] = {}
        self._watch_manager: WatchManager = WatchManager(self.app, model_class)
        self._columns = Columns(self._model_class)
        self._add_columns()
        self.tooltip: str | None = None
        self._sorting = Sorting()

    @property
    def model_class(self) -> type[UIRow]:
        """The model class for the resource list."""
        return self._model_class

    def __del__(self) -> None:
        """Log when the resource list is destroyed."""
        log.debug("ResourceList destroyed")

    @lru_cache(maxsize=128)
    def _get_column_width(self, column_key: str, now: datetime) -> int:
        column_info = next(
            (c for c in self._columns.metadata if c["key"] == column_key), None
        )

        if not column_info:
            return 0

        header_width = len(str(column_info["label"]))

        # Check if the column is a time-tracked field
        is_time_tracked = column_key in self._columns.time_tracked_fields

        if is_time_tracked:
            field_type = self._columns.time_tracked_fields[column_key]
            formatter = (
                UIRow.format_age if field_type == "age" else UIRow.format_countdown
            )

            max_content_width = max(
                (
                    len(formatter(getattr(self.resources[uid], column_key), now))
                    for uid in self.visible_uids
                    if uid in self.resources
                    and getattr(self.resources[uid], column_key) is not None
                ),
                default=0,
            )
        else:
            max_content_width = max(
                (
                    len(str(getattr(self.resources[uid], column_key, "")))
                    for uid in self.visible_uids
                    if uid in self.resources
                ),
                default=0,
            )

        fixed_width = column_info.get("width") or 0

        final_width = max(header_width, max_content_width, fixed_width)

        return final_width

    @on(Resize)
    def _update_table_layout(self) -> None:
        if not self.visible_uids:
            return

        column_keys = self._columns.column_keys
        if not column_keys:
            return

        first_column_key = column_keys[0]
        is_scrollbar_visible = self.row_count > self.content_region.height
        scrollbar_width = 2 if is_scrollbar_visible else 0

        fixed_width_sum = 0
        now = datetime.now(timezone.utc)

        with self.app.batch_update():
            for key in column_keys:
                is_first = key == first_column_key
                if is_first:
                    continue  # We compute this after we know fixed_width_sum
                width = self._get_column_width(key, now)
                fixed_width_sum += width + self.PADDING_PER_COLUMN
                self.columns[ColumnKey(key)].width = width

            # Now compute free space for the first column and set it
            free_space = (
                self.size.width - fixed_width_sum - scrollbar_width - self.OUTER_PADDING
            )
            self.columns[ColumnKey(first_column_key)].width = max(8, free_space)

            self.refresh()

    def on_age_update(self, updates: list[tuple[str, str, datetime]]) -> None:
        """Update age and countdown cells in the data table."""
        if not updates:
            return
        try:
            now = datetime.now(timezone.utc)
            with self.app.batch_update():
                for uid, field_name, timestamp in updates:
                    field_type = self._columns.time_tracked_fields.get(field_name)
                    if not field_type:
                        continue

                    formatter = (
                        UIRow.format_age
                        if field_type == "age"
                        else UIRow.format_countdown
                    )
                    formatted_time = formatter(timestamp, now)
                    try:
                        self.update_cell(
                            uid, field_name, formatted_time, update_width=False
                        )
                    except (RowDoesNotExist, CellDoesNotExist):
                        log.debug(
                            "Row %s does not exist in table during age update", uid
                        )
                        continue
        except Exception as e:
            log.error("Error updating time cells: %s", e, exc_info=True)

    def watch_pod_metrics(self, metrics: dict[str, dict[str, Any]] | None) -> None:
        """Watch for changes in pod metrics and update the table."""
        if not metrics:
            return
        with self.app.batch_update():
            for uid, pod_metrics in metrics.items():
                if uid not in self.visible_uids:
                    continue
                try:
                    if "cpu" in self._columns.column_keys:
                        cpu_cores = float(pod_metrics.get("cpu", 0.0))
                        cpu_text = f"{cpu_cores:.3f}"
                        self.update_cell(uid, "cpu", cpu_text, update_width=False)

                    if "memory" in self._columns.column_keys:
                        memory_bytes = pod_metrics.get("memory", 0)
                        units = ["B", "Ki", "Mi", "Gi", "Ti"]
                        unit_index = 0
                        memory_value = float(memory_bytes)

                        while memory_value >= 1024 and unit_index < len(units) - 1:
                            memory_value /= 1024
                            unit_index += 1

                        memory_text = f"{memory_value:.1f}{units[unit_index]}"
                        self.update_cell(uid, "memory", memory_text, update_width=False)
                except (RowDoesNotExist, CellDoesNotExist):
                    continue

    async def watch_resources(self, resources: dict[str, UIRow] | None) -> None:
        if not resources:
            self.visible_uids = set()
            return

        if not self.search_input:
            self.visible_uids = {resource.uid for resource in resources.values()}
        elif self.search_input:
            filtered_uids = {
                resource.uid
                for resource in resources.values()
                if self._resource_matches_filters(resource)
            }
            if filtered_uids != self.visible_uids:
                self.visible_uids = filtered_uids

    @on(MouseMove)
    def _show_tooltip(self, event: MouseMove) -> None:
        """Handle mouse movement to display tooltips."""
        if event.style and "@tooltip" in event.style.meta:
            tooltip_text = event.style.meta["@tooltip"]
            if self.tooltip != tooltip_text:
                self.tooltip = tooltip_text
        elif self.tooltip:
            self.tooltip = None

    async def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Populate the subscriptions' dictionary for this instance
        self.subscriptions["resource_added"] = (
            self._watch_manager.signals.resource_added
        )
        self.subscriptions["resource_deleted"] = (
            self._watch_manager.signals.resource_deleted
        )
        self.subscriptions["resource_modified"] = (
            self._watch_manager.signals.resource_modified
        )
        self.subscriptions["resource_full_reset"] = (
            self._watch_manager.signals.resource_full_reset
        )

        # if age_signal := self.app.age_tracker.get_signal(self._model_class.plural):
        self.subscriptions["age_tracker"] = self.app.age_tracker.get_signal(
            self._model_class.plural
        )

        # Subscribe handlers directly
        self.subscriptions["resource_added"].subscribe(self, self.on_resource_added)
        self.subscriptions["resource_deleted"].subscribe(self, self.on_resource_deleted)
        self.subscriptions["resource_modified"].subscribe(
            self, self.on_resource_modified
        )
        # self.subscriptions["resource_full_reset"].subscribe(
        # self, self.on_resource_full_reset
        # )

        self.subscriptions["age_tracker"].subscribe(self, self.on_age_update)

        if self._model_class.plural == "pods":
            self._metrics_timer = self.set_interval(
                5,
                self._update_metrics,
                name="Pod Metrics",
            )

    async def on_unmount(self) -> None:
        """Cleanup subscriptions when the widget is unmounted."""
        await self._watch_manager.stop()
        for subscription in self.subscriptions.values():
            subscription.unsubscribe(self)
        self.subscriptions.clear()
        self._get_column_width.cache_clear()
        self.app.age_tracker.clear_resource_type(self._model_class.plural)

        if self._model_class.plural == "pods":
            self._metrics_timer.stop()

    def _add_columns(self) -> None:
        """Add columns to the data table based on the model's metadata."""
        with self.app.batch_update():
            for column_info in self._columns.metadata:
                self.add_column(
                    label=str(column_info["label"]),
                    key=str(column_info["key"]),
                    width=column_info.get("width"),
                )

    def watch_search_input(self, search_input: str) -> None:
        """Called when the search input changes."""
        if search_input == "" and self.visible_uids == self.resources.keys():
            return
        self.visible_uids = {
            resource.uid
            for resource in self.resources.values()
            if self._resource_matches_filters(resource)
        }

    def _resource_should_be_in_view(self, resource: UIRow) -> bool:
        """Checks if a resource belongs in the current namespace selection."""
        if not self._model_class.namespaced:
            return True
        if "all" in self.selected_namespaces:
            return True
        if resource.namespace in self.selected_namespaces:
            return True
        return False

    def on_resource_added(self, data: dict[str, Any]) -> None:
        """Handles a resource added event."""
        resource = data["resource"]
        if self._resource_should_be_in_view(resource):
            self.resources[resource.uid] = resource
        if self._resource_matches_filters(resource):
            self.visible_uids = self.visible_uids | {resource.uid}

    def on_resource_deleted(self, data: dict[str, Any]) -> None:
        """Handles a resource deleted event."""
        resource = data["resource"]
        uid = resource.uid
        del self.resources[uid]
        if uid in self.visible_uids:
            self.visible_uids = self.visible_uids - {uid}

    def on_resource_modified(self, data: dict[str, Any]) -> None:
        """Handles inexpensive, immediate UI updates for already-visible rows."""

        resource = data["resource"]
        uid = resource.uid

        # Update the primary list first
        self.resources[uid] = resource

        # If the row is not visible on screen, there's nothing to do.
        if uid not in self.visible_uids:
            return

        self._get_column_width.cache_clear()
        with self.app.batch_update():
            try:
                # --- Update standard, non-age-tracked cells ---
                for key in self._columns.column_keys:
                    if key in self._columns.time_tracked_fields or key in (
                        "cpu",
                        "memory",
                    ):
                        continue
                    value = getattr(resource, key, "")
                    self.update_cell(uid, key, value, update_width=False)

                for field_key, field_type in self._columns.time_tracked_fields.items():
                    # The 'age' is based on creationTimestamp, which is immutable.
                    # We should not re-process it on modification events.
                    if field_key == "age":
                        continue

                    self.app.age_tracker.remove_field(
                        uid, field_key, self._model_class.plural
                    )

                    if dt_obj := getattr(resource, field_key, None):
                        # Format the initial display for the new value
                        self.app.age_tracker.track_field(
                            uid, field_key, dt_obj, field_type, self._model_class.plural
                        )
                    else:
                        # If there's no new timestamp, display N/A
                        self.update_cell(uid, field_key, "N/A", update_width=False)

            except RowDoesNotExist:
                log.debug("Row %s does not exist in table during modification", uid)

    def _resource_matches_filters(self, resource: UIRow) -> bool:
        # Check search filter
        if search_text := self.search_input:
            if search_text not in resource.name:
                if not (resource.namespace and search_text in resource.namespace):
                    return False
        return True

    def _add_row(self, resource: UIRow) -> None:
        new_cells = [getattr(resource, key, "") for key in self._columns.column_keys]
        now = datetime.now(timezone.utc)

        for field_key, field_type in self._columns.time_tracked_fields.items():
            # The datetime object should be pre-computed on the model.
            if dt_obj := getattr(resource, field_key, None):
                age_index = self._columns.column_keys.index(field_key)
                formatter = (
                    UIRow.format_age if field_type == "age" else UIRow.format_countdown
                )
                new_cells[age_index] = formatter(dt_obj, now)
                self.app.age_tracker.track_field(
                    resource.uid,
                    field_key,
                    dt_obj,
                    field_type,
                    self._model_class.plural,
                )
        try:
            self.add_row(*new_cells, key=resource.uid)
        except Exception as e:
            log.error("Error adding row for UID %s: %s", resource.uid, e, exc_info=True)

    @on(DataTable.HeaderSelected)
    def _trigger_sorting(self, message: DataTable.HeaderSelected) -> None:
        """Handle column header clicks for interactive sorting."""
        new_sort_column_key = cast(str, message.column_key.value)

        if new_sort_column_key == self._sorting.current_column_key:
            self._sorting.reverse_order = not self._sorting.reverse_order
        else:
            self._sorting.current_column_key = new_sort_column_key
            self._sorting.reverse_order = True

        self._sort_rows()

    def _sort_rows(self) -> None:
        if not self._sorting.current_column_key:
            self.sort()
            return

        if sorter := SORTER_DISPATCH.get(self._sorting.current_column_key):
            key_func = lambda value: _SortKey(sorter(value))
        else:
            key_func = _SortKey

        self.sort(
            self._sorting.current_column_key,
            reverse=self._sorting.reverse_order,
            key=key_func,
        )

    @work(exclusive=True)
    async def _update_metrics(self) -> None:
        if self._model_class.__name__ != "PodRow":
            return

        try:
            # Create a map from namespace/name to UID for efficient lookup,
            # but only for the pods that are currently visible.
            name_to_uid_map = {
                f"{self.resources[uid].namespace or ''}/{self.resources[uid].name}": uid
                for uid in self.visible_uids
                if uid in self.resources
            }

            all_pod_metrics = await self.app.kubernetes_client.fetch_pod_metrics()

            self.pod_metrics = dict(
                (name_to_uid_map[pod_name], metrics)
                for pod_name, metrics in all_pod_metrics.items()
                if pod_name in name_to_uid_map
            )

        except Exception as e:
            log.error("Error updating metrics: %s", e)
            self.pod_metrics = {}

    def _remove_row(self, uid: str) -> None:
        """Removes a row from the table and stops tracking its age."""
        try:
            self.remove_row(uid)
            self.app.age_tracker.remove_item(uid, self._model_class.plural)
        except (RowDoesNotExist, KeyError):
            log.debug("Row %s does not exist in table", uid)
        except Exception as e:
            log.error("Failed to remove row for: %s", e)

    def watch_visible_uids(self, old_uids: set[str], new_uids: set[str]) -> None:
        if new_uids == old_uids:
            return

        self._get_column_width.cache_clear()
        if not new_uids:
            self.clear()
            self.app.age_tracker.clear_resource_type(self._model_class.plural)
        elif not old_uids and new_uids == self.resources.keys():
            with self.app.batch_update():
                for uid in self.resources:
                    self._add_row(self.resources[uid])
                self._sort_rows()
                self._update_table_layout()
        else:
            uids_to_remove = old_uids - new_uids
            uids_to_add = new_uids - old_uids

            with self.app.batch_update():
                for uid in uids_to_remove:
                    self._remove_row(uid)
                for uid in uids_to_add:
                    if uid in self.resources:
                        self._add_row(self.resources[uid])

                if uids_to_add:
                    self._sort_rows()

                self._update_table_layout()

        if self._model_class.__name__ == "PodRow":
            self.call_after_refresh(self._update_metrics)

    async def watch_selected_namespaces(self, selected_namespaces: set[str]) -> None:
        """Watch the selected namespaces."""
        log.info(f"Watching selected namespaces: {selected_namespaces}")

        # If 'all' is selected, that's the only watch we need.
        if "all" in selected_namespaces:
            effective_selection = {"all"}
        else:
            effective_selection = selected_namespaces

        # If nothing is selected, ensure resources are cleared and stop all watches.
        if not selected_namespaces:
            self.resources = {}
            await self._watch_manager.stop()
            return

        current_watching = self._watch_manager.watching
        namespaces_to_load = effective_selection

        to_stop = current_watching - effective_selection
        for ns in to_stop:
            await self._watch_manager.stop_namespace_watch(ns)

        to_start = effective_selection - current_watching

        if not to_start and not to_stop:
            return

        # This will hold all resources from all namespaces being loaded.
        all_resources_dict: dict[str, UIRow] = {}

        for namespace in namespaces_to_load:
            create_task = namespace in to_start
            try:
                (
                    resource_generator,
                    resource_version,
                ) = await self._watch_manager.get_initial_list(namespace)
            except (ApiException, ClientConnectorError, asyncio.TimeoutError) as e:
                log.error(f"Error getting initial list for {namespace}: {e}")
                self.app.notify(
                    f"Failed to get resources for '{namespace}'. Please check your connection and permissions.",
                    title="Error",
                    severity="error",
                    timeout=10,
                )
                break

            # Consume the generator to populate the dictionary.
            for res in resource_generator:
                all_resources_dict[res.uid] = res

            if create_task:
                await self._watch_manager.create_watch_task(namespace, resource_version)

        self.resources = all_resources_dict
