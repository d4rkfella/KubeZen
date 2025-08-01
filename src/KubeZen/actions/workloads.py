from __future__ import annotations
from typing import Union
import logging
from datetime import datetime

from .base_action import BaseAction, supports_resources
from KubeZen.models.apps import DeploymentRow, StatefulSetRow, DaemonSetRow
from KubeZen.screens.input_screen import InputScreen, InputInfo

log = logging.getLogger(__name__)


@supports_resources("deployments", "statefulsets", "daemonsets")
class WorkloadsRestartAction(BaseAction[DeploymentRow | StatefulSetRow | DaemonSetRow]):
    """An action to perform a rolling restart on a workload."""

    name = "Restart"

    _row_info: Union[DeploymentRow, StatefulSetRow, DaemonSetRow]

    def can_perform(
        self, row_info: Union[DeploymentRow, StatefulSetRow, DaemonSetRow]
    ) -> bool:
        """
        For simplicity, we'll always allow restart.
        A more complex check could see if a rollout is already in progress.
        """
        return True

    async def execute(
        self, row_info: Union[DeploymentRow, StatefulSetRow, DaemonSetRow]
    ) -> None:
        """Restart the workload by patching the pod template annotations."""
        self._row_info = row_info

        try:
            log.debug("Restarting workload %s", self._row_info.name)

            restarted_at = datetime.utcnow().isoformat() + "Z"
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": restarted_at
                            }
                        }
                    }
                }
            }

            patch_workload_method, kwargs = (
                self.app.kubernetes_client.get_api_method_for_resource(
                    model_class=type(self._row_info),
                    action="patch",
                    namespace=self._row_info.namespace,
                )
            )

            kwargs["name"] = self._row_info.name
            kwargs["body"] = body

            await patch_workload_method(**kwargs)

            self.app.notify(
                f"✅ Successfully restarted workload '{self._row_info.name}'.",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to restart workload '{self._row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")


@supports_resources("deployments", "statefulsets")
class WorkloadsScaleAction(BaseAction[DeploymentRow | StatefulSetRow]):
    """An action to scale a workload."""

    name = "Scale"

    _row_info: Union[DeploymentRow, StatefulSetRow]

    async def execute(self, row_info: Union[DeploymentRow, StatefulSetRow]) -> None:
        """Scale the workload by patching the replicas field."""
        self._row_info = row_info

        async def on_submit(results: dict[str, str] | None) -> None:
            if not results:
                return
            if results["replicas"] != str(self._row_info.replicas):
                await self._scale_resource(int(results["replicas"]))

        inputs = [
            InputInfo(
                name="replicas",
                label="Desired number of replicas:",
                initial_value=str(self._row_info.replicas),
            )
        ]

        await self.app.push_screen(
            InputScreen(
                title=f"Scale {self._row_info.kind} {self._row_info.name}/{self._row_info.namespace}",
                inputs=inputs,
                static_text=f"Current replicas: {self._row_info.replicas}",
                confirm_button_text="Scale",
            ),
            on_submit,
        )

    async def _scale_resource(self, replicas: int) -> None:
        """The actual logic to scale the resource."""
        try:
            log.debug(
                "Scaling workload %s to %d replicas", self._row_info.name, replicas
            )

            patch_workload_method, kwargs = (
                self.app.kubernetes_client.get_api_method_for_resource(
                    model_class=type(self._row_info),
                    action="patch",
                    namespace=self._row_info.namespace,
                )
            )

            body = {"spec": {"replicas": replicas}}

            kwargs["name"] = self._row_info.name
            kwargs["body"] = body

            await patch_workload_method(**kwargs)

            self.app.notify(
                f"✅ Successfully scaled workload {self._row_info.name} to {replicas} replicas.",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to scale workload '{self._row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
