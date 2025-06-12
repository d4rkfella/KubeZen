from __future__ import annotations
from typing import Optional, Dict, Any
import shlex
import time
import asyncio

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.core.exceptions import (
    ActionFailedError,
)
from KubeZen.actions.pod.pod_action_utils import select_container_if_needed


class ExecIntoPodAction(Action):
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

        # Ensure the pod is running
        status = resource.get("status", {})
        if not status:
            return False

        pod_phase = status.get("phase")
        if not isinstance(pod_phase, str):
            return False
        return pod_phase == "Running"

    async def _find_first_available_shell(
        self, context: ActionContext, pod_name: str, namespace: str, container_name: str
    ) -> Optional[str]:
        """
        Attempts to find a suitable shell in the specified pod and container.
        Returns the first available shell command, or None if none are found.
        """
        # List of shell commands to try, in order of preference
        shell_commands = ["/bin/bash", "/bin/sh", "/bin/zsh", "/bin/ash", "/bin/dash"]

        for shell in shell_commands:
            try:
                # Construct a command to test if the shell exists
                test_command = f"kubectl exec --namespace {shlex.quote(namespace)} {shlex.quote(pod_name)} --container {shlex.quote(container_name)} -- which {shlex.quote(shell)}"

                proc = await asyncio.create_subprocess_shell(
                    test_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                await proc.communicate()

                # If the command succeeded (return code 0), the shell exists
                if proc.returncode == 0:
                    return shell

            except Exception as e:
                context.logger.debug(f"Failed to test shell {shell}: {e}")
                continue

        return None

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        """
        Handles the execution of the 'exec' action. This involves:
        1. Determining the target container (prompting the user if necessary).
        2. Finding a suitable shell inside the container.
        3. Constructing a `kubectl exec` command.
        4. Using TmuxUIManager to run the command in a new, interactive window.
        """
        action_name = self.__class__.__name__
        metadata = resource.get("metadata", {})
        if not metadata:
            raise ActionFailedError(f"{action_name}: Pod metadata is missing.")

        pod_name = metadata.get("name")
        namespace = metadata.get("namespace")

        if not pod_name or not namespace:
            raise ActionFailedError(f"{action_name}: Pod name or namespace is missing.")

        # --- Step 1: Select the container ---
        selection_signal = await select_container_if_needed(
            self, context, resource, only_running=True
        )
        if selection_signal:
            return selection_signal

        if context.custom_data is None:
            raise ActionFailedError(
                f"{action_name}: Could not determine container for exec: custom_data is missing."
            )

        selected_container_name = context.custom_data.get("selected_container_name")
        if not selected_container_name:
            raise ActionFailedError(f"{action_name}: Could not determine container for exec.")

        context.logger.info(
            f"Proceeding with exec for pod '{namespace}/{pod_name}', container '{selected_container_name}'."
        )

        # --- Step 2: Find a suitable shell ---
        selected_shell = await self._find_first_available_shell(
            context, pod_name, namespace, selected_container_name
        )

        if not selected_shell:
            error_message = f"No suitable shell found in pod '{pod_name}' container '{selected_container_name}'."
            await context.tmux_ui_manager.show_toast(
                error_message, bg_color="red", fg_color="white"
            )
            return StaySignal()

        # --- Step 3: Construct the final kubectl command ---
        shell_command = (
            f"kubectl exec -it --namespace {shlex.quote(namespace)} "
            f"{shlex.quote(pod_name)} --container {shlex.quote(selected_container_name)} "
            f"-- {shlex.quote(selected_shell)}"
        )
        context.logger.debug(f"Constructed exec shell command: {shell_command}")

        # --- Step 4: Execute in a new window ---
        task_name = f"Exec_{namespace}_{pod_name}_{selected_container_name}_{int(time.time())}"

        try:
            await context.tmux_ui_manager.launch_command_in_new_window(
                command_str=shell_command,
                window_name=task_name,
                attach=True,
            )
            await context.tmux_ui_manager.show_toast(
                f"Exec session started for {pod_name}/{selected_container_name}"
            )
        except Exception as e:
            error_message = f"Failed to start exec session: {e}"
            context.logger.error(error_message, exc_info=True)
            raise ActionFailedError(error_message)

        return StaySignal()
