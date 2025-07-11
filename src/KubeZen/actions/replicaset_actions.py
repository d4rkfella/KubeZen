from __future__ import annotations
from typing import TYPE_CHECKING
import logging

from kubernetes_asyncio.client import V1Deployment, V1DeploymentSpec

from .base_action import BaseAction, supports_resources
from ..models.apps import ReplicaSetRow, DeploymentRow
from ..models.base import UIRow
from ..screens.confirmation_screen import ConfirmationScreen, ButtonInfo
from ..screens.input_screen import InputScreen, InputInfo

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp


log = logging.getLogger(__name__)


@supports_resources("replicasets")
class ReplicaSetScaleAction(BaseAction):
    """An action to scale a ReplicaSet."""

    name = "Scale"

    _row_info: ReplicaSetRow

    def can_perform(self, row_info: ReplicaSetRow) -> bool:
        """
        Only allow rollback if the ReplicaSet is inactive and owned by a Deployment.
        """
        # Ensure it's a ReplicaSetRow
        if not isinstance(row_info, ReplicaSetRow):
            return False

        # Must be owned by a deployment to find the parent
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
                api_client = getattr(self.app.kubernetes_client, self._row_info.api_info.client_name)
                read_method = getattr(api_client, "read_namespaced_deployment")
                patch_method = getattr(api_client, "patch_namespaced_deployment")

                parent_deployment = await read_method(
                    name=deployment_name,
                    namespace=self._row_info.namespace
                )

                patch_body = V1Deployment(
                    spec=V1DeploymentSpec(
                        selector=parent_deployment.spec.selector,
                        template=self._row_info.raw.spec.template
                    )
                )

                await patch_method(
                    name=deployment_name,  # The name of the PARENT deployment
                    namespace=self._row_info.namespace,
                    body=patch_body,
                )
                self.app.notify(f"Deployment {deployment_name} is rolling back to the selected revision.")

            except StopIteration:
                message = (
                    f"Could not find a Deployment owner for ReplicaSet %s.",
                    self._row_info.name,
                )
                self.app.notify(message, title="Error", severity="error")

            except Exception as e:
                message = f"Failed to scale ReplicaSet %s: %s", self._row_info, e
                log.error(message, exc_info=True)
                self.app.notify(message, title="Error", severity="error")
