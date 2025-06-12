from KubeZen.actions.delete_resource import DeleteResourceAction
from KubeZen.actions.describe_resource import DescribeResourceAction
from KubeZen.actions.edit_resource import EditResourceAction
from KubeZen.actions.view_yaml import ViewYamlAction
from KubeZen.actions.pod.exec_into_pod import ExecIntoPodAction
from KubeZen.actions.pod.view_logs import ViewPodLogsAction
from KubeZen.actions.pvc.file_browser_action import PVCBrowserAction
from KubeZen.actions.port_forward_action import PortForwardAction

ACTION_REGISTRY = [
    # General Actions, applicable to all resource types
    {
        "class": ViewPodLogsAction,
        "name": "View Logs",
        "shortcut": "l",
        "icon": "📜",
        "resource_types": ["pods"],
    },
    {
        "class": ExecIntoPodAction,
        "name": "Exec into Pod",
        "shortcut": "e",
        "icon": "❯_",
        "resource_types": ["pods"],
    },
    {
        "class": DeleteResourceAction,
        "name": "Delete",
        "shortcut": "x",
        "icon": "💣",
        "resource_types": ["*"],
    },
    {
        "class": DescribeResourceAction,
        "name": "Describe",
        "shortcut": "d",
        "icon": "📝",
        "resource_types": ["*"],
    },
    {
        "class": EditResourceAction,
        "name": "Edit",
        "shortcut": "e",
        "icon": "🔧",
        "resource_types": ["*"],
    },
    {
        "class": ViewYamlAction,
        "name": "View YAML",
        "shortcut": "y",
        "icon": "📄",
        "resource_types": ["*"],
    },
    {
        "class": PVCBrowserAction,
        "name": "Browse PVC",
        "shortcut": "b",
        "icon": "📁",
        "resource_types": ["pvcs"],
    },
    {
        "class": PortForwardAction,
        "name": "Port Forward",
        "shortcut": "p",
        "icon": "🔌",
        "resource_types": ["pods", "services"],
    },
]
