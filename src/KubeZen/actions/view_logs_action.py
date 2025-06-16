from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging
import shlex
import tempfile

from .base_action import BaseAction
from ..screens.log_options_screen import LogOptionsScreen, ALL_CONTAINERS_CODE
from ..core.resource_registry import RESOURCE_REGISTRY

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

log = logging.getLogger(__name__)


class ViewLogsAction(BaseAction):
    """An action to view the logs of a pod or workload."""

    # This will hold the user's choices between screens
    _log_options: dict[str, Any]

    def __init__(
        self,
        app: KubeZenTuiApp,
        resource: dict[str, Any],
        object_name: str,
        resource_key: str,
    ):
        super().__init__(app, resource, object_name, resource_key)
        self._log_options = {}

    async def run(self) -> None:
        """Starts the multi-step process of viewing logs."""
        if self.resource_kind == "pods":
            await self._handle_pod_log_selection()
        else:
            await self._handle_workload_log_selection()

    async def _handle_pod_log_selection(self) -> None:
        """Handles the logic for selecting containers in a pod."""
        if not self.client.core_v1 or not self.namespace:
            return

        try:
            pod = await self.client.core_v1.read_namespaced_pod(
                name=self.resource_name, namespace=self.namespace
            )
            containers = [c.name for c in pod.spec.containers] + [
                c.name for c in (pod.spec.init_containers or [])
            ]

            self._log_options["target_name"] = f"pod '{self.resource_name}'"

            if len(containers) > 1:
                # Pass the list of containers to the options screen.
                await self._show_log_options_screen(containers=containers)
            elif len(containers) == 1:
                # Pre-select the only container.
                self._log_options["container"] = containers[0]
                await self._show_log_options_screen()
            else:
                self.app.notify(
                    f"No containers found in pod '{self.resource_name}'.",
                    title="Error",
                    severity="error",
                )

        except Exception as e:
            message = f"Failed to get pod details: {e}"
            log.error(f"Failed to get pod details for log action: {e}", exc_info=True)
            self.app.notify(message, title="Error", severity="error")

    async def _handle_workload_log_selection(self) -> None:
        """Handles the logic for getting logs from a workload."""
        resource_meta = RESOURCE_REGISTRY.get(self.resource_kind)
        if not resource_meta or not self.namespace:
            log.error(
                f"Cannot get logs for {self.resource_kind}, registry entry not found."
            )
            return

        api_client_attr = resource_meta["api_client_attr"]
        read_method_name = resource_meta["read_method"]
        api_client = getattr(self.client, api_client_attr)
        read_method = getattr(api_client, read_method_name)

        try:
            workload = await read_method(
                name=self.resource_name, namespace=self.namespace
            )
            selector = getattr(workload.spec, "selector", None)
            if not selector or not getattr(selector, "match_labels", None):
                message = f"No selector found for workload '{self.resource_name}'."
                log.error(message)
                self.app.notify(message, title="Error", severity="error")
                return

            labels = selector.match_labels
            label_selector_str = ",".join([f"{k}={v}" for k, v in labels.items()])

            self._log_options["selector"] = label_selector_str
            self._log_options["target_name"] = (
                f"pods with selector '{label_selector_str}'"
            )
            await self._show_log_options_screen()

        except Exception as e:
            message = f"Failed to get workload details: {e}"
            log.error(
                f"Failed to get workload details for log action: {e}", exc_info=True
            )
            self.app.notify(message, title="Error", severity="error")

    async def _show_log_options_screen(
        self, containers: list[str] | None = None
    ) -> None:
        """Presents the user with various logging options."""
        allow_follow = self.resource_kind == "pods"

        async def options_callback(options: dict[str, Any] | None) -> None:
            """Nested callback to handle the result from the options screen."""
            if options is None:
                return  # The modal was cancelled.

            self._log_options.update(options)
            self.app.run_worker(self._execute_log_command())

        await self.app.push_screen(
            LogOptionsScreen(
                target_name=self._log_options.get("target_name", "unknown"),
                allow_follow=allow_follow,
                containers=containers,
            ),
            options_callback,
        )

    async def _execute_log_command(self) -> None:
        """Constructs and executes the final kubectl logs command."""
        self.app.pop_screen()  # Pop the ActionScreen

        if not self.namespace:
            log.error("Cannot execute log command without a namespace.")
            self.app.notify("Namespace not available.", title="Error", severity="error")
            return

        parts = ["kubectl", "logs", "--namespace", self.namespace]

        # Target selector
        if selector := self._log_options.get("selector"):
            parts.extend([f"--selector={selector}", "--all-containers=true"])
        else:
            parts.append(self.resource_name)
            container = self._log_options.get("container")
            if container and container != ALL_CONTAINERS_CODE:
                parts.extend(["--container", container])
            elif container == ALL_CONTAINERS_CODE:
                parts.append("--all-containers=true")

        # Log options from the new screen
        if self._log_options.get("follow"):
            parts.append("--follow")
        if self._log_options.get("timestamps"):
            parts.append("--timestamps")
        if self._log_options.get("previous"):
            parts.append("--previous")
        if tail_lines := self._log_options.get("tail"):
            parts.extend(["--tail", str(tail_lines)])
        if since := self._log_options.get("since"):
            parts.extend(["--since", since])

        # Use a temp file for fzf searching later
        with tempfile.NamedTemporaryFile(mode="w", delete=True, suffix=".log") as tmp:
            log_file_path = tmp.name

        # Determine less options based on whether we are following the logs.
        should_follow = self._log_options.get("follow", False)
        less_options = f"-j.5 -R -N {'+F' if should_follow else ''}"

        # The final command pipes kubectl output to 'tee' (to save to the file)
        # and then to 'less' for viewing.
        cmd_str = " ".join(shlex.quote(part) for part in parts)
        full_command = (
            f"{cmd_str} | tee {shlex.quote(log_file_path)} | less {less_options}"
        )

        window_name = f"logs-{self.resource_name}"
        log.info(f"Executing log command: {full_command}")

        try:
            window = await self.tmux_manager.launch_command_in_new_window(
                command=full_command, window_name=window_name, attach=True
            )

            if window and window.attached_pane and window.attached_pane.id:
                pane_id = window.attached_pane.id
                search_script = "bin/fzf_log_search.sh"
                search_command = (
                    f"{search_script} {shlex.quote(log_file_path)} {pane_id}"
                )

                await self.tmux_manager.set_key_bindings(
                    pane_id, {"f2": search_command}
                )
        except Exception as e:
            message = f"Failed to start log viewer: {e}"
            log.error("Failed to execute log command.", exc_info=True)
            self.app.notify(message, title="Error", severity="error")
        finally:
            # The temp file is intentionally not deleted. The fzf script needs it.
            # A periodic cleanup job for old /tmp files is the standard solution.
            pass
