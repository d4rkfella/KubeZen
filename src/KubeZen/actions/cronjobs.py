from __future__ import annotations
import logging
import time

from kubernetes_asyncio.client import V1Job, V1ObjectMeta

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.batch import CronJobRow
from KubeZen.screens.input_screen import InputScreen, InputInfo

log = logging.getLogger(__name__)


@supports_resources("cronjobs")
class TriggerCronJobAction(BaseAction):
    """An action to manually trigger a CronJob."""

    name = "Trigger"

    async def execute(self, row_info: CronJobRow) -> None:
        """Shows an input screen to get a name for the new Job and triggers it."""

        default_job_name = f"{row_info.name}-{int(time.time())}"

        inputs = [
            InputInfo(
                name="job_name",
                label="Enter name for the new Job:",
                initial_value=default_job_name,
            )
        ]

        results = await self.app.push_screen_wait(
            InputScreen(
                title=f"Trigger CronJob: {row_info.name}",
                inputs=inputs,
            )
        )

        if results is None:
            self.app.notify("Action cancelled.", severity="error")
            return

        job_name = results.get("job_name") or default_job_name

        await self._trigger_job(row_info, job_name)

    async def _trigger_job(self, row_info: CronJobRow, job_name: str) -> None:
        """Creates a Job from the CronJob's template."""
        try:
            cronjob = row_info.raw
            job_spec = cronjob.spec.job_template.spec

            # Create the Job object
            job = V1Job(
                api_version="batch/v1",
                kind="Job",
                metadata=V1ObjectMeta(
                    name=job_name,
                    namespace=row_info.namespace,
                    labels=(
                        cronjob.spec.job_template.metadata.labels
                        if cronjob.spec.job_template.metadata
                        else None
                    ),
                    annotations=(
                        cronjob.spec.job_template.metadata.annotations
                        if cronjob.spec.job_template.metadata
                        else {}
                    ),
                ),
                spec=job_spec,
            )
            # Add an annotation to show this was a manual trigger
            if job.metadata.annotations is None:
                job.metadata.annotations = {}
            job.metadata.annotations["cronjob.kubernetes.io/instantiate"] = "manual"

            await self.app.kubernetes_client.BatchV1Api.create_namespaced_job(
                namespace=row_info.namespace,
                body=job,
            )

            self.app.notify(
                f"✅ Successfully triggered Job '{job_name}' from CronJob '{row_info.name}'.",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to trigger CronJob '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")


@supports_resources("cronjobs")
class SuspendCronJobAction(BaseAction):
    """An action to suspend a CronJob."""

    name = "Suspend"

    def can_perform(self, row_info: CronJobRow) -> bool:
        """Only allow suspending if the CronJob is not already suspended."""
        return not row_info.raw.spec.suspend

    async def execute(self, row_info: CronJobRow) -> None:
        """Suspend the CronJob by setting spec.suspend to True."""
        try:
            log.debug(f"Suspending CronJob '{row_info.name}'")

            await self.app.kubernetes_client.BatchV1Api.patch_namespaced_cron_job(
                name=row_info.name,
                namespace=row_info.namespace,
                body=({"spec": {"suspend": True}}),
            )

            self.app.notify(
                f"✅ Successfully suspended CronJob '{row_info.name}'.",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to suspend CronJob '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")


@supports_resources("cronjobs")
class ResumeCronJobAction(BaseAction[CronJobRow]):
    """An action to resume a CronJob."""

    name = "Resume"

    def can_perform(self, row_info: CronJobRow) -> bool:
        """Only allow resuming if the CronJob is suspended."""
        return bool(row_info.raw.spec.suspend)

    async def execute(self, row_info: CronJobRow) -> None:
        """Resume the CronJob by setting spec.suspend to False."""
        try:
            log.debug(f"Resuming CronJob '{row_info.name}'")

            await self.app.kubernetes_client.BatchV1Api.patch_namespaced_cron_job(
                name=row_info.name,
                namespace=row_info.namespace,
                body={"spec": {"suspend": False}},
            )

            self.app.notify(
                f"✅ Successfully resumed CronJob '{row_info.name}'.",
                title="Success",
            )
        except Exception as e:
            message = f"Failed to resume CronJob '{row_info.name}': {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error")
