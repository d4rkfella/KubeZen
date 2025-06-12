from typing import List, Dict, Any
from KubeZen.actions.action_registry import ACTION_REGISTRY


def get_registered_actions_for_resource_type(
    resource_type: str,
) -> List[Dict[str, Any]]:
    """
    Retrieves a list of action configurations applicable to a given resource type.

    Args:
        resource_type: The type of the resource (e.g., 'pods', 'deployments').

    Returns:
        A list of action configuration dictionaries that can be used to instantiate
        the actions.
    """
    applicable_actions = []
    for action_config in ACTION_REGISTRY:
        resource_types = action_config.get("resource_types", [])
        if isinstance(resource_types, (list, tuple)) and (
            "*" in resource_types or resource_type in resource_types
        ):
            applicable_actions.append(action_config)
    return applicable_actions
