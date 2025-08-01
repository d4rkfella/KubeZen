from __future__ import annotations
import logging

from kubernetes_asyncio.client import V1Deployment, V1DeploymentSpec

from .base_action import BaseAction, supports_resources
from KubeZen.models.apps import ReplicaSetRow
from ..screens.confirmation_screen import ConfirmationScreen, ButtonInfo


log = logging.getLogger(__name__)


@supports_resources("replicasets")
class ReplicaSetRollbackAction(BaseAction):
    """An action to scale a ReplicaSet."""

    name = "Rollback"

    _row_info: ReplicaSetRow

    def can_perform(self, row_info: ReplicaSetRow) -> bool:
        """
        Only allow rollback if the ReplicaSet is inactive and owned by a Deployment.
        """
        if not any(
            owner.kind == "Deployment"
            for owner in (row_info.raw.metadata.owner_references or [])
        ):
            return False

        return True

    async def execute(self, row_info: ReplicaSetRow) -> None:
        self._row_info = row_info

        owner_ref = next(
            owner
            for owner in self._row_info.raw.metadata.owner_references
            if owner.kind == "Deployment"
        )
        deployment_name = owner_ref.name
        replicaset_name = self._row_info.name

        prompt = (
            f"Are you sure you want to roll back Deployment '{deployment_name}' "
            f"to the revision defined by ReplicaSet '{replicaset_name}'?"
        )

        buttons = [
            ButtonInfo(label="Rollback", result=True, variant="error"),
            ButtonInfo(label="Cancel", result=False, variant="primary"),
        ]

        screen = ConfirmationScreen(
            title="Confirm Rollback",
            prompt=prompt,
            buttons=buttons,
        )

        confirmed = await self.app.push_screen_wait(screen)

        if confirmed:
            try:
                parent_deployment = await self.app.kubernetes_client.AppsV1Api.read_namespaced_deployment(
                    name=deployment_name, namespace=self._row_info.namespace
                )

                patch_body = V1Deployment(
                    spec=V1DeploymentSpec(
                        selector=parent_deployment.spec.selector,
                        template=self._row_info.raw.spec.template,
                    )
                )

                await self.app.kubernetes_client.AppsV1Api.patch_namespaced_deployment(
                    name=deployment_name,  # The name of the PARENT deployment
                    namespace=self._row_info.namespace,
                    body=patch_body,
                )
                self.app.notify(
                    f"Deployment {deployment_name} is rolling back to the selected revision."
                )

            except StopIteration:
                self.app.notify(
                    f"Could not find a Deployment owner for ReplicaSet {self._row_info.name}.",
                    title="Error",
                    severity="error",
                )

            except Exception as e:
                self.app.notify(
                    f"Failed to scale ReplicaSet {self._row_info}: {e}",
                    title="Error",
                    severity="error",
                )
