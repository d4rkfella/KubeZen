from __future__ import annotations

import logging
from abc import abstractmethod, ABCMeta, ABC
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, ClassVar, Optional, Dict
from functools import lru_cache

from jsonpath_ng import JSONPath
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse as jsonpath_parse

import ciso8601


log = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _get_cached_jsonpath_expression(path: str) -> JSONPath:
    """Compiles and caches a JSONPath expression string."""
    log.debug(f"[JSONPath] Compiling and caching expression: '{path}'")
    return jsonpath_parse(path)


class ModelMeta(ABCMeta):
    """
    A metaclass that enforces the presence of required class variables
    on any concrete (non-abstract) subclass of UIRow.
    """

    def __new__(mcs, name, bases, dct) -> ModelMeta:
        cls = super().__new__(mcs, name, bases, dct)

        # Do not run checks on abstract base classes.
        # We identify them by checking for the presence of abc.ABC in their bases
        # or by our convention of starting their names with '_' or 'Base'.
        is_abstract_base = any(b is ABC for b in bases)
        if is_abstract_base:
            return cls

        # List of attributes that every concrete model must define
        required_attrs = [
            "kind",
            "plural",
            "display_name",
            "namespaced",
            "category",
            "index",
            "api_info",
        ]

        for attr in required_attrs:
            if not hasattr(cls, attr):
                raise TypeError(
                    f"Class '{name}' is missing required class variable '{attr}'. "
                    f"All KubeZen models must define these attributes."
                )
        return cls


@dataclass(frozen=True)
class Category:
    """A simple dataclass to hold category information."""

    name: str
    icon: str
    index: int


_CATEGORIES_LIST = [
    Category(name="Nodes", icon="🗄 ", index=0),
    Category(name="Workloads", icon="🚢", index=1),
    Category(name="Config", icon="⚙ ", index=2),
    Category(name="Network", icon="🌐", index=3),
    Category(name="Storage", icon="💾", index=4),
    Category(name="Namespaces", icon="🏷 ", index=5),
    Category(name="Helm", icon="☸️", index=6),
    Category(name="Access Control", icon="🛡 ", index=7),
    Category(name="Events", icon="🕘", index=8),
    Category(name="Custom Resources", icon="🧩", index=9),
]

CATEGORIES: Dict[str, Category] = {cat.name: cat for cat in _CATEGORIES_LIST}


@dataclass(frozen=True)
class ApiInfo:
    """A dataclass to hold API client information."""

    client_name: str
    group: str
    version: str


# Core APIs
core_v1_api = ApiInfo(
    client_name="CoreV1Api",
    group="",
    version="v1",
)
apps_v1_api = ApiInfo(
    client_name="AppsV1Api",
    group="apps",
    version="v1",
)
batch_v1_api = ApiInfo(
    client_name="BatchV1Api",
    group="batch",
    version="v1",
)
custom_objects_api = ApiInfo(
    client_name="CustomObjectsApi",
    group="",
    version="",
)
autoscaling_v1_api = ApiInfo(
    client_name="AutoscalingV1Api",
    group="autoscaling",
    version="v1",
)
policy_v1_api = ApiInfo(
    client_name="PolicyV1Api",
    group="policy",
    version="v1",
)
scheduling_v1_api = ApiInfo(
    client_name="SchedulingV1Api",
    group="scheduling",
    version="v1",
)
node_v1_api = ApiInfo(
    client_name="NodeV1Api",
    group="",
    version="v1",
)
coordination_v1_api = ApiInfo(
    client_name="CoordinationV1Api",
    group="coordination",
    version="v1",
)
admissionregistration_v1_api: ApiInfo = ApiInfo(
    client_name="AdmissionregistrationV1Api",
    group="admissionregistration",
    version="v1",
)
storage_v1_api = ApiInfo(
    client_name="StorageV1Api",
    group="storage",
    version="v1",
)
networking_v1_api = ApiInfo(
    client_name="NetworkingV1Api",
    group="networking",
    version="v1",
)
rbac_authorization_v1_api = ApiInfo(
    client_name="RbacAuthorizationV1Api",
    group="rbac",
    version="v1",
)
apiextensions_v1_api = ApiInfo(
    client_name="ApiextensionsV1Api",
    group="apiextensions",
    version="v1",
)

