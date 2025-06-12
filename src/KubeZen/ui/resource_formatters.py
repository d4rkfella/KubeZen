from __future__ import annotations
from typing import Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
from datetime import datetime, timezone


def get_creation_timestamp(resource: Dict[str, Any]) -> Optional[Any]:
    """
    Gets the creation timestamp from a resource, checking for both
    'creationTimestamp' (from API) and 'creation_timestamp' (from watches).
    """
    metadata = resource.get("metadata", {})
    return metadata.get("creationTimestamp") or metadata.get("creation_timestamp")


def calculate_age(creation_timestamp: Optional[Any]) -> str:
    """Calculates the age of a resource from its creation timestamp."""
    if not creation_timestamp:
        return "Unknown"

    try:
        created = None
        if isinstance(creation_timestamp, str):
            created = datetime.fromisoformat(creation_timestamp.replace("Z", "+00:00"))
        elif isinstance(creation_timestamp, datetime):
            if creation_timestamp.tzinfo is None:
                created = creation_timestamp.replace(tzinfo=timezone.utc)
            else:
                created = creation_timestamp

        if created:
            now = datetime.now(timezone.utc)
            age = now - created
            if age.days > 0:
                return f"{age.days}d"
            elif age.seconds >= 3600:
                return f"{age.seconds // 3600}h"
            elif age.seconds >= 60:
                return f"{age.seconds // 60}m"
            else:
                return f"{age.seconds}s"
        else:
            return "Unknown"
    except (ValueError, TypeError):
        return "Unknown"


def format_resource_list_line(
    resource: Dict[str, Any],
    status_formatter: Callable[[Dict[str, Any]], str],
    is_all_namespaces: bool,
) -> str:
    """
    Creates the final display string for a resource in a list view.
    Handles columns and padding for both single-namespace and all-namespace views.
    """
    metadata = resource.get("metadata", {})
    name = metadata.get("name", "Unknown Name")
    display_name = name[:49] if len(name) > 49 else name

    status_str = status_formatter(resource)
    age_str = calculate_age(get_creation_timestamp(resource))

    if is_all_namespaces:
        item_namespace = metadata.get("namespace", "unknown")
        namespace_col = f"{item_namespace:<25}"
        return f"{namespace_col}{display_name:<50}{status_str:<15}{age_str:<10}"
    else:
        return f"{display_name:<50}{status_str:<15}{age_str:<10}"


class ResourceFormatter(ABC):
    """Base class for formatting Kubernetes resources."""

    @abstractmethod
    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format the display text for a resource."""
        pass

    @abstractmethod
    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get the icon for a resource."""
        pass


class PodFormatter(ResourceFormatter):
    """Formatter for Pod resources."""

    # Column widths for pod display
    NAME_WIDTH = 40
    STATUS_WIDTH = 12
    READY_WIDTH = 10
    AGE_WIDTH = 10

    def get_status(self, resource: Dict[str, Any]) -> str:
        """
        Returns the status phase for a Pod object.
        """
        return str(resource.get("status", {}).get("phase", "Unknown"))

    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format pod display text with fixed-width columns."""
        name = resource.get("metadata", {}).get("name", "unknown")
        status = self.get_status(resource)

        # Get ready containers info
        status_dict = resource.get("status", {})
        containers = (
            status_dict.get("containerStatuses") or status_dict.get("container_statuses") or []
        )
        ready_count = sum(1 for c in containers if c.get("ready", False))
        total_count = len(containers)
        ready_str = f"{ready_count}/{total_count}"

        # Calculate age
        age = calculate_age(get_creation_timestamp(resource))

        # Format with fixed-width columns
        return f"{name:<{self.NAME_WIDTH}} | {status:<{self.STATUS_WIDTH}} | {ready_str:<{self.READY_WIDTH}} | {age:<{self.AGE_WIDTH}}"

    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get pod icon based on status."""
        status = resource.get("status", {}).get("phase", "").lower()
        if status == "running":
            return "🟢"
        elif status == "pending":
            return "🟡"
        elif status == "failed":
            return "🔴"
        elif status == "succeeded":
            return "✅"
        else:
            return "📦"


