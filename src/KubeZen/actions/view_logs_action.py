from __future__ import annotations
from typing import TYPE_CHECKING
import shlex
import tempfile
import logging

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.base import UIRow
from KubeZen.models.apps import DeploymentRow, StatefulSetRow, DaemonSetRow
from KubeZen.models.core import PodRow
from KubeZen.screens.log_options_screen import ALL_CONTAINERS_CODE, LogOptionsScreen


if TYPE_CHECKING:
    from KubeZen.app import KubeZenTuiApp

log = logging.getLogger(__name__)


@supports_resources("pods", "deployments", "statefulsets", "daemonsets")
class ViewLogsAction(BaseAction):
    """An action to view the logs of a pod or workload."""

    name = "View Logs"

    _row_info: UIRow

    async def execute(self, row_info: UIRow) -> None:
        self._row_info = row_info

        """Shows log options screen and then shows the logs."""

        def on_select(options: dict | None) -> None:
            if options:
                self.app.run_worker(
                    self._show_logs(options, ALL_CONTAINERS_CODE),
                    thread=True,
                    exclusive=True,
                )

        await self.app.push_screen(LogOptionsScreen(self._row_info), on_select)

    async def _show_logs(self, options: dict, all_containers_code: str) -> None:
        """Constructs and executes the final kubectl logs command with a pager."""
        parts = ["kubectl", "logs"]
        window_name = f"logs-{self._row_info.name}"

        if isinstance(self._row_info, PodRow):
            parts.extend([self._row_info.name])
            if self._row_info.namespace:
                parts.extend(["--namespace", self._row_info.namespace])
            container = options.get("container")
            if container and container != all_containers_code:
                parts.extend(["--container", container])
                window_name = f"logs-{self._row_info.name}-{container}"
            else:
                total_containers = len(self._row_info.raw.spec.containers) + len(
                    self._row_info.raw.spec.init_containers or []
                )
                if total_containers > 1:
                    parts.append("--all-containers=true")
        
        elif isinstance(self._row_info, (DeploymentRow, StatefulSetRow, DaemonSetRow)):
            match_labels = self._row_info.raw.spec.selector.match_labels
            selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])
            parts.extend(["-l", selector])
            if self._row_info.namespace:
                parts.extend(["--namespace", self._row_info.namespace])
            parts.append("--all-containers=true")

        # Add other log options
        if options.get("follow"):
            parts.append("--follow")
        if options.get("timestamps"):
            parts.append("--timestamps")
        if options.get("previous"):
            parts.append("--previous")
        if tail_lines := options.get("tail"):
            parts.extend(["--tail", str(tail_lines)])
        if since := options.get("since"):
            parts.extend(["--since", since])

        # Use a temp file for fzf searching later. We will manually delete it.
        with tempfile.NamedTemporaryFile(
            mode="r", delete=False, suffix=".log", dir=self.app.config.paths.temp_dir
        ) as tmp:
            log_file_path = tmp.name

        should_follow = options.get("follow", False)
        less_options = f"-j.5 -R -N {'+F' if should_follow else ''}"

        cmd_str = " ".join(shlex.quote(part) for part in parts)

        full_command = (
            f"{cmd_str} | tee {shlex.quote(log_file_path)} | less {less_options}; "
            f"rm {shlex.quote(log_file_path)}"
        )

        await self.app.tmux_manager.launch_command_in_new_window(
            command=full_command,
            window_name=window_name,
            attach=True,
            key_bindings={
                "f2": f"bin/fzf_log_search.sh {shlex.quote(log_file_path)}"
            },
        )
