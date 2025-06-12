from __future__ import annotations
from typing import Optional, Dict, Any
import time
import asyncio

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.core.exceptions import (
    TmuxCommandInterruptedError,
    TmuxCommandFailedError,
    TmuxEnvironmentError,
    ActionFailedError,
    ActionCancelledError,
)


class DescribeResourceAction(Action):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        return context.raw_k8s_object is not None

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        resource_name = resource.get("metadata", {}).get("name")
        resource_kind = resource.get("kind")
        action_name = self.__class__.__name__

        # For cluster-scoped resources, namespace may be None
        namespace_for_command = resource.get("metadata", {}).get("namespace")

        context.logger.info(
            f"{action_name}: Calling describe_resource for {resource_kind} '{resource_name}' in namespace '{namespace_for_command}'"
        )

        if not resource_name or not resource_kind:
            msg = f"{action_name}: Resource metadata (name or kind) is missing."
            context.logger.error(msg)
            raise ActionFailedError(msg)

        if not context.kubernetes_client:
            raise ActionFailedError("KubernetesClient not available, cannot describe resource.")

        try:
            describe_output = await context.kubernetes_client.describe_resource(
                resource_type=resource_kind,
                name=resource_name,
                namespace=namespace_for_command,
            )
        except TmuxCommandFailedError as e:
            context.logger.error(f"{action_name}: Tmux command failed during describe: {e}")
            raise ActionFailedError(f"Failed to execute describe command: {str(e)}")
        except TmuxCommandInterruptedError:
            context.logger.info(f"{action_name}: Describe command was interrupted")
            raise ActionCancelledError("Describe operation was interrupted")
        except TmuxEnvironmentError as e:
            context.logger.error(f"{action_name}: Tmux environment error: {e}")
            raise ActionFailedError(f"Tmux environment error: {str(e)}")

        if not describe_output:
            describe_output = f"# Could not fetch description for {resource_kind}/{resource_name} in namespace {namespace_for_command}.\n# Check KubeZen logs for details."
            # Even if the command fails, we can display the error message in the pager.
            # command_to_page = f"echo {shlex.quote(describe_output)}"
        else:
            # The client returns the full describe output, so we echo it into the pager.
            # command_to_page = f"echo {shlex.quote(describe_output)}"
            pass

        # Use the new robust method to display the output in a pager window
        try:
            # Create a unique task name using timestamp
            task_name = f"Describe_{resource_kind}_{resource_name}_{int(time.time())}"
            asyncio.create_task(
                context.tmux_ui_manager.display_text_in_new_window(
                    text=describe_output,
                    window_name=task_name,
                    pager_command="less -R",  # Static content, no follow mode needed
                    attach=True,
                )
            )
        except TmuxCommandFailedError as e:
            context.logger.error(f"{action_name}: Failed to display in pager: {e}")
            raise ActionFailedError(f"Failed to display resource description: {str(e)}")
        except TmuxCommandInterruptedError:
            context.logger.info(f"{action_name}: Pager display was interrupted")
            raise ActionCancelledError("Resource description display was interrupted")
        except TmuxEnvironmentError as e:
            context.logger.error(f"{action_name}: Tmux environment error in pager: {e}")
            raise ActionFailedError(f"Failed to display description due to tmux error: {str(e)}")

        context.logger.info(
            f"{action_name}: Describe action for {resource_kind} '{resource_name}' completed."
        )

        return StaySignal()