class DeploymentFormatter(ResourceFormatter):
    """Formatter for Deployment resources."""

    # Column widths for deployment display
    NAME_WIDTH = 40
    READY_WIDTH = 10
    AGE_WIDTH = 10

    def get_status(self, resource: Dict[str, Any]) -> str:
        """
        Returns the ready/total replica count for a Deployment object.
        """
        status = resource.get("status", {})
        ready_replicas = status.get("readyReplicas", 0)
        total_replicas = status.get("replicas", 0)
        return f"{ready_replicas}/{total_replicas}"

    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format deployment display text with fixed-width columns."""
        name = resource.get("metadata", {}).get("name", "unknown")
        ready_str = self.get_status(resource)
        age = calculate_age(get_creation_timestamp(resource))

        # Format with fixed-width columns
        return f"{name:<{self.NAME_WIDTH}} | {ready_str:<{self.READY_WIDTH}} | {age:<{self.AGE_WIDTH}}"

    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get deployment icon based on status."""
        status = resource.get("status", {})
        ready_replicas = status.get("readyReplicas", 0)
        total_replicas = status.get("replicas", 0)

        if ready_replicas == total_replicas:
            return "🚀"
        elif ready_replicas > 0:
            return "🟡"
        else:
            return "🔴"


class PvcFormatter(ResourceFormatter):
    """Formatter for PVC resources."""

    NAME_WIDTH = 40
    STATUS_WIDTH = 12
    CAPACITY_WIDTH = 10
    ACCESS_MODE_WIDTH = 15
    STORAGE_CLASS_WIDTH = 20
    AGE_WIDTH = 10

    def get_status(self, resource: Dict[str, Any]) -> str:
        """
        Returns the status phase for a PVC object.
        """
        return str(resource.get("status", {}).get("phase", "Unknown"))

    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format PVC display text with fixed-width columns."""
        name = resource.get("metadata", {}).get("name", "unknown")
        status = self.get_status(resource)

        spec = resource.get("spec", {})
        capacity = spec.get("resources", {}).get("requests", {}).get("storage", "N/A")
        access_modes = ", ".join(spec.get("accessModes", []))
        storage_class = spec.get("storageClassName", "N/A")

        age = calculate_age(get_creation_timestamp(resource))

        return (
            f"{name:<{self.NAME_WIDTH}} | "
            f"{status:<{self.STATUS_WIDTH}} | "
            f"{capacity:<{self.CAPACITY_WIDTH}} | "
            f"{access_modes:<{self.ACCESS_MODE_WIDTH}} | "
            f"{storage_class:<{self.STORAGE_CLASS_WIDTH}} | "
            f"{age:<{self.AGE_WIDTH}}"
        )

    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get PVC icon based on status."""
        status = resource.get("status", {}).get("phase", "").lower()
        if status == "bound":
            return "💾"
        elif status == "pending":
            return "⏳"
        else:
            return "❓"


class ServiceFormatter(ResourceFormatter):
    """Formatter for Service resources."""

    NAME_WIDTH = 40
    TYPE_WIDTH = 15
    CLUSTER_IP_WIDTH = 20
    AGE_WIDTH = 10

    def get_status(self, resource: Dict[str, Any]) -> str:
        """
        Returns the type of the Service.
        """
        return str(resource.get("spec", {}).get("type", "Unknown"))

    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format Service display text with fixed-width columns."""
        name = resource.get("metadata", {}).get("name", "unknown")
        service_type = self.get_status(resource)
        cluster_ip = resource.get("spec", {}).get("clusterIP", "None")

        age = calculate_age(get_creation_timestamp(resource))

        return (
            f"{name:<{self.NAME_WIDTH}} | "
            f"{service_type:<{self.TYPE_WIDTH}} | "
            f"{cluster_ip:<{self.CLUSTER_IP_WIDTH}} | "
            f"{age:<{self.AGE_WIDTH}}"
        )

    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get Service icon."""
        return "🌐"


class DefaultFormatter(ResourceFormatter):
    """Default formatter for resources without a specific formatter."""

    def format_display_text(self, resource: Dict[str, Any]) -> str:
        """Format display text for any resource."""
        name = resource.get("metadata", {}).get("name", "unknown")
        return str(name)

    def get_icon(self, resource: Dict[str, Any]) -> str:
        """Get default icon for any resource."""
        return "📄"


class ResourceFormatterRegistry:
    """Registry for resource formatters."""

    _formatters = {
        "pods": PodFormatter(),
        "deployments": DeploymentFormatter(),
        "pvcs": PvcFormatter(),
        "services": ServiceFormatter(),
    }

    @classmethod
    def get_formatter(cls, resource_kind: str) -> ResourceFormatter:
        """Get the formatter for a resource kind."""
        return cls._formatters.get(resource_kind.lower(), DefaultFormatter())
