from typing import Callable, Any, Literal, TypedDict
from ..utils import format_age


class PortInfo(TypedDict):
    """Defines the structure for port information."""

    name: str
    number: str
    protocol: str


class ResourceColumn(TypedDict):
    """Defines the structure for a column in the resource table."""

    label: str
    ratio: int
    min_width: int
    key: str


class ResourceMeta(TypedDict):
    """Defines the metadata structure for a single Kubernetes resource type."""

    api_client_attr: Literal["core_v1", "apps_v1"]
    list_all_method: str
    list_namespaced_method: str | None
    read_method: str
    delete_method: str
    patch_method: str
    is_namespaced: bool
    kind: str
    api_version: str
    emoji: str
    display_name: str
    columns: list[ResourceColumn]
    formatter: Callable[[dict[str, Any]], list[Any]]
    port_forward_provider: Callable[[dict[str, Any]], list[PortInfo]] | None


# --- Port Forwarding Providers ---
# These functions extract port information from different resource types.


def _get_pod_ports(pod: dict[str, Any]) -> list[PortInfo]:
    """Extracts port information from a Pod resource."""
    ports_to_return: list[PortInfo] = []
    spec = pod.get("spec", {})
    all_containers = spec.get("containers", []) + spec.get("initContainers", [])
    for container in all_containers:
        if container.get("ports"):
            for port in container.get("ports", []):
                port_number = port.get("containerPort") or port.get("container_port")
                if port_number:
                    ports_to_return.append(
                        {
                            "name": port.get("name", ""),
                            "number": str(port_number),
                            "protocol": port.get("protocol", "TCP"),
                        }
                    )
    return ports_to_return


def _get_service_ports(service: dict[str, Any]) -> list[PortInfo]:
    """Extracts port information from a Service resource."""
    ports_to_return: list[PortInfo] = []
    spec = service.get("spec", {})
    if spec.get("ports"):
        for port in spec.get("ports", []):
            port_number = port.get("port")
            if port_number:
                ports_to_return.append(
                    {
                        "name": port.get("name", ""),
                        "number": str(port_number),
                        "protocol": port.get("protocol", "TCP"),
                    }
                )
    return ports_to_return


# --- Formatter Functions ---
# These functions contain the specific logic for turning a Kubernetes resource
# object into a list of values for a table row.


def _format_pod_row(pod: dict) -> list:
    """Formatter for Pod resources."""
    ready_count = 0
    total_count = 0
    restarts = 0
    if pod.get("status", {}).get("containerStatuses"):
        for status in pod["status"]["containerStatuses"]:
            if status.get("ready"):
                ready_count += 1
            restarts += status.get("restartCount", 0)
        total_count = len(pod["status"]["containerStatuses"])
    ready_str = f"{ready_count}/{total_count}"
    return [
        pod["metadata"]["name"],
        pod["status"]["phase"],
        ready_str,
        str(restarts),
        format_age(pod.get("metadata", {})),
    ]


def _format_namespace_row(namespace: dict) -> list:
    """Formatter for Namespace resources."""
    return [
        namespace["metadata"]["name"],
        namespace["status"]["phase"],
        format_age(namespace.get("metadata", {})),
    ]


def _format_service_row(service: dict) -> list:
    """Formatter for Service resources."""
    spec = service.get("spec", {})
    ports = spec.get("ports", [])
    port_str = ", ".join(
        [
            f"{p.get('port')}:{p.get('nodePort')}/{p.get('protocol')}"
            for p in ports
            if p.get("nodePort")
        ]
        + [
            f"{p.get('port')}/{p.get('protocol')}"
            for p in ports
            if not p.get("nodePort")
        ]
    )
    return [
        service["metadata"]["name"],
        spec.get("type", "N/A"),
        spec.get("clusterIP", "N/A"),
        port_str,
        format_age(service.get("metadata", {})),
    ]


