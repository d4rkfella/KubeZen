from __future__ import annotations
from typing import Optional, Dict, Any
import asyncio

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import (
    TmuxCommandInterruptedError,
    TmuxCommandFailedError,
    TmuxEnvironmentError,
    ActionFailedError,
)
from KubeZen.core.signals import NavigationSignal, StaySignal
import time


class ViewYamlAction(Action):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        return context.raw_k8s_object is not None

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        resource_name = resource.get("metadata", {}).get("name")
        resource_kind = resource.get("kind")
        namespace_for_command = resource.get("metadata", {}).get("namespace")

        if not resource_name or not resource_kind:
            msg = "Resource metadata (name or kind) is missing."
            context.logger.error(msg)
            raise ActionFailedError(msg)

        action_name = self.__class__.__name__

        context.logger.debug(
            f"{action_name}: Handling 'View YAML' for {resource_kind} '{resource_name}' in namespace '{namespace_for_command}'"
        )

        yaml_output: Optional[str] = None

        try:
            context.logger.debug(
                f"{action_name}: Fetching resource YAML via client: {resource_kind} '{resource_name}' in ns '{namespace_for_command}'"
            )
            yaml_output = await context.kubernetes_client.get_resource_as_yaml(
                resource_type=resource_kind,
                namespace=namespace_for_command,
                name=resource_name,
            )

            if yaml_output is None:
                msg = f"# Could not fetch YAML for {resource_kind}/{resource_name} in namespace {namespace_for_command}.\n# Check KubeZen logs for details."
                context.logger.warning(f"{action_name}: {msg.replace('//n', ' ')}")
                yaml_output = msg

        except Exception as e_get_yaml:
            log_msg = f"Error calling get_resource_as_yaml for {resource_kind} '{resource_name}': {e_get_yaml}"
            context.logger.error(f"{action_name}: {log_msg}", exc_info=True)
            raise ActionFailedError(
                f"Failed to fetch YAML for {resource_kind}/{resource_name}."
            ) from e_get_yaml

        try:
            task_name = f"ViewYAML_{resource_kind}_{resource_name}_{int(time.time())}"

            asyncio.create_task(
                context.tmux_ui_manager.display_text_in_new_window(
                    text=yaml_output,
                    window_name=task_name,
                    pager_command="less -R",
                    attach=True,
                )
            )

            context.logger.info(
                f"{action_name}: ViewYAML action for {resource_kind} '{resource_name}' completed."
            )

        except (
            TmuxCommandFailedError,
            TmuxCommandInterruptedError,
            TmuxEnvironmentError,
        ) as e_tmux:
            log_msg = f"Tmux error during view YAML of {resource_kind} '{resource_name}': {e_tmux}"
            context.logger.error(f"{action_name}: {log_msg}", exc_info=True)
            raise ActionFailedError(
                f"Tmux error viewing YAML for {resource_kind}/{resource_name}."
            ) from e_tmux
        except Exception as e_general:
            log_msg = f"Unexpected error during view YAML of {resource_kind} '{resource_name}': {e_general}"
            context.logger.error(f"{action_name}: {log_msg}", exc_info=True)
            raise ActionFailedError(
                f"Unexpected error viewing YAML for {resource_kind}/{resource_name}."
            ) from e_general

        return StaySignal()
