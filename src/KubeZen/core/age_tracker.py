from __future__ import annotations
from datetime import datetime, timezone, timedelta
import logging
from typing import (
    Set,
    Optional,
    TypedDict,
    Dict,
    List,
    Union,
    ClassVar,
    TYPE_CHECKING,
    Generator,
    Tuple,
)
from collections import namedtuple
from dataclasses import dataclass, field

from textual.signal import Signal

if TYPE_CHECKING:
    from ..app import KubeZen
    from textual.timer import Timer


log = logging.getLogger(__name__)


TrackedItem = namedtuple(
    "TrackedItem", ["uid", "field", "timestamp", "field_type", "resource_type"]
)


@dataclass
class TrackerState:
    """Encapsulates all state data for the age tracker."""

    # Buckets for age and countdown tracking, organized by resource type
    age_buckets: Dict[str, Dict[str, List[TrackedItem]]] = field(default_factory=dict)
    countdown_buckets: Dict[str, Dict[str, List[TrackedItem]]] = field(
        default_factory=dict
    )

    # Quick lookup maps
    item_to_bucket_map: Dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )  # (uid, field, resource_type) -> bucket_name
    next_threshold_times: Dict[tuple[str, str, str], datetime] = field(
        default_factory=dict
    )  # (uid, field, resource_type) -> transition_time
    tracked_items_by_uid: Dict[str, Set[str]] = field(
        default_factory=dict
    )  # uid -> set of field names

    def clear(self) -> None:
        """Clear all state data."""
        self.age_buckets.clear()
        self.countdown_buckets.clear()
        self.item_to_bucket_map.clear()
        self.next_threshold_times.clear()
        self.tracked_items_by_uid.clear()

    def clear_resource_type(self, resource_type: str) -> None:
        """Clear all state data for a specific resource type."""
        # Clear age and countdown buckets
        for bucket_dict in (self.age_buckets, self.countdown_buckets):
            if resource_type in bucket_dict:
                bucket_dict.pop(resource_type, None)

        # Remove mappings and next threshold times for the resource type
        self.item_to_bucket_map = {
            key: bucket
            for key, bucket in self.item_to_bucket_map.items()
            if key[2] != resource_type
        }
        self.next_threshold_times = {
            key: time
            for key, time in self.next_threshold_times.items()
            if key[2] != resource_type
        }

        # Clear tracked UIDs that are no longer referenced
        referenced_uids = {key[0] for key in self.item_to_bucket_map.keys()}
        self.tracked_items_by_uid = {
            uid: fields
            for uid, fields in self.tracked_items_by_uid.items()
            if uid in referenced_uids
        }


class BucketConfig(TypedDict):
    """Type definition for bucket configuration."""

    threshold: Union[float, int]
    next: Optional[str]
    freq: str