def _format_deployment_row(deployment: dict) -> list:
    """Formatter for Deployment resources."""
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    ready_replicas = status.get("readyReplicas", 0)
    total_replicas = spec.get("replicas", 0)
    return [
        deployment["metadata"]["name"],
        f"{ready_replicas}/{total_replicas}",
        str(status.get("updatedReplicas", 0)),
        str(status.get("availableReplicas", 0)),
        format_age(deployment.get("metadata", {})),
    ]


def _format_daemonset_row(daemonset: dict) -> list:
    """Formatter for DaemonSet resources."""
    status = daemonset.get("status", {})
    return [
        daemonset["metadata"]["name"],
        str(status.get("desiredNumberScheduled", 0)),
        str(status.get("currentNumberScheduled", 0)),
        str(status.get("numberReady", 0)),
        str(status.get("updatedNumberScheduled", 0)),
        str(status.get("numberAvailable", 0)),
        format_age(daemonset.get("metadata", {})),
    ]


def _format_statefulset_row(statefulset: dict) -> list:
    """Formatter for StatefulSet resources."""
    spec = statefulset.get("spec", {})
    status = statefulset.get("status", {})
    return [
        statefulset["metadata"]["name"],
        f"{status.get('readyReplicas', 0)}/{spec.get('replicas', 0)}",
        format_age(statefulset.get("metadata", {})),
    ]


def _format_pvc_row(pvc: dict) -> list:
    """Formatter for PersistentVolumeClaim resources."""
    spec = pvc.get("spec", {})
    status = pvc.get("status", {})
    access_modes = ", ".join(spec.get("accessModes", []))
    return [
        pvc["metadata"]["name"],
        status.get("phase", "N/A"),
        spec.get("volumeName", ""),
        status.get("capacity", {}).get("storage", "N/A"),
        access_modes,
        format_age(pvc.get("metadata", {})),
    ]


# This file defines the central, unified registry for all Kubernetes resource
# metadata used throughout the application. It is the single source of truth.

