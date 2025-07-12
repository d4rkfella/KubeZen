from abc import abstractmethod
from .base import (
    dataclass,
    Any,
    ClassVar,
    column_field,
    UIRow,
    ApiInfo,
    apps_v1_api,
    ABC,
    CATEGORIES,
)
from kubernetes_asyncio.client import V1Deployment
from typing import cast

@dataclass(frozen=True)
class BaseAppsV1Row(UIRow, ABC):
    """Base class for Apps V1 API resources."""

    api_info: ClassVar[ApiInfo] = apps_v1_api
    category: ClassVar[str] = CATEGORIES["Workloads"].name

    age: str = column_field(label="Age", width=10, is_age=True, index=999)

    @abstractmethod
    def __init__(self, raw: Any) -> None:
        super().__init__(raw=raw)


@dataclass(frozen=True)
class DeploymentRow(BaseAppsV1Row):
    """Represents a Deployment for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Deployment"
    plural: ClassVar[str] = "deployments"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Deployments"
    resource_name_snake: ClassVar[str] = "deployment"
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    ready: str = column_field(label="Ready", width=10)
    up_to_date: str = column_field(label="Up-to-date", width=10)
    available: str = column_field(label="Available", width=10)
    replicas: str = column_field(label="Replicas", width=10)

    def __init__(self, raw: V1Deployment):
        """Initialize the deployment row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(
            self,
            "ready",
            (
                f"{self.raw.status.ready_replicas}/{self.raw.spec.replicas}"
                if self.raw.spec.replicas
                else "0/0"
            ),
        )
        object.__setattr__(
            self,
            "up_to_date",
            (
                self.raw.status.updated_replicas
                if self.raw.status.updated_replicas
                else "0"
            ),
        )
        object.__setattr__(
            self,
            "available",
            (
                self.raw.status.available_replicas
                if self.raw.status.available_replicas
                else "0"
            ),
        )
        object.__setattr__(
            self, "replicas", self.raw.spec.replicas if self.raw.spec.replicas else "0"
        )


@dataclass(frozen=True)
class DaemonSetRow(BaseAppsV1Row):
    """Represents a DaemonSet for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "DaemonSet"
    plural: ClassVar[str] = "daemonsets"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Daemon Sets"
    list_method_name: ClassVar[str] = "list_daemon_set_for_all_namespaces"
    delete_method_name: ClassVar[str] = "delete_namespaced_daemon_set"
    patch_method_name: ClassVar[str] = "patch_namespaced_daemon_set"
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    desired: str = column_field(label="Desired", width=10)
    current: str = column_field(label="Current", width=10)
    ready: str = column_field(label="Ready", width=10)
    up_to_date: str = column_field(label="Up-to-date", width=10)
    available: str = column_field(label="Available", width=10)
    node_selector: str = column_field(label="Node Selector", width=10)

    def __init__(self, raw: Any):
        """Initialize the daemon set row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "desired", self.raw.status.desired_number_scheduled)
        object.__setattr__(self, "current", self.raw.status.current_number_scheduled)
        object.__setattr__(self, "ready", self.raw.status.number_ready)
        object.__setattr__(self, "up_to_date", self.raw.status.updated_number_scheduled)
        object.__setattr__(self, "available", self.raw.status.number_available)
        node_selector_dict = (
            getattr(self.raw.spec.template.spec, "node_selector", None) or {}
        )
        object.__setattr__(
            self,
            "node_selector",
            ", ".join(f"{key}={value}" for key, value in node_selector_dict.items()),
        )


@dataclass(frozen=True)
class ReplicaSetRow(BaseAppsV1Row):
    """Represents a ReplicaSet for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ReplicaSet"
    plural: ClassVar[str] = "replicasets"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Replica Sets"
    list_method_name: ClassVar[str] = "list_replica_set_for_all_namespaces"
    delete_method_name: ClassVar[str] = "delete_namespaced_replica_set"
    patch_method_name: ClassVar[str] = "patch_namespaced_replica_set"
    index: ClassVar[int] = 4

    # --- Instance Fields ---
    ready: str = column_field(label="Ready", width=10)
    replicas: str = column_field(label="Replicas", width=10)

    def __init__(self, raw: Any):
        """Initialize the replica set row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(
            self,
            "ready",
            f"{self.raw.status.ready_replicas or 0}/{self.raw.spec.replicas or 0}",
        )
        object.__setattr__(
            self, "replicas", self.raw.spec.replicas if self.raw.spec.replicas else "0"
        )


@dataclass(frozen=True)
class StatefulSetRow(BaseAppsV1Row):
    """Represents a StatefulSet for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "StatefulSet"
    plural: ClassVar[str] = "statefulsets"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Stateful Sets"
    list_method_name: ClassVar[str] = "list_stateful_set_for_all_namespaces"
    delete_method_name: ClassVar[str] = "delete_namespaced_stateful_set"
    patch_method_name: ClassVar[str] = "patch_namespaced_stateful_set"
    index: ClassVar[int] = 5

    # --- Instance Fields ---
    ready: str = column_field(label="Ready", width=10)

    def __init__(self, raw: Any):
        """Initialize the stateful set row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(
            self,
            "ready",
            (
                f"{self.raw.status.ready_replicas}/{self.raw.status.replicas}"
                if self.raw.status.replicas
                else "0/0"
            ),
        )
