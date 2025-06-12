from KubeZen.actions.delete_resource import DeleteResourceAction
from KubeZen.actions.describe_resource import DescribeResourceAction
from KubeZen.actions.edit_resource import EditResourceAction
from KubeZen.actions.view_yaml import ViewYamlAction
from KubeZen.actions.pod.exec_into_pod import ExecIntoPodAction
from KubeZen.actions.view_logs import ViewLogsAction
from KubeZen.actions.pvc.file_browser_action import PVCBrowserAction
from KubeZen.actions.port_forward import PortForwardAction
from KubeZen.actions.workload.scale import ScaleWorkloadAction
from KubeZen.actions.deployment.restart_rollout import RestartRolloutAction
from KubeZen.actions.deployment.rollback import RollbackAction

ACTION_REGISTRY = [
    {
        "class": ViewLogsAction,
        "name": "View Logs",
        "icon": "📜",
        "resource_types": ["pods", "deployments", "statefulsets", "replicasets"],
    },
    {
        "class": ExecIntoPodAction,
        "name": "Exec into Pod",
        "icon": "❯_",
        "resource_types": ["pods"],
    },
    {
        "class": DeleteResourceAction,
        "name": "Delete",
        "icon": "💣",
        "resource_types": ["*"],
    },
    {
        "class": DescribeResourceAction,
        "name": "Describe",
        "icon": "📝",
        "resource_types": ["*"],
    },
    {
        "class": EditResourceAction,
        "name": "Edit",
        "icon": "🔧",
        "resource_types": ["*"],
    },
    {
        "class": ViewYamlAction,
        "name": "View YAML",
        "icon": "📄",
        "resource_types": ["*"],
    },
    {
        "class": PVCBrowserAction,
        "name": "Browse PVC",
        "icon": "📁",
        "resource_types": ["pvcs"],
    },
    {
        "class": PortForwardAction,
        "name": "Port Forward",
        "icon": "🔌",
        "resource_types": ["pods", "services"],
    },
    {
        "class": ScaleWorkloadAction,
        "name": "Scale",
        "icon": "⚖️",
        "resource_types": ["deployments", "statefulsets", "replicasets"],
    },
    {
        "class": RestartRolloutAction,
        "name": "Restart Rollout",
        "icon": "🔄",
        "resource_types": ["deployments"],
    },
    {
        "class": RollbackAction,
        "name": "Rollback",
        "icon": "⏪",
        "resource_types": ["deployments"],
    },
]
