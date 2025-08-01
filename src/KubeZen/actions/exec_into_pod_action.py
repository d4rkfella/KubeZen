from __future__ import annotations
import logging
import shlex
import asyncio

from KubeZen.models.core import PodRow
from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.screens.container_selection_screen import ContainerSelectionScreen


log = logging.getLogger(__name__)


@supports_resources("pods")
class ExecIntoPodAction(BaseAction):
    """An action to open a shell inside a running pod's container."""

    name = "Exec into"

    async def execute(self, row_info: PodRow) -> None:
        """Starts the multistep process of executing into a pod."""
        # Get the list of running containers from the pod's status.
        container_statuses = []

        status = row_info.raw.status
        if status:
            # Regular containers
            if status.container_statuses:
                container_statuses.extend(status.container_statuses)
            # Init containers (now can be long-running with restartPolicy: Always)
            if status.init_container_statuses:
                container_statuses.extend(status.init_container_statuses)
            # Ephemeral containers
            if getattr(status, "ephemeral_container_statuses", None):
                container_statuses.extend(status.ephemeral_container_statuses)

        running_containers = [
            cs.name for cs in container_statuses if cs.state and cs.state.running
        ]

        if not running_containers:
            self.app.notify(
                f"No running containers found in pod '{row_info.name}'.",
            )
            return

        if len(running_containers) > 1:
            selected_container = await self.app.push_screen_wait(
                ContainerSelectionScreen(
                    title="Select a container to exec into:",
                    containers=running_containers,
                )
            )
            if selected_container is not None:
                await self._start_exec_session(row_info, selected_container)
        else:
            await self._start_exec_session(row_info, running_containers[0])

    async def _find_first_available_shell(
        self, row_info: PodRow, container_name: str
    ) -> str | None:
        """Tries to find a suitable shell in the specified container."""
        shell_commands = ["/bin/bash", "/bin/ash", "/bin/sh"]
        for shell in shell_commands:
            try:
                # Use kubectl to check if the shell binary exists and is executable.
                test_command = (
                    f"kubectl exec --namespace {shlex.quote(row_info.namespace)} "
                    f"{shlex.quote(row_info.name)} "
                    f"--container {shlex.quote(container_name)} -- test -x {shell}"
                )
                proc = await asyncio.create_subprocess_shell(
                    test_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0:
                    return shell
            except Exception as e:
                log.warning(f"Failed to test for shell {shell}: {e}")
                continue
        return None

    async def _start_exec_session(self, row_info: PodRow, container_name: str) -> None:
        shell = await self._find_first_available_shell(row_info, container_name)
        if not shell:
            self.app.notify(
                f"No suitable shell found in container '{container_name}'.",
                title="Error",
                severity="error",
            )
            return

        command = (
            f"kubectl exec -it --namespace {shlex.quote(row_info.namespace)} "
            f"{shlex.quote(row_info.name)} --container {shlex.quote(container_name)} "
            f"-- {shell}"
        )

        try:
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"exec-{row_info.name}-{container_name}",
            )
        except Exception as e:
            message = f"Failed to start exec session: {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
