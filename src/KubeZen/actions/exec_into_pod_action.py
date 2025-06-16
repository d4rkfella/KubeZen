from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging
import shlex
import asyncio

from .base_action import BaseAction
from ..screens.container_selection_screen import ContainerSelectionScreen


if TYPE_CHECKING:
    from ..app import KubeZenTuiApp

log = logging.getLogger(__name__)


class ExecIntoPodAction(BaseAction):
    """An action to open a shell inside a running pod's container."""

    async def run(self) -> None:
        """Starts the multi-step process of executing into a pod."""
        # Get the list of running containers from the pod's status.
        container_statuses = self.resource.get("status", {}).get(
            "containerStatuses", []
        )
        running_containers = [
            status["name"]
            for status in container_statuses
            if status.get("state", {}).get("running")
        ]

        if not running_containers:
            self.app.notify(
                f"No running containers found in pod '{self.resource_name}'.",
                title="Error",
                severity="error",
            )
            return

        if len(running_containers) > 1:
            await self.app.push_screen(
                ContainerSelectionScreen(
                    title="Select a container to exec into:",
                    containers=running_containers,
                    callback=self._on_container_selected,
                )
            )
        else:
            await self._on_container_selected(running_containers[0])

    async def _on_container_selected(self, container_name: str | None) -> None:
        """Callback for when a container is selected."""
        if container_name is None:
            self.app.notify("Exec cancelled.", title="Exec")
            return

        await self._start_exec_session(container_name)

    async def _find_first_available_shell(self, container_name: str) -> str | None:
        """Tries to find a suitable shell in the specified container."""
        shell_commands = ["/bin/bash", "/bin/sh"]
        for shell in shell_commands:
            try:
                # Use kubectl to check if the shell binary exists and is executable.
                test_command = (
                    f"kubectl exec --namespace {shlex.quote(self.namespace)} "
                    f"{shlex.quote(self.resource_name)} "
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

    async def _start_exec_session(self, container_name: str) -> None:
        """Finds a shell and launches the kubectl exec command in tmux."""
        self.app.pop_screen()  # Pop the ActionScreen

        shell = await self._find_first_available_shell(container_name)
        if not shell:
            self.app.notify(
                f"No suitable shell found in container '{container_name}'.",
                title="Error",
                severity="error",
            )
            return

        command = (
            f"kubectl exec -it --namespace {shlex.quote(self.namespace)} "
            f"{shlex.quote(self.resource_name)} --container {shlex.quote(container_name)} "
            f"-- {shell}"
        )
        window_name = f"exec-{self.resource_name}-{container_name}"
        log.info(f"Executing command: {command}")

        try:
            await self.tmux_manager.launch_command_in_new_window(
                command=command, window_name=window_name, attach=True
            )
        except Exception as e:
            message = f"Failed to start exec session: {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
