from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List, Dict, Any
from KubeZen.core.signals import PushViewSignal
from KubeZen.ui.views.container_selection_view import ContainerSelectionView
from KubeZen.core.exceptions import ActionFailedError

if TYPE_CHECKING:
    from KubeZen.core.contexts import ActionContext
    from KubeZen.core.actions import Action


def get_containers_from_pod(
    pod_obj: Dict[str, Any],
    include_init_containers: bool = True,
    only_running: bool = False,
) -> List[Dict[str, Any]]:
    """
    Extracts a list of containers from a pod object based on specified criteria.

    Args:
        pod_obj: The raw Kubernetes pod object.
        include_init_containers: Whether to include init containers.
        only_running: If True, only include containers that are currently in a 'running' state.

    Returns:
        A list of container dictionaries.
    """
    all_containers = []
    # pod_name = pod_obj.get("metadata", {}).get("name", "unknown")

    # 1. Get regular containers
    spec = pod_obj.get("spec", {})
    if spec:
        all_containers.extend(spec.get("containers", []))

    # 2. Get init containers if requested
    if include_init_containers and spec:
        all_containers.extend(spec.get("initContainers", []))

    if not only_running:
        return all_containers

    # 3. Filter by running state if requested
    running_containers = []
    status = pod_obj.get("status", {})
    container_statuses = status.get("containerStatuses", [])
    init_container_statuses = status.get("initContainerStatuses", [])
    all_statuses = container_statuses + init_container_statuses

    running_container_names = {
        status["name"] for status in all_statuses if status.get("state", {}).get("running")
    }

    for container in all_containers:
        if container["name"] in running_container_names:
            running_containers.append(container)

    return running_containers


async def select_container_if_needed(
    action: Action, context: ActionContext, resource: Dict[str, Any], only_running: bool = False
) -> Optional[PushViewSignal]:
    """
    Checks if a container needs to be selected for a pod action.
    - If a container is already in context.custom_data, it does nothing.
    - If the pod has one container, it's auto-selected and added to context.
    - If the pod has multiple containers, it returns a PushViewSignal to the
      ContainerSelectionView.
    - If no containers are found, it raises an ActionFailedError.

    Args:
        action: The action instance calling this utility.
        context: The current action context.
        resource: The raw Kubernetes pod object.
        only_running: If True, only considers running containers for selection.
    """
    if context.custom_data is None:
        context.custom_data = {}

    action_name = action.__class__.__name__
    metadata = resource.get("metadata", {})
    pod_name = metadata.get("name")
    namespace = metadata.get("namespace")

    if not pod_name or not namespace:
        raise ActionFailedError(f"[{action_name}] Pod metadata missing name or namespace.")

    # Check if a container was already selected (e.g., when returning from the selection view)
    if context.custom_data.get("selected_container_name"):
        context.logger.debug(
            f"[{action_name}] Container '{context.custom_data['selected_container_name']}' already selected in custom_data. Skipping selection."
        )
        return None

    context.logger.debug(f"[{action_name}] No container in custom_data. Checking pod spec.")

    all_containers = get_containers_from_pod(
        resource, include_init_containers=True, only_running=only_running
    )
    all_container_names = [c["name"] for c in all_containers]

    if not all_container_names:
        raise ActionFailedError(f"Pod '{pod_name}' has no containers to select from.")

    if len(all_container_names) == 1:
        selected_container = all_container_names[0]
        context.logger.info(
            f"[{action_name}] Auto-selected single container: {selected_container}"
        )
        context.custom_data["selected_container_name"] = selected_container
        return None
    else:
        context.logger.info(
            f"[{action_name}] Pod has multiple containers. Pushing ContainerSelectionView."
        )
        view_context = {
            "pod_name": pod_name,
            "namespace": namespace,
            "container_names": all_container_names,
            "original_action_context": context.to_dict(),
            "action_to_resume": action.action_code,
        }
        return PushViewSignal(view_class=ContainerSelectionView, context=view_context)