RESOURCE_REGISTRY: dict[str, ResourceMeta] = {
    "pods": {
        "api_client_attr": "core_v1",
        "list_all_method": "list_pod_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_pod",
        "read_method": "read_namespaced_pod",
        "delete_method": "delete_namespaced_pod",
        "patch_method": "patch_namespaced_pod",
        "is_namespaced": True,
        "kind": "Pod",
        "api_version": "v1",
        "emoji": "📦",
        "display_name": "Pods",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 4, "min_width": 20},
            {"label": "Status", "key": "Status", "ratio": 1, "min_width": 10},
            {"label": "Ready", "key": "Ready", "ratio": 1, "min_width": 8},
            {"label": "Restarts", "key": "Restarts", "ratio": 1, "min_width": 10},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_pod_row,
        "port_forward_provider": _get_pod_ports,
    },
    "namespaces": {
        "api_client_attr": "core_v1",
        "list_all_method": "list_namespace",
        "list_namespaced_method": None,
        "read_method": "read_namespace",
        "delete_method": "delete_namespace",
        "patch_method": "patch_namespace",
        "is_namespaced": False,
        "kind": "Namespace",
        "api_version": "v1",
        "emoji": "🌐",
        "display_name": "Namespaces",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 3, "min_width": 20},
            {"label": "Status", "key": "Status", "ratio": 1, "min_width": 10},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_namespace_row,
        "port_forward_provider": None,
    },
    "services": {
        "api_client_attr": "core_v1",
        "list_all_method": "list_service_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_service",
        "read_method": "read_namespaced_service",
        "delete_method": "delete_namespaced_service",
        "patch_method": "patch_namespaced_service",
        "is_namespaced": True,
        "kind": "Service",
        "api_version": "v1",
        "emoji": "🔧",
        "display_name": "Services",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 3, "min_width": 20},
            {"label": "Type", "key": "Type", "ratio": 1, "min_width": 8},
            {"label": "Cluster IP", "key": "ClusterIP", "ratio": 2, "min_width": 15},
            {"label": "Ports", "key": "Ports", "ratio": 2, "min_width": 10},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_service_row,
        "port_forward_provider": _get_service_ports,
    },
    "deployments": {
        "api_client_attr": "apps_v1",
        "list_all_method": "list_deployment_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_deployment",
        "read_method": "read_namespaced_deployment",
        "delete_method": "delete_namespaced_deployment",
        "patch_method": "patch_namespaced_deployment",
        "is_namespaced": True,
        "kind": "Deployment",
        "api_version": "apps/v1",
        "emoji": "🚀",
        "display_name": "Deployments",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 3, "min_width": 20},
            {"label": "Ready", "key": "Ready", "ratio": 1, "min_width": 8},
            {"label": "Up-to-date", "key": "UpToDate", "ratio": 1, "min_width": 12},
            {"label": "Available", "key": "Available", "ratio": 1, "min_width": 12},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_deployment_row,
        "port_forward_provider": None,
    },
    "daemonsets": {
        "api_client_attr": "apps_v1",
        "list_all_method": "list_daemon_set_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_daemon_set",
        "read_method": "read_namespaced_daemon_set",
        "delete_method": "delete_namespaced_daemon_set",
        "patch_method": "patch_namespaced_daemon_set",
        "is_namespaced": True,
        "kind": "DaemonSet",
        "api_version": "apps/v1",
        "emoji": "😈",
        "display_name": "DaemonSets",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 3, "min_width": 20},
            {"label": "Desired", "key": "Desired", "ratio": 1, "min_width": 10},
            {"label": "Current", "key": "Current", "ratio": 1, "min_width": 10},
            {"label": "Ready", "key": "Ready", "ratio": 1, "min_width": 8},
            {"label": "Up-to-date", "key": "UpToDate", "ratio": 1, "min_width": 12},
            {"label": "Available", "key": "Available", "ratio": 1, "min_width": 12},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_daemonset_row,
        "port_forward_provider": None,
    },
    "statefulsets": {
        "api_client_attr": "apps_v1",
        "list_all_method": "list_stateful_set_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_stateful_set",
        "read_method": "read_namespaced_stateful_set",
        "delete_method": "delete_namespaced_stateful_set",
        "patch_method": "patch_namespaced_stateful_set",
        "is_namespaced": True,
        "kind": "StatefulSet",
        "api_version": "apps/v1",
        "emoji": "🧱",
        "display_name": "StatefulSets",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 4, "min_width": 20},
            {"label": "Ready", "key": "Ready", "ratio": 1, "min_width": 8},
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_statefulset_row,
        "port_forward_provider": None,
    },
    "pvcs": {
        "api_client_attr": "core_v1",
        "list_all_method": "list_persistent_volume_claim_for_all_namespaces",
        "list_namespaced_method": "list_namespaced_persistent_volume_claim",
        "read_method": "read_namespaced_persistent_volume_claim",
        "delete_method": "delete_namespaced_persistent_volume_claim",
        "patch_method": "patch_namespaced_persistent_volume_claim",
        "is_namespaced": True,
        "kind": "PersistentVolumeClaim",
        "api_version": "v1",
        "emoji": "💾",
        "display_name": "PersistentVolumeClaims",
        "columns": [
            {"label": "Name", "key": "Name", "ratio": 3, "min_width": 20},
            {"label": "Status", "key": "Status", "ratio": 1, "min_width": 10},
            {"label": "Volume", "key": "Volume", "ratio": 1, "min_width": 10},
            {"label": "Capacity", "key": "Capacity", "ratio": 1, "min_width": 10},
            {
                "label": "Access Modes",
                "key": "AccessModes",
                "ratio": 1,
                "min_width": 15,
            },
            {"label": "Age", "key": "Age", "ratio": 1, "min_width": 8},
        ],
        "formatter": _format_pvc_row,
        "port_forward_provider": None,
    },
}

# The explicit list of keys from the registry that represent a resource type that
# can be selected from the main resource list.
VIEWABLE_RESOURCE_TYPES = sorted(
    [
        "pods",
        "services",
        "deployments",
        "daemonsets",
        "statefulsets",
        "pvcs",
    ]
)