class AgeTracker:
    """Tracks ages of items and manages transitions between age buckets."""

    # Single source of truth for bucket configuration.
    # The dictionary must be defined in ascending order of thresholds.
    AGE_BUCKET_CONFIG: Dict[str, BucketConfig] = {
        "secs (<2m)": {"threshold": 120, "next": "min_sec (2-10m)", "freq": "seconds"},
        "min_sec (2-10m)": {
            "threshold": 600,
            "next": "mins (10-60m)",
            "freq": "seconds",
        },
        "mins (10-60m)": {
            "threshold": 3600,
            "next": "hour_min (1-10h)",
            "freq": "minutes",
        },
        "hour_min (1-10h)": {
            "threshold": 36000,
            "next": "hours (10-24h)",
            "freq": "minutes",
        },
        "hours (10-24h)": {
            "threshold": 86400,
            "next": "day_hour (1-10d)",
            "freq": "hours",
        },
        "day_hour (1-10d)": {
            "threshold": 864000,
            "next": "days (>10d)",
            "freq": "hours",
        },
        "days (>10d)": {"threshold": float("inf"), "next": None, "freq": "days"},
    }

    COUNTDOWN_BUCKET_CONFIG: Dict[str, BucketConfig] = {
        "secs (<2m)": {"threshold": 120, "next": "min_sec (2-10m)", "freq": "seconds"},
        "min_sec (2-10m)": {
            "threshold": 600,
            "next": "mins (10-60m)",
            "freq": "seconds",
        },
        "mins (10-60m)": {
            "threshold": 3600,
            "next": "hours (1-24h)",
            "freq": "seconds",
        },
        "hours (1-24h)": {
            "threshold": 86400,
            "next": "day_hour (1-10d)",
            "freq": "minutes",
        },
        "day_hour (1-10d)": {
            "threshold": 864000,
            "next": "days (>10d)",
            "freq": "hours",
        },
        "days (>10d)": {"threshold": float("inf"), "next": None, "freq": "days"},
    }

    # Add singleton class variable
    _instance: ClassVar[AgeTracker | None] = None

    def __init__(self, app: "KubeZen") -> None:
        """Initialize the age tracker."""
        self._app = app
        self._state = TrackerState()
        self._resource_signals: Dict[str, Signal[list[tuple[str, str, datetime]]]] = {}
        self._countdown_prev_map = {
            v["next"]: k for k, v in self.COUNTDOWN_BUCKET_CONFIG.items() if v["next"]
        }
        self._timer: Timer | None = self._app.set_interval(1, self.update_ages)

        for resource_model in self._app.resource_models.values():
            self._create_signal(resource_model.plural)

    @classmethod
    def get_instance(cls, app: "KubeZen") -> "AgeTracker":
        """Returns the singleton instance of the AgeTracker."""
        if cls._instance is None:
            cls._instance = AgeTracker(app)
            log.info("AgeTracker singleton initialized.")
        return cls._instance

    def __del__(self) -> None:
        """Log when the age tracker is destroyed."""
        if self._timer:
            self._timer.stop()
        log.debug("AgeTracker instance destroyed")

    def clear(self) -> None:
        """Clear all tracked items and buckets."""
        self._state.clear()
        log.debug("AgeTracker cleared.")

    def clear_resource_type(self, resource_type: str) -> None:
        """Clear all tracked items and buckets for a specific resource type."""
        self._state.clear_resource_type(resource_type)
        log.debug("Cleared tracking data for resource type: %s", resource_type)

    def is_tracking_field(self, uid: str, field: str, resource_type: str) -> bool:
        """Check if a specific field for a given UID is being tracked."""
        tracked_fields = self._state.tracked_items_by_uid.get(uid, set())
        return bool(uid and field in tracked_fields)

    def _create_signal(self, resource_type: str) -> Signal:
        """Get the signal for a specific resource type, creating it if it doesn't exist."""
        if resource_type not in self._resource_signals:
            self._resource_signals[resource_type] = Signal(
                self._app, f"age_updated_{resource_type}"
            )
        return self._resource_signals[resource_type]

    def get_signal(self, resource_type: str) -> Signal | None:
        """Get the signal for a specific resource type."""
        return self._resource_signals.get(resource_type)

    def track_field(
        self,
        uid: str,
        field: str,
        timestamp: datetime | None,
        field_type: str,
        resource_type: str,
    ) -> None:
        """Track a specific field for updates."""
        if timestamp is None:
            log.debug(
                "Not tracking field '%s' for %s because timestamp is None.", field, uid
            )
            return

        # --- FIX STARTS HERE ---
        # Ensure the nested dictionaries for the resource type exist before any operation.
        if resource_type not in self._state.age_buckets:
            self._state.age_buckets[resource_type] = {
                bucket: [] for bucket in self.AGE_BUCKET_CONFIG
            }
        if resource_type not in self._state.countdown_buckets:
            self._state.countdown_buckets[resource_type] = {
                bucket: [] for bucket in self.COUNTDOWN_BUCKET_CONFIG
            }
        # --- FIX ENDS HERE ---

        now = datetime.now(timezone.utc)
        item_key = (uid, field, resource_type)

        # Check if it's already being tracked and remove it to re-bucket it.
        if item_key in self._state.item_to_bucket_map:
            self.remove_field(uid, field, resource_type)

        # Track the field for the given UID
        self._track_field_for_uid(uid, field)

        item = TrackedItem(uid, field, timestamp, field_type, resource_type)
        if field_type == "age":
            self._assign_to_age_bucket(item, now)
        elif field_type == "countdown":
            self._assign_to_countdown_bucket(item, now)

    def _track_field_for_uid(self, uid: str, field: str) -> None:
        if uid not in self._state.tracked_items_by_uid:
            self._state.tracked_items_by_uid[uid] = set()
        self._state.tracked_items_by_uid[uid].add(field)

    def _assign_to_age_bucket(self, item: TrackedItem, now: datetime) -> None:
        age_seconds = (now - item.timestamp).total_seconds()
        for bucket_name, config in self.AGE_BUCKET_CONFIG.items():
            if age_seconds < config["threshold"]:
                self._state.age_buckets[item.resource_type][bucket_name].append(item)
                self._state.item_to_bucket_map[
                    (item.uid, item.field, item.resource_type)
                ] = bucket_name
                self._set_next_transition_time(item, now)
                break

    def _assign_to_countdown_bucket(self, item: TrackedItem, now: datetime) -> None:
        countdown_seconds = (item.timestamp - now).total_seconds()
        if countdown_seconds < 0:
            return
        for bucket_name, config in self.COUNTDOWN_BUCKET_CONFIG.items():
            if countdown_seconds < config["threshold"]:
                self._state.countdown_buckets[item.resource_type][bucket_name].append(
                    item
                )
                self._state.item_to_bucket_map[
                    (item.uid, item.field, item.resource_type)
                ] = bucket_name
                self._set_next_transition_time(item, now)
                break

    def remove_field(self, uid: str, field: str, resource_type: str) -> None:
        item_key = (uid, field, resource_type)
        bucket_name = self._state.item_to_bucket_map.pop(item_key, None)
        if bucket_name:
            # Directly remove from the correct bucket
            self._remove_from_bucket(bucket_name, item_key, resource_type)
            self._state.next_threshold_times.pop(item_key, None)
            self._state.tracked_items_by_uid[uid].discard(field)
            if not self._state.tracked_items_by_uid[uid]:
                self._state.tracked_items_by_uid.pop(uid)

    def _remove_from_bucket(
        self, bucket_name: str, item_key: tuple[str, str, str], resource_type: str
    ) -> None:
        if bucket_name in self._state.age_buckets[resource_type]:
            self._state.age_buckets[resource_type][bucket_name] = [
                item
                for item in self._state.age_buckets[resource_type][bucket_name]
                if (item.uid, item.field, item.resource_type) != item_key
            ]
        elif bucket_name in self._state.countdown_buckets[resource_type]:
            self._state.countdown_buckets[resource_type][bucket_name] = [
                item
                for item in self._state.countdown_buckets[resource_type][bucket_name]
                if (item.uid, item.field, item.resource_type) != item_key
            ]

    def remove_item(self, uid: str, resource_type: str) -> None:
        """Remove all tracked fields for a given item UID."""
        fields_to_remove = self._state.tracked_items_by_uid.pop(uid, set())
        for tracked_field in fields_to_remove:
            item_key = (uid, tracked_field, resource_type)
            bucket = self._state.item_to_bucket_map.pop(item_key, None)
            if bucket is not None:
                self._state.next_threshold_times.pop(item_key, None)
                if bucket in self._state.age_buckets.get(resource_type, {}):
                    self._state.age_buckets[resource_type][bucket] = [
                        item
                        for item in self._state.age_buckets[resource_type][bucket]
                        if not (
                            item.uid == uid
                            and item.field == tracked_field
                            and item.resource_type == resource_type
                        )
                    ]
                if bucket in self._state.countdown_buckets.get(resource_type, {}):
                    self._state.countdown_buckets[resource_type][bucket] = [
                        item
                        for item in self._state.countdown_buckets[resource_type][bucket]
                        if not (
                            item.uid == uid
                            and item.field == tracked_field
                            and item.resource_type == resource_type
                        )
                    ]
        log.debug("Stopped tracking all fields for %s", uid)

    def _set_next_transition_time(self, item: TrackedItem, now: datetime) -> None:
        """Calculate and set the time for the item's next potential bucket transition."""
        item_key = (item.uid, item.field, item.resource_type)
        self._state.next_threshold_times.pop(item_key, None)  # Clear any existing time

        bucket_name = self._state.item_to_bucket_map.get(item_key)
        if not bucket_name:
            return

        if item.field_type == "age":
            config = self.AGE_BUCKET_CONFIG[bucket_name]
            if config["next"]:
                transition_time = item.timestamp + timedelta(
                    seconds=float(config["threshold"])
                )
                self._state.next_threshold_times[item_key] = transition_time
        elif item.field_type == "countdown":
            prev_bucket = self._countdown_prev_map.get(bucket_name)
            if prev_bucket:
                prev_bucket_threshold = self.COUNTDOWN_BUCKET_CONFIG[prev_bucket][
                    "threshold"
                ]
                # Time when this item's countdown will equal the threshold of the *previous* bucket
                transition_time = item.timestamp - timedelta(
                    seconds=prev_bucket_threshold
                )
                if transition_time > now:
                    self._state.next_threshold_times[item_key] = transition_time

    def _handle_transitions(
        self, now: datetime
    ) -> Generator[tuple[str, str, datetime, str], None, None]:
        """
        Efficiently checks for and moves items between buckets using pre-calculated
        transition times.

        Yields:
            A tuple for each transitioned item.
        """
        items_due_for_check = [
            key for key, time in self._state.next_threshold_times.items() if now >= time
        ]

        for item_key in items_due_for_check:
            current_bucket_name = self._state.item_to_bucket_map.get(item_key)
            if not current_bucket_name:
                self._state.next_threshold_times.pop(item_key, None)
                continue

            uid, field, resource_type = item_key
            source_bucket_list = None
            config_map = None

            if current_bucket_name in self._state.age_buckets.get(resource_type, {}):
                source_bucket_list = self._state.age_buckets[resource_type][
                    current_bucket_name
                ]
                config_map = self.AGE_BUCKET_CONFIG
            elif current_bucket_name in self._state.countdown_buckets.get(
                resource_type, {}
            ):
                source_bucket_list = self._state.countdown_buckets[resource_type][
                    current_bucket_name
                ]
                config_map = self.COUNTDOWN_BUCKET_CONFIG

            if not source_bucket_list or not config_map:
                continue

            item_index = next(
                (
                    i
                    for i, item in enumerate(source_bucket_list)
                    if (item.uid, item.field, item.resource_type) == item_key
                ),
                -1,
            )

            if item_index == -1:
                self._state.item_to_bucket_map.pop(item_key, None)
                self._state.next_threshold_times.pop(item_key, None)
                continue

            # Found the item. Pop from current bucket.
            item = source_bucket_list.pop(item_index)

            if item.field_type == "age":
                age_seconds = (now - item.timestamp).total_seconds()
                for bucket_name, config in self.AGE_BUCKET_CONFIG.items():
                    if age_seconds < config["threshold"]:
                        self._state.age_buckets[resource_type][bucket_name].append(item)
                        self._state.item_to_bucket_map[item_key] = bucket_name
                        self._set_next_transition_time(item, now)
                        yield (item.uid, item.field, item.timestamp, resource_type)
                        break

            elif item.field_type == "countdown":
                countdown_seconds = (item.timestamp - now).total_seconds()
                if countdown_seconds >= 0:
                    for bucket_name, config in self.COUNTDOWN_BUCKET_CONFIG.items():
                        if countdown_seconds < config["threshold"]:
                            self._state.countdown_buckets[resource_type][
                                bucket_name
                            ].append(item)
                            self._state.item_to_bucket_map[item_key] = bucket_name
                            self._set_next_transition_time(item, now)
                            yield (
                                item.uid,
                                item.field,
                                item.timestamp,
                                resource_type,
                            )
                            break

    def update_ages(self) -> None:
        now = datetime.now(timezone.utc)

        transitioned_generator = self._handle_transitions(now)

        age_buckets_to_refresh = self._get_buckets_to_refresh(
            now, self.AGE_BUCKET_CONFIG
        )
        countdown_buckets_to_refresh = self._get_buckets_to_refresh(
            now, self.COUNTDOWN_BUCKET_CONFIG
        )

        updates_by_type = self._gather_bucket_updates(
            age_buckets_to_refresh, countdown_buckets_to_refresh, now
        )

        for uid, tracked_field, timestamp, resource_type in transitioned_generator:
            updates_by_type.setdefault(resource_type, []).append(
                (uid, tracked_field, timestamp)
            )

        for resource_type, updates in updates_by_type.items():
            if resource_type in self._resource_signals:
                self._resource_signals[resource_type].publish(updates)

    def _get_buckets_to_refresh(
        self, now: datetime, bucket_config: Dict[str, BucketConfig]
    ) -> list[str]:
        return [
            bucket_name
            for bucket_name, config in bucket_config.items()
            if self._should_refresh_bucket(now, config["freq"])
        ]

    def _should_refresh_bucket(self, now: datetime, freq: str) -> bool:
        if freq == "seconds":
            return True
        if freq == "minutes" and now.second == 0:
            return True
        if freq == "hours" and now.second == 0 and now.minute == 0:
            return True
        if freq == "days" and now.second == 0 and now.minute == 0 and now.hour == 0:
            return True
        return False

    def _gather_bucket_updates(
        self,
        age_buckets_to_refresh: list[str],
        countdown_buckets_to_refresh: list[str],
        now: datetime,
    ) -> Dict[str, list[tuple[str, str, datetime]]]:
        updates_by_type: Dict[str, List[Tuple[str, str, datetime]]] = {}
        for resource_type in self._state.age_buckets:
            updates: List[Tuple[str, str, datetime]] = []
            updates.extend(
                self._collect_bucket_updates(
                    self._state.age_buckets[resource_type], age_buckets_to_refresh, now
                )
            )
            updates.extend(
                self._collect_bucket_updates(
                    self._state.countdown_buckets[resource_type],
                    countdown_buckets_to_refresh,
                    now,
                )
            )
            if updates:
                updates_by_type[resource_type] = updates
        return updates_by_type

    def _collect_bucket_updates(
        self,
        buckets: Dict[str, List[TrackedItem]],
        buckets_to_refresh: list[str],
        now: datetime,
    ) -> Generator[tuple[str, str, datetime], None, None]:
        for bucket_name in buckets_to_refresh:
            for item in buckets.get(bucket_name, []):
                yield (item.uid, item.field, item.timestamp)
