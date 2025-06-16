from .describe_action import DescribeResourceAction
from .view_yaml_action import ViewYamlAction
from .delete_action import DeleteResourceAction
from .edit_action import EditResourceAction
from .pvc_file_browser_action import PVCFileBrowserAction
from .view_logs_action import ViewLogsAction
from .port_forward_action import PortForwardAction
from .scale_action import ScaleResourceAction
from .exec_into_pod_action import ExecIntoPodAction

ACTION_REGISTRY = [
    {
        "class": DescribeResourceAction,
        "name": "Describe",
        "emoji": "🔍",
        "resource_types": ["all"],
    },
    {
        "class": ViewYamlAction,
        "name": "View YAML",
        "emoji": "📄",
        "resource_types": ["all"],
    },
    {
        "class": EditResourceAction,
        "name": "Edit",
        "emoji": "✏️",
        "resource_types": ["all"],
    },
    {
        "class": DeleteResourceAction,
        "name": "Delete",
        "emoji": "❌",
        "resource_types": ["all"],
    },
    {
        "class": PVCFileBrowserAction,
        "name": "Browse Files",
        "emoji": "📂",
        "resource_types": ["pvcs"],
    },
    {
        "class": ViewLogsAction,
        "name": "View Logs",
        "emoji": "📜",
        "resource_types": ["pods", "deployments", "statefulsets", "daemonsets"],
    },
    {
        "class": PortForwardAction,
        "name": "Port Forward",
        "emoji": "🔌",
        "resource_types": ["pods", "services"],
    },
    {
        "class": ScaleResourceAction,
        "name": "Scale",
        "emoji": "↔️",
        "resource_types": ["deployments", "statefulsets"],
    },
    {
        "class": ExecIntoPodAction,
        "name": "Exec into Pod",
        "emoji": "💻",
        "resource_types": ["pods"],
    },
    # Future actions will be added here, e.g.:
    # {
    #     "class": ViewLogsAction,
    #     "name": "View Logs",
    #     "emoji": "📜",
    #     "resource_types": ["pods"],
    # },
]
