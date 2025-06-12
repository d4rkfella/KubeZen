from typing import Optional, Any, List, Dict
import pprint
import logging
from .utils import UtilsMixin


class DescribeMixin(UtilsMixin):
    logger: logging.Logger
    app_services: Any = None  # This will be set by the parent class

    async def describe_resource(
        self,
        resource_type: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> str:
        logger = getattr(self, "logger", None) or getattr(self.app_services, "logger", None)
        # Use the generic get_namespaced_resource_object or get_cluster_scoped_resource_object from UtilsMixin
        if namespace:
            obj = await self.get_namespaced_resource_object(resource_type, name, namespace)
        else:
            obj = await self.get_cluster_scoped_resource_object(resource_type, name)
        if obj is None:
            if logger:
                logger.error(f"Could not fetch {resource_type} '{name}' for describe.")
            return f"Error: Could not fetch {resource_type} '{name}'"
        # Pod-specific formatting
        kind = getattr(obj, "kind", None) or (
            obj.to_dict().get("kind") if hasattr(obj, "to_dict") else None
        )
        if kind and kind.lower() == "pod":
            return self._format_pod_describe(obj)
        # Fallback: pretty print dict
        if hasattr(obj, "to_dict"):
            return pprint.pformat(obj.to_dict(), indent=2, width=120)
        return str(obj)

    def _format_pod_describe(self, pod: Any) -> str:
        d = pod.to_dict() if hasattr(pod, "to_dict") else pod
        lines = []
        meta = d.get("metadata", {})
        spec = d.get("spec", {})
        status = d.get("status", {})
        lines.append(f"Name:        {meta.get('name', '-')}")
        lines.append(f"Namespace:   {meta.get('namespace', '-')}")
        lines.append(f"Priority:    {spec.get('priority', '-')}")
        lines.append(f"Node:        {status.get('node_name', '-')}")
        lines.append(f"Start Time:  {status.get('start_time', '-')}")
        lines.append("Labels:")
        lines.extend(self._format_dict(meta.get("labels", {}), indent=2))
        lines.append("Annotations:")
        lines.extend(self._format_dict(meta.get("annotations", {}), indent=2))
        lines.append(f"Status:      {status.get('phase', '-')}")
        lines.append(f"IP:          {status.get('pod_ip', '-')}")
        lines.append(f"Controlled By: {self._get_controller(meta)}")
        lines.append("")
        # Containers
        lines.append("Containers:")
        containers = spec.get("containers", [])
        for c in containers:
            lines.append(f"  {c.get('name', '-')}: ")
            lines.append(f"    Image:      {c.get('image', '-')}")
            # Ports
            ports = c.get("ports", [])
            if ports:
                lines.append("    Ports:")
                for p in ports:
                    port_str = f"      - {p.get('container_port', '-')}/{p.get('protocol', '-')}"
                    lines.append(port_str)
            else:
                lines.append("    Ports:      None")
            # Env
            envs = c.get("env", [])
            if envs:
                lines.append("    Env:")
                for e in envs:
                    name = e.get("name", "-")
                    value = e.get("value", "-")
                    lines.append(f"      - {name}: {value}")
            else:
                lines.append("    Env:        None")
            # Resources
            resources = c.get("resources", {})
            lines.append("    Resources:")
            if resources:
                for k, v in resources.items():
                    lines.append(f"      {k}: {v}")
            else:
                lines.append("      None")
        # Statuses
        lines.append("")
        lines.append("Conditions:")
        for cond in status.get("conditions", []):
            type_str = str(cond.get("type", "-") or "-")
            status_str = str(cond.get("status", "-") or "-")
            reason_str = str(cond.get("reason", "-") or "-")
            message_str = str(cond.get("message", "-") or "-")
            lines.append(
                f"  Type: {type_str:12} Status: {status_str:6} Reason: {reason_str:10} Message: {message_str}"
            )
        result = "\n".join(lines)
        return result

    def _format_dict(self, d: Dict[str, Any], indent: int = 0) -> List[str]:
        lines = []
        for k, v in d.items():
            lines.append(" " * indent + f"{k}: {v}")
        if not lines:
            lines.append(" " * indent + "-")
        return lines

    def _get_controller(self, meta: Dict[str, Any]) -> str:
        owner_refs = meta.get("owner_references", [])
        if owner_refs:
            ref = owner_refs[0]
            return f"{ref.get('kind', '-')}/{ref.get('name', '-')}"
        return "-"
