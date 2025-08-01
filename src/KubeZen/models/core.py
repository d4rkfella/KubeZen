from abc import abstractmethod
from KubeZen.models.base import (
    UIRow,
    CATEGORIES,
    core_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
    ABC,
)
from rich.text import Text
from rich.markup import escape
from kubernetes_asyncio.client import V1ContainerStatus
from KubeZen.utils import sanitize_timestamp_str


class BaseCoreV1Row(UIRow, ABC):
    """Base class for Core V1 API resources."""

    api_info: ClassVar[ApiInfo] = core_v1_api

    @abstractmethod
    def __init__(self, raw: UIRow):
        super().__init__(raw=raw)


@dataclass(frozen=True)
class NodeRow(BaseCoreV1Row):
    """A simple dataclass to hold resource information."""

    kind: ClassVar[str] = "Node"
    plural: ClassVar[str] = "nodes"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Nodes"
    category: ClassVar[str] = CATEGORIES["Nodes"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    conditions: Text = column_field(label="Conditions", width=20)
    age: str = column_field(label="Age", width=10, is_age=True)
    version: str = column_field(label="Version", width=10)
    kernel: str = column_field(label="Kernel", width=10)
    os: str = column_field(label="OS", width=10)
    architecture: str = column_field(label="Architecture", width=10)
    roles: str = column_field(label="Roles", width=10)

    def __init__(self, raw: Any):
        """Initialize the node row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "conditions", self._format_conditions())
        object.__setattr__(self, "version", self.raw.status.node_info.kubelet_version)
        object.__setattr__(self, "kernel", self.raw.status.node_info.kernel_version)
        object.__setattr__(self, "os", self.raw.status.node_info.os_image)
        object.__setattr__(self, "architecture", self.raw.status.node_info.architecture)
        object.__setattr__(self, "roles", self._node_roles())

    def _format_conditions(self) -> Text:
        if not self.raw.status.conditions:
            return Text("Unknown", style="yellow")

        status_parts = []

        if self.raw.spec.unschedulable:
            status_parts.append(Text("SchedulingDisabled", style="orange"))

        base_status_str = "Unknown"
        for condition in self.raw.status.conditions:
            if condition.type == "Ready":
                status = condition.status
                if status == "True":
                    base_status_str = "Ready"
                else:
                    base_status_str = condition.get("reason", "NotReady")
                break

        if base_status_str == "Ready":
            base_status_text = Text(base_status_str, style="green")
        else:
            base_status_text = Text(base_status_str, style="red")

        status_parts.append(base_status_text)

        final_text = Text()
        for i, part in enumerate(status_parts):
            final_text.append(part)
            if i < len(status_parts) - 1:
                final_text.append(", ")

        return final_text

    def _node_roles(self) -> str:
        """Extracts the roles from a node's labels."""
        if not self.raw.metadata.labels:
            return "<none>"

        labels = self.raw.metadata.labels
        role_prefix = "node-role.kubernetes.io/"

        roles = {
            key.split(role_prefix)[1] for key in labels if key.startswith(role_prefix)
        }

        if "kubernetes.io/role" in labels and labels["kubernetes.io/role"]:
            roles.add(labels["kubernetes.io/role"])

        if not roles:
            return "<none>"

        return ",".join(sorted(list(roles)))


@dataclass(frozen=True)
class NamespaceRow(BaseCoreV1Row):
    """Represents a Namespace for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Namespace"
    plural: ClassVar[str] = "namespaces"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Namespaces"
    category: ClassVar[str] = CATEGORIES["Namespaces"].name
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    status: str = column_field(label="Status", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the namespace row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "status", self.raw.status.phase)


@dataclass(frozen=True)
class EventRow(BaseCoreV1Row):
    """Represents an Event for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Event"
    plural: ClassVar[str] = "events"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Events"
    category: ClassVar[str] = CATEGORIES["Events"].name
    index: ClassVar[int] = 0
    omit_name_column: ClassVar[bool] = True

    # --- Instance Fields ---
    type: str = column_field(label="Type", width=10)
    reason: str = column_field(label="Reason", width=20)
    involved_object: str = column_field(label="Involved Object", width=30)
    source: str = column_field(label="Source", width=20)
    count: int = column_field(label="Count", width=5)
    age: str = column_field(label="Age", width=10, is_age=True)
    last_seen: str = column_field(label="Last Seen", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the event row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "type", self.raw.type)
        object.__setattr__(self, "reason", self.raw.reason)
        object.__setattr__(
            self,
            "involved_object",
            (
                f"{self.raw.involved_object.kind}: {self.raw.involved_object.name}"
                if self.raw.involved_object
                else "<unknown>"
            ),
        )
        object.__setattr__(
            self,
            "source",
            self.raw.source.component if self.raw.source.component else "<unknown>",
        )
        object.__setattr__(self, "count", self.raw.count)
        object.__setattr__(self, "last_seen", self.raw.last_timestamp)


@dataclass(frozen=True)
class ConfigMapRow(BaseCoreV1Row):
    """Represents a ConfigMap for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ConfigMap"
    plural: ClassVar[str] = "configmaps"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Config Maps"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the config map row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class SecretRow(BaseCoreV1Row):
    """Represents a Secret for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Secret"
    plural: ClassVar[str] = "secrets"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Secrets"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the secret row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class ServiceAccountRow(BaseCoreV1Row):
    """Represents a ServiceAccount for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ServiceAccount"
    plural: ClassVar[str] = "serviceaccounts"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Service Accounts"
    category: ClassVar[str] = CATEGORIES["Access Control"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the service account row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class ServiceRow(BaseCoreV1Row):
    """Represents a Service for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Service"
    plural: ClassVar[str] = "services"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Services"
    category: ClassVar[str] = CATEGORIES["Network"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    type: str = column_field(label="Type", width=10)
    cluster_ip: str = column_field(label="Cluster IP", width=10)
    external_ip: str = column_field(label="External IP", width=10)
    ports: str = column_field(label="Ports", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the service row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "type", self.raw.spec.type)
        object.__setattr__(self, "cluster_ip", self.raw.spec.cluster_ip)
        object.__setattr__(
            self,
            "external_ip",
            (
                self.raw.status.load_balancer.ingress[0].ip
                if self.raw.status.load_balancer.ingress
                else ""
            ),
        )
        object.__setattr__(
            self,
            "ports",
            ", ".join(f"{p.port}/{p.protocol}" for p in self.raw.spec.ports),
        )


@dataclass(frozen=True)
class ResourceQuotaRow(BaseCoreV1Row):
    """Represents a ResourceQuota for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ResourceQuota"
    plural: ClassVar[str] = "resourcequotas"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Resource Quotas"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the resource quota row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class PersistentVolumeRow(BaseCoreV1Row):
    """Represents a PersistentVolume for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "PersistentVolume"
    plural: ClassVar[str] = "persistentvolumes"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Persistent Volumes"
    category: ClassVar[str] = CATEGORIES["Storage"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    status: str = column_field(label="Status", width=10)
    capacity: str = column_field(label="Capacity", width=10)
    access_modes: str = column_field(label="Access Modes", width=10)
    storage_class: str = column_field(label="StorageClass", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)
    claim: str = column_field(label="Claim", width=20)

    def __init__(self, raw: Any):
        """Initialize the persistent volume row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "status", self.raw.status.phase)
        object.__setattr__(self, "capacity", self.raw.spec.capacity.get("storage", ""))
        object.__setattr__(self, "access_modes", ", ".join(self.raw.spec.access_modes))
        object.__setattr__(self, "storage_class", self.raw.spec.storage_class_name)
        object.__setattr__(self, "claim", self.raw.spec.claim_ref.name)


@dataclass(frozen=True)
class PersistentVolumeClaim(BaseCoreV1Row):
    """Represents a PersistentVolumeClaim for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "PersistentVolumeClaim"
    plural: ClassVar[str] = "persistentvolumeclaims"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Persistent Volume Claims"
    category: ClassVar[str] = CATEGORIES["Storage"].name
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    status: str = column_field(label="Status", width=10)
    volume: str = column_field(label="Volume", width=10)
    size: str = column_field(label="Size", width=10)
    access_modes: str = column_field(label="Access Modes", width=10)
    storage_class: str = column_field(label="StorageClass", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the persistent volume claim row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "status", self.raw.status.phase)
        object.__setattr__(self, "volume", self.raw.spec.volume_name)
        object.__setattr__(self, "size", self.raw.status.capacity.get("storage", ""))
        object.__setattr__(self, "access_modes", ", ".join(self.raw.spec.access_modes))
        object.__setattr__(self, "storage_class", self.raw.spec.storage_class_name)


@dataclass(frozen=True)
class LimitRangeRow(BaseCoreV1Row):
    """Represents a LimitRange for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "LimitRange"
    plural: ClassVar[str] = "limitranges"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Limit Ranges"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 3

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the limit range row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class Endpoint(BaseCoreV1Row):
    """Represents an Endpoint for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Endpoints"
    plural: ClassVar[str] = "endpoints"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Endpoints"
    category: ClassVar[str] = CATEGORIES["Network"].name
    index: ClassVar[int] = 4

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    endpoints: str = column_field(label="Endpoints", width=10)

    def __init__(self, raw: Any):
        """Initialize the endpoint row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "endpoints", self._format_endpoints())

    def _format_endpoints(self) -> str:
        """Formats the subsets of an Endpoint resource into a string."""
        if not self.raw.subsets:
            return ""

        formatted_endpoints = []
        for subset in self.raw.subsets:
            addresses = subset.addresses or []
            ports = subset.ports or []
            for address in addresses:
                for port in ports:
                    formatted_endpoints.append(f"{address.ip}:{port.port}")

        # Limit the output to a reasonable number of endpoints to avoid UI clutter
        display_limit = 3
        if len(formatted_endpoints) > display_limit:
            more_count = len(formatted_endpoints) - display_limit
            return (
                ", ".join(formatted_endpoints[:display_limit])
                + f", (+{more_count} more)"
            )

        return ", ".join(formatted_endpoints)


@dataclass(frozen=True)
class PodRow(BaseCoreV1Row):
    """A data class representing the view model for a Kubernetes Pod."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Pod"
    plural: ClassVar[str] = "pods"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Pods"
    category: ClassVar[str] = CATEGORIES["Workloads"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    ready: Text = column_field(label="Containers", width=8)
    restarts: int = column_field(label="Restarts", width=10)
    controlled_by: Text = column_field(label="Controlled By", width=8)
    cpu: str = column_field(label="CPU", width=10)
    memory: str = column_field(label="Memory", width=10)
    node: str = column_field(label="Node", width=10)
    age: str = column_field(label="Age", width=5, is_age=True)
    status: str = column_field(label="Status", width=10)

    def __init__(self, raw: UIRow):
        """Initialize the pod row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        # --- Standard Fields ---
        object.__setattr__(self, "status", self._get_status())
        object.__setattr__(self, "ready", self._format_pod_containers_status())
        object.__setattr__(self, "restarts", self._get_restarts())
        object.__setattr__(self, "node", self.raw.spec.node_name)
        object.__setattr__(self, "controlled_by", self._format_controlled_by_status())
        object.__setattr__(self, "cpu", "")
        object.__setattr__(self, "memory", "")

    def _get_restarts(self) -> int:
        """Calculates the total number of container restarts."""
        if not self.raw.status or not self.raw.status.container_statuses:
            return 0
        return sum(cs.restart_count for cs in self.raw.status.container_statuses)

    def _get_status(self) -> str:
        """
        Determines a detailed status for a pod by inspecting its state,
        including checking for termination, container statuses, and other conditions.
        """
        if not self.raw:
            return "Unknown"

        # 1. Check for deletion timestamp
        if self.raw.metadata and self.raw.metadata.deletion_timestamp:
            return "Terminating"

        status = self.raw.status
        if not status:
            return "Unknown"

        phase = str(status.phase or "Unknown")

        # 2. Pod-level abnormal status
        if status.reason:
            return str(status.reason)

        # 3. Check init container statuses
        init_container_statuses = status.init_container_statuses or []
        for c in init_container_statuses:
            if c.state and c.state.terminated and c.state.terminated.exit_code != 0:
                return str(f"Init:{c.state.terminated.reason or 'Error'}")
            if (
                c.state
                and c.state.waiting
                and c.state.waiting.reason
                and c.state.waiting.reason != "PodInitializing"
            ):
                return str(f"Init:{c.state.waiting.reason}")

        # 4. Check main container statuses
        container_statuses = status.container_statuses or []
        if not container_statuses:
            # If no container statuses, phase is the best we have
            return phase

        waiting_containers = []
        for c in container_statuses:
            if c.state and c.state.waiting and c.state.waiting.reason:
                waiting_containers.append(str(c.state.waiting.reason))

        if waiting_containers:
            # Prioritize critical waiting reasons
            for critical_reason in (
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "Error",
            ):
                if critical_reason in waiting_containers:
                    return critical_reason
            # Otherwise, return the first waiting reason found
            return waiting_containers[0]

        # 5. Fallback to phase if all containers seem okay
        # but the pod isn't 'Running' or 'Succeeded' yet.
        return phase

    def _format_pod_containers_status(self) -> Text:
        """Return a Text object of container status indicators for a pod."""
        if not self.raw or not self.raw.status:
            return Text("n/a")

        spec = self.raw.spec
        status = self.raw.status

        # Get container specs and statuses
        container_specs = spec.containers or []
        init_container_specs = spec.init_containers or []
        container_statuses = {s.name: s for s in (status.container_statuses or [])}
        init_container_statuses = {
            s.name: s for s in (status.init_container_statuses or [])
        }

        indicators = []
        for specs, statuses in [
            (container_specs, container_statuses),
            (init_container_specs, init_container_statuses),
        ]:
            for spec in specs:
                name = spec.name
                if not name:
                    continue
                container = statuses.get(name)
                if not container:
                    continue  # Should not happen
                indicator_str, tooltip_text = PodRow._get_container_indicator(container)
                indicator = Text.from_markup(indicator_str)
                indicator.apply_meta({"@tooltip": tooltip_text})
                indicators.append(indicator)

        if not indicators:
            return Text("n/a")
        return Text(" ").join(indicators)

    @staticmethod
    def _get_container_indicator(container: V1ContainerStatus) -> tuple[str, str]:
        """Helper function to get the status indicator and a rich Text tooltip for a container."""
        name = str(container.name or "Unknown")
        state = container.state
        ready = container.ready

        started_at = None
        if state.running:
            started_at = state.running.started_at
        elif state.terminated:
            started_at = state.terminated.started_at

        finished_at = None
        exit_code = None
        if state.terminated:
            finished_at = state.terminated.finished_at
            exit_code = state.terminated.exit_code

        # First line of tooltip, with the name escaped.
        line1_parts = [f"[bold]{escape(name)}[/bold]"]

        status_parts = []
        if state.running:
            status_parts.append("running")
            if ready:
                status_parts.append("ready")
        elif state.waiting:
            if state.waiting.reason:
                status_parts.append(str(state.waiting.reason))
        elif state.terminated:
            status_parts.append("terminated")
            if state.terminated.reason:
                status_parts.append(str(state.terminated.reason))

        if status_parts:
            status_str = ", ".join(status_parts)
            line1_parts.append(f" [dim]{status_str}[/dim]")

        line1 = "".join(line1_parts)

        lines = [line1]
        if started_at:
            lines.append(
                f"[dim]Started At {sanitize_timestamp_str(str(started_at))}[/dim]"
            )

        if finished_at:
            lines.append(
                f"[dim]Finished At {sanitize_timestamp_str(str(finished_at))}[/dim]"
            )

        if exit_code is not None:
            lines.append(f"[dim]Exit Code {exit_code}[/dim]")

        # Combine lines
        tooltip_content = "\n".join(lines)

        # Determine indicator
        indicator_str = ""
        if state.running:
            if ready:
                indicator_str = "[bold green]■[/]"  # Running and ready
            else:
                indicator_str = "[bold yellow]■[/]"  # Running but not ready
        elif state.waiting and state.waiting.reason in [
            "CrashLoopBackOff",
            "Error",
            "ImagePullBackOff",
        ]:
            indicator_str = "[bold red]■[/]"  # Error state
        elif state.waiting:
            indicator_str = "[bold yellow]■[/]"  # Waiting state
        elif state.terminated:
            indicator_str = "[dim]■[/]"  # Terminated state
        else:
            indicator_str = "[dim]□[/]"  # Not yet created/no status

        return indicator_str, tooltip_content

    def _format_controlled_by_status(self) -> Text | str:
        """
        Return a Text object with the owner's kind, and a tooltip with the owner's name.
        """
        owner_references = self.raw.metadata.owner_references
        if not owner_references:
            return ""  # Return an empty string or "n/a" if there's no owner

        # Get the kind and name from the first owner
        immediate_owner = owner_references[0]
        owner_kind = immediate_owner.kind
        owner_name = immediate_owner.name

        # Create the Text object for display
        # The main text will be just the kind (e.g., "ReplicaSet")
        display_text = Text(owner_kind)

        # Create the content for the tooltip
        # Use rich markup for formatting, and escape the name to be safe
        tooltip_content = f"{escape(owner_name)}"

        # Apply the tooltip to the Text object
        display_text.apply_meta({"@tooltip": tooltip_content})

        return display_text
