from KubeZen.providers.pod_provider import create_pod_provider
from KubeZen.providers.deployment_provider import create_deployment_provider
from KubeZen.providers.pvc_provider import create_pvc_provider
from KubeZen.providers.service_provider import create_service_provider
from KubeZen.ui.resource_formatters import (
    format_resource_list_line,
    PodFormatter,
    DeploymentFormatter,
    PvcFormatter,
    ServiceFormatter,
)

pod_formatter = PodFormatter()
deployment_formatter = DeploymentFormatter()
pvc_formatter = PvcFormatter()
service_formatter = ServiceFormatter()


RESOURCE_TYPE_CONFIGS = [
    {
        "code": "pods",
        "display": "Pods",
        "icon": "📦",
        "status_formatter": pod_formatter.get_status,
        "line_formatter": format_resource_list_line,
        "item_provider_factory": create_pod_provider,
    },
    {
        "code": "deployments",
        "display": "Deployments",
        "icon": "🚀",
        "status_formatter": deployment_formatter.get_status,
        "line_formatter": format_resource_list_line,
        "item_provider_factory": create_deployment_provider,
    },
    {
        "code": "pvcs",
        "display": "PVCs",
        "icon": "💾",
        "status_formatter": pvc_formatter.get_status,
        "line_formatter": format_resource_list_line,
        "item_provider_factory": create_pvc_provider,
    },
    {
        "code": "services",
        "display": "Services",
        "icon": "🌐",
        "status_formatter": service_formatter.get_status,
        "line_formatter": format_resource_list_line,
        "item_provider_factory": create_service_provider,
    },
]