ALL_APIS = {
    api.client_name: api
    for api in [
        core_v1_api,
        apps_v1_api,
        batch_v1_api,
        custom_objects_api,
        autoscaling_v1_api,
        policy_v1_api,
        scheduling_v1_api,
        node_v1_api,
        coordination_v1_api,
        admissionregistration_v1_api,
        storage_v1_api,
        networking_v1_api,
        rbac_authorization_v1_api,
        apiextensions_v1_api,
    ]
}


def column_field(
    *,
    label: str,
    width: int | None = None,
    is_age: bool = False,
    is_countdown: bool = False,
    index: int | None = None,
) -> Any:
    """Create a field with column metadata cleanly."""
    return field(  # pylint: disable=invalid-field-call
        metadata={
            "column": {
                "label": label,
                "width": width,
                "is_age": is_age,
                "is_countdown": is_countdown,
                "index": index,
            }
        },
        init=False,
    )


@dataclass(frozen=True)
class UIRow(ABC, metaclass=ModelMeta):
    """
    The most generic abstract base class for any row that can be displayed in the UI.
    It cannot be instantiated directly.
    """

    # --- Subclasses must define API Metadata (Class-level) ---
    api_info: ClassVar[ApiInfo]
    kind: ClassVar[str]
    plural: ClassVar[str]
    display_name: ClassVar[str]
    namespaced: ClassVar[bool]
    category: ClassVar[str]
    index: ClassVar[int]
    omit_name_column: ClassVar[bool] = False

    raw: Any = field(repr=False, compare=False)
    uid: str = field(init=False, repr=False, compare=False)
    namespace: str | None = field(default=None, init=False)
    name: str = field(
        init=False,
        metadata={
            "column": {
                "label": "Name",
                "index": 0,
                "width": 25,
            }
        },
    )

    def __init_subclass__(cls, **kwargs):
        """
        Dynamically adds the 'namespace' field to subclasses that are marked as namespaced.
        This avoids having a namespace column for non-namespaced resources like Nodes.
        """
        super().__init_subclass__(**kwargs)
        if getattr(cls, "namespaced", False):
            # Define the field with its metadata.
            namespace_field = field(
                init=False,
                metadata={
                    "column": {
                        "label": "Namespace",
                        "index": 1,
                        "width": 15,
                    }
                },
            )
            # Add it to the class annotations and the dataclass fields.
            cls.__annotations__["namespace"] = Optional[str]
            # The type hint here is for mypy, the actual field object is what matters.
            setattr(cls, "namespace", namespace_field)

            # Rebuild the dataclass fields to include the new one
            cls.__dataclass_fields__ = {
                **getattr(cls, "__dataclass_fields__", {}),
                "namespace": namespace_field,
            }

    @abstractmethod
    def __init__(self, raw: Any) -> None:
        """Initialize the row with data from the raw Kubernetes resource."""
        object.__setattr__(self, "raw", raw)

        metadata = raw.get("metadata", {}) if isinstance(raw, dict) else raw.metadata
        object.__setattr__(
            self,
            "uid",
            metadata.get("uid") if isinstance(metadata, dict) else metadata.uid,
        )
        object.__setattr__(
            self,
            "name",
            metadata.get("name") if isinstance(metadata, dict) else metadata.name,
        )

        # Always set the namespace attribute for internal consistency.
        # The column will only be shown for namespaced resources via __init_subclass__.
        namespace = (
            metadata.get("namespace")
            if isinstance(metadata, dict)
            else getattr(metadata, "namespace", None)
        )
        object.__setattr__(self, "namespace", namespace)

        # Always set the age attribute. Subclasses can add an 'age' column field if needed.
        age = (
            metadata.get("creationTimestamp")
            if isinstance(metadata, dict)
            else getattr(metadata, "creation_timestamp", None)
        )
        if isinstance(age, str):
            age = UIRow.to_datetime(age)
        object.__setattr__(self, "age", age)

    def _resolve_path(self, obj: Any, path: str) -> Any:
        """
        Resolves a path on an object. Uses a custom resolver for simple dot-notation
        paths (faster for dicts/objects) and jsonpath-ng for complex ones.
        """
        if "[" not in path and "*" not in path:
            # Fast path
            current = obj
            for part in path.split("."):
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    current = getattr(current, part, None)
                if current is None:
                    log.debug(f"[SimplePath] Failed at '{part}' in '{path}' — got None")
                    return None
            log.debug(f"[SimplePath] Resolved '{path}' → {current!r}")
            return current

        # Complex path using jsonpath-ng
        log.debug(f"[JSONPath] Complex lookup for path: '{path}'")
        try:
            expression = _get_cached_jsonpath_expression(path)

            matches = expression.find(obj)
            if matches:
                result = matches[0].value
                log.debug(f"[JSONPath] Resolved '{path}' → {result!r}")
                return result

            log.debug(f"[JSONPath] No match for path: '{path}'")
            return None
        except (JsonPathParserError, Exception) as e:
            log.debug(f"[JSONPath] Failed to resolve '{path}': {e}")
            return None

    @classmethod
    @lru_cache(maxsize=32)
    def get_columns(cls) -> list[dict[str, Any]]:
        """
        Inspects the dataclass fields to find columns and their metadata.
        It respects the 'index' key for explicit ordering. Columns without an
        index are placed after explicitly indexed columns. A high index (>=999)
        is treated as a signal to place the column at the very end.
        """
        start_columns = []
        middle_columns = []
        end_columns = []

        # A threshold to separate 'end' columns from 'start' columns.
        end_index_threshold = 999

        for f in fields(cls):
            if "column" in f.metadata:
                column_meta = f.metadata["column"].copy()
                if cls.omit_name_column and f.name == "name":
                    continue
                column_meta["key"] = f.name

                index = column_meta.get("index")
                if index is None:
                    middle_columns.append(column_meta)
                elif index >= end_index_threshold:
                    end_columns.append(column_meta)
                else:
                    start_columns.append(column_meta)

        # Sort the start and end groups by their explicit index.
        start_columns.sort(key=lambda c: c["index"])
        end_columns.sort(key=lambda c: c["index"])

        return start_columns + middle_columns + end_columns

    @classmethod
    @lru_cache(maxsize=32)
    def get_column_keys(cls) -> list[str]:
        """Get the list of column keys for the model."""
        columns = cls.get_columns()
        return [c["key"] for c in columns] if columns else []

    @classmethod
    @lru_cache(maxsize=32)
    def get_time_tracked_fields(cls) -> dict[Any, str]:
        """Get the list of time-tracked fields for the model."""
        columns = cls.get_columns()
        return {
            c["key"]: "countdown" if c.get("is_countdown") else "age"
            for c in columns
            if c.get("is_age") or c.get("is_countdown")
        }

    @staticmethod
    @lru_cache(maxsize=1024)
    def to_datetime(timestamp: Any) -> datetime:
        return ciso8601.parse_datetime(timestamp)

    @staticmethod
    def format_datetime_string(ts_str: str | None) -> str:
        if not ts_str:
            return "N/A"
        dt_object = UIRow.to_datetime(ts_str)
        if not dt_object:
            return str(ts_str)  # Return original string if parsing fails
        return dt_object.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def format_age(creation_ts: datetime, now: datetime) -> str:
        age_delta = now - creation_ts
        total_seconds = int(age_delta.total_seconds())

        if total_seconds < 0:
            return "0s"

        # Compute all units
        total_minutes, seconds = divmod(total_seconds, 60)
        total_hours, minutes = divmod(total_minutes, 60)
        total_days, hours = divmod(total_hours, 24)

        if total_minutes < 2:
            return f"{total_seconds}s"
        elif total_minutes < 10:
            return f"{total_minutes}m{seconds:02d}s"
        elif total_minutes < 60:
            return f"{total_minutes}m"
        elif total_hours < 10:
            return f"{total_hours}h{minutes}m"
        elif total_hours < 24:
            return f"{total_hours}h"
        elif total_days < 10:
            return f"{total_days}d{hours}h"
        else:
            return f"{total_days}d"

    @staticmethod
    def format_countdown(future_ts: datetime, now: datetime) -> str:
        """Formats a future datetime into a countdown string like 'in 5m'."""
        delta = future_ts - now
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "now"

        total_minutes, seconds = divmod(total_seconds, 60)
        total_hours, minutes = divmod(total_minutes, 60)
        days, hours = divmod(total_hours, 24)

        if days > 0:
            return f"in {days}d{hours}h"
        elif total_hours > 0:
            return f"in {total_hours}h{minutes}m"
        elif total_minutes > 0:
            return f"in {total_minutes}m{seconds:02d}s"
        else:
            return f"in {seconds}s"
