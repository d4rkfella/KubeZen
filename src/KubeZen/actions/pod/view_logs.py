from __future__ import annotations
from typing import Optional, Dict, Any
import shlex
import asyncio
import re

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import (
    ActionFailedError,
    UserInputCancelledError,
    UserInputFailedError,
)
from KubeZen.core.user_input_manager import InputSpec
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.actions.pod.pod_action_utils import select_container_if_needed


def validate_yes_no(input_str: str) -> None:
    """Validator to ensure input is 'y' or 'n'."""
    if input_str.lower().strip() not in ["y", "n"]:
        raise ValueError("Please enter 'y' or 'n'.")

def validate_positive_integer(input_str: str) -> None:
    """Validator to ensure input is a positive integer."""
    if not input_str.isdigit() or int(input_str) <= 0:
        raise ValueError("Please enter a positive number.")

def validate_duration(input_str: str) -> None:
    """Validator to ensure input is a valid duration string (e.g., 5m, 2h, 10s) or empty."""
    if not input_str:  # Allow empty string
        return
    if not re.match(r"^\d+[smh]$", input_str):
        raise ValueError("Invalid duration format. Use formats like 10s, 5m, 2h.")

class ViewPodLogsAction(Action):
    ALL_CONTAINERS_CODE = "All Containers"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        """
        This action is applicable if we have a resource object, and that resource
        is a pod that is currently in the 'Running' phase.
        """
        resource = context.raw_k8s_object
        if not resource:
            return False

        # Ensure the resource is a pod
        kind = resource.get("kind")
        if not isinstance(kind, str) or kind != "Pod":
            return False

        return True

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        """
        Executes the view logs action for a given pod resource.
        - If the pod has multiple containers and one is not specified in the
          context, it returns a PushViewSignal to the ContainerSelectionView.
        - Otherwise, it prompts for log options and displays the logs.
        """
        action_name = self.__class__.__name__
        metadata = resource.get("metadata", {})
        if not metadata:
            raise ActionFailedError(f"{action_name}: Pod metadata is missing.")

        pod_name = metadata.get("name")
        namespace = metadata.get("namespace")

        if not pod_name or not namespace:
            raise ActionFailedError(f"{action_name}: Pod name or namespace is missing.")

        context.logger.debug(
            f"[{action_name}] Initiating 'View Logs' for pod '{namespace}/{pod_name}'"
        )

        # --- Step 1: Select the container (or "all") ---
        selection_signal = await select_container_if_needed(
            self, context, resource, only_running=False
        )
        if selection_signal:
            if selection_signal.context and "container_names" in selection_signal.context:
                selection_signal.context["container_names"].insert(0, self.ALL_CONTAINERS_CODE)
            return selection_signal

        if context.custom_data is None:
            # This should not happen if select_container_if_needed has run, but for type safety:
            raise ActionFailedError(
                "Could not determine container for logs: custom_data is missing."
            )

        selected_container = context.custom_data.get("selected_container_name")
        if not selected_container:
            raise ActionFailedError("Could not determine container for logs.")

        # --- Step 2: Get log options from the user ---
        is_all_containers = selected_container == self.ALL_CONTAINERS_CODE
        log_target = "all containers" if is_all_containers else f"container '{selected_container}'"
        context.logger.info(
            f"Gathering log options for {log_target} in pod {namespace}/{pod_name}."
        )

        try:
            input_specs = [
                InputSpec(
                    result_key="tail_lines",
                    prompt_message="Tail lines (e.g., 500, default: all): ",
                    default_value="5000",
                    validator=validate_positive_integer,
                    validation_error_message="Invalid number.",
                ),
                InputSpec(
                    result_key="follow",
                    prompt_message="Follow logs (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                    validation_error_message="Invalid choice.",
                ),
                InputSpec(
                    result_key="previous",
                    prompt_message="View previous termination (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                    validation_error_message="Invalid choice.",
                ),
                InputSpec(
                    result_key="timestamps",
                    prompt_message="Add timestamps (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                    validation_error_message="Invalid choice.",
                ),
                InputSpec(
                    result_key="since",
                    prompt_message="Only logs since duration (e.g., 5m, 2h): ",
                    default_value="",
                    validator=validate_duration,
                    validation_error_message="Invalid duration format.",
                ),
            ]

            # The 'follow' option is not compatible with 'all-containers'
            if is_all_containers:
                input_specs = [spec for spec in input_specs if spec.result_key != "follow"]

            log_options = await context.user_input_manager.get_multiple_inputs(
                specs=input_specs, task_name="Get Log Options"
            )

            # --- Step 3: Construct and execute the kubectl command ---
            log_command_parts = ["kubectl", "logs", pod_name, "--namespace", namespace]

            if is_all_containers:
                log_command_parts.append("--all-containers")
            else:
                log_command_parts.extend(["--container", selected_container])

            tail_lines = log_options.get("tail_lines")
            if tail_lines and tail_lines.isdigit() and int(tail_lines) > 0:
                log_command_parts.extend(["--tail", str(tail_lines)])

            if log_options.get("follow", "n").lower() == "y" and not is_all_containers:
                log_command_parts.append("-f")

            if log_options.get("previous", "n").lower() == "y":
                log_command_parts.append("--previous")

            if log_options.get("timestamps", "n").lower() == "y":
                log_command_parts.append("--timestamps")

            since = log_options.get("since")
            if since:
                log_command_parts.extend(["--since", since])

            final_log_command = " ".join(shlex.quote(part) for part in log_command_parts)

            # For logs, we want to use follow mode by default
            pager_command = (
                "less -R +F"
                if log_options.get("follow", "n").lower() == "y" and not is_all_containers
                else "less -R"
            )
            asyncio.create_task(
                context.tmux_ui_manager.display_command_in_pager(
                    command_to_page=final_log_command,
                    pager_command=pager_command,
                    task_name=f"ViewLogs_{namespace}_{pod_name}_{selected_container}",
                )
            )

        except (UserInputCancelledError, UserInputFailedError) as e:
            await context.tmux_ui_manager.show_toast(
                f"Log view: {e}", bg_color="yellow", fg_color="black"
            )
            return StaySignal()

        return StaySignal()
