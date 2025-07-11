from __future__ import annotations
from typing import TYPE_CHECKING

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.base import UIRow
from KubeZen.models.core import NodeRow
from KubeZen.screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from kubernetes.client.models import V1DeleteOptions, V1ObjectMeta

import logging

if TYPE_CHECKING:
    from KubeZen.app import KubeZenTuiApp


log = logging.getLogger(__name__)


@supports_resources("nodes")
class DrainNodeAction(BaseAction):
    """An action to drain a Kubernetes node."""

    name = "Drain"
    _row_info: NodeRow

    async def execute(self, row_info: NodeRow) -> None:

        self._row_info = row_info

        """Confirm and then drain the node."""
        prompt = (
            f"Are you sure you want to drain node '{row_info.name}'?\n\n"
            "This will cordon the node and evict all pods."
        )
        buttons = [
            ButtonInfo(label="Drain", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]
        screen = ConfirmationScreen(
            title="Confirm Drain", prompt=prompt, buttons=buttons
        )

        if not await self.app.push_screen_wait(screen):
            return

        try:
            log.info(f"Starting drain for node '{row_info.name}'")

            # 1. Cordon the node
            log.info(f"Cordoning node '{row_info.name}'")
            await self.app.kubernetes_client.CoreV1Api.patch_node(
                name=row_info.name, body={"spec": {"unschedulable": True}}
            )

            # 2. Get all pods on the node
            log.info(f"Getting pods on node '{row_info.name}'")
            field_selector = f"spec.nodeName={row_info.name}"
            pods = await self.app.kubernetes_client.CoreV1Api.list_pod_for_all_namespaces(
                field_selector=field_selector
            )

            # 3. Evict each pod
            log.info(
                f"Evicting {len(pods.items)} pods from node '{row_info.name}'"
            )
            for pod in pods.items:
                pod_name = pod.metadata.name
                namespace = pod.metadata.namespace
                log.debug(f"Evicting pod '{pod_name}' in namespace '{namespace}'")
                try:
                    await self.app.kubernetes_client.CoreV1Api.create_namespaced_pod_eviction(
                        name=pod_name,
                        namespace=namespace,
                        body={
                            "apiVersion": "policy/v1",
                            "kind": "Eviction",
                            "metadata": V1ObjectMeta(
                                name=pod_name, namespace=namespace
                            ),
                            "deleteOptions": V1DeleteOptions(
                                grace_period_seconds=60  # Default to 60s, can be configured
                            ),
                        },
                    )
                except Exception as e:
                    # Log and continue with other pods
                    log.error(
                        f"Failed to evict pod '{pod_name}' in '{namespace}': {e}",
                        exc_info=True,
                    )

            self.app.notify(
                f"✅ Successfully drained node '{row_info.name}'", title="Success"
            )

        except Exception as e:
            message = f"Failed to drain node '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")


@supports_resources("nodes")
class CordonNodeAction(BaseAction):
    """An action to cordon a Kubernetes node."""

    name = "Cordon"
    _row_info: NodeRow

    def can_perform(self, row_info: NodeRow) -> bool:
        """Only allow cordoning if the node is not already unschedulable."""
        # The `unschedulable` attribute on the row is a string representation.
        # The raw resource attribute `spec.unschedulable` is a boolean.
        return not row_info.raw.spec.unschedulable

    async def execute(self, row_info: NodeRow) -> None:
        """Cordon the node by setting spec.unschedulable to True."""
        self._row_info = row_info
        try:
            log.debug(f"Cordoning node '{row_info.name}'")

            await self.app.kubernetes_client.CoreV1Api.patch_node(
                name=row_info.name,
                body={"spec": {"unschedulable": True}},
            )

            self.app.notify(
                f"✅ Successfully cordoned node '{row_info.name}'",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to cordon node '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")


@supports_resources("nodes")
class UncordonNodeAction(BaseAction):
    """An action to uncordon a Kubernetes node."""

    name = "Uncordon"

    def can_perform(self, row_info: UIRow) -> bool:
        """Only allow uncordoning if the node is already unschedulable."""
        # The `unschedulable` attribute on the row is a string representation.
        # The raw resource attribute `spec.unschedulable` is a boolean.
        return bool(row_info.raw.spec.unschedulable)

    async def execute(self, row_info: UIRow) -> None:
        """Uncordon the node by setting spec.unschedulable to False."""
        try:
            log.debug(f"Uncordoning node '{row_info.name}'")

            # To uncordon, we patch `unschedulable` to False.
            # Using `None` might also work, but `False` is more explicit.
            await self.app.kubernetes_client.CoreV1Api.patch_node(
                name=row_info.name,
                body={"spec": {"unschedulable": False}},
            )

            self.app.notify(
                f"✅ Successfully uncordoned node '{row_info.name}'",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to uncordon node '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
