from __future__ import annotations
from typing import Optional, Dict, Any
import shlex
import asyncio
import re
import tempfile
import os
from pathlib import Path

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.exceptions import (
    ActionFailedError,
    UserInputCancelledError,
    UserInputFailedError,
)
from KubeZen.core.user_input_manager import InputSpec
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.actions.action_utils import select_container_if_needed


def validate_yes_no(input_str: str) -> None:
    """Validator to ensure input is 'y' or 'n'."""
    if input_str.lower().strip() not in ["y", "n"]:
        raise ValueError("Please enter 'y' or 'n'.")

def validate_positive_integer(input_str: str) -> None:
    """Validator to ensure input is a positive integer."""
    if not input_str.isdigit() or int(input_str) <= 0:
        raise ValueError("Please enter a positive number.")

def validate_duration(input_str: str) -> None:
    """Validator to ensure input is a valid duration string (e.g., 5m, 2h, 10s) or empty."""
    if not input_str:  # Allow empty string
        return
    if not re.match(r"^\d+[smh]$", input_str):
        raise ValueError("Invalid duration format. Use formats like 10s, 5m, 2h.")

class ViewLogsAction(Action):
    ALL_CONTAINERS_CODE = "All Containers"
    APPLICABLE_KINDS = {"Pod", "Deployment", "StatefulSet", "ReplicaSet"}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        """
        This action is applicable if the resource is a Pod or a scalable workload.
        """
        resource = context.raw_k8s_object
        if not resource:
            return False
        
        kind = resource.get("kind")
        return kind in self.APPLICABLE_KINDS

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        action_name = self.__class__.__name__
        metadata = resource.get("metadata", {})
        if not metadata:
            raise ActionFailedError(f"{action_name}: Resource metadata is missing.")

        resource_name = metadata.get("name")
        namespace = metadata.get("namespace")
        kind = resource.get("kind")

        if not all([resource_name, namespace, kind]):
            raise ActionFailedError(f"{action_name}: Resource name, namespace, or kind is missing.")

        context.logger.debug(
            f"[{action_name}] Initiating 'View Logs' for {kind} '{namespace}/{resource_name}'"
        )
        
        # --- Step 1: Handle Pods (with container selection) vs Workloads ---
        if kind == "Pod":
            return await self._execute_for_pod(context, resource)
        else:
            return await self._execute_for_workload(context, resource)

    async def _execute_for_pod(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        pod_name = resource.get("metadata", {}).get("name")
        namespace = resource.get("metadata", {}).get("namespace")

        # Container selection logic
        selection_signal = await select_container_if_needed(self, context, resource, only_running=False)
        if selection_signal:
            if selection_signal.context and "container_names" in selection_signal.context:
                selection_signal.context["container_names"].insert(0, self.ALL_CONTAINERS_CODE)
            return selection_signal

        selected_container = context.custom_data.get("selected_container_name")
        if not selected_container:
            raise ActionFailedError("Could not determine container for logs.")

        is_all_containers = selected_container == self.ALL_CONTAINERS_CODE
        log_target_name = "all containers" if is_all_containers else f"container '{selected_container}'"

        # Construct kubectl command parts
        command_parts = ["kubectl", "logs", pod_name, "--namespace", namespace]
        if is_all_containers:
            command_parts.append("--all-containers")
        else:
            command_parts.extend(["--container", selected_container])
        
        # Get log options from user, then display
        return await self._get_options_and_display_logs(context, command_parts, log_target_name)


    async def _execute_for_workload(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        resource_name = resource.get("metadata", {}).get("name")
        namespace = resource.get("metadata", {}).get("namespace")
        
        # Get the label selector for the workload
        selector = resource.get("spec", {}).get("selector", {})
        match_labels = selector.get("matchLabels")
        if not match_labels:
            raise ActionFailedError(f"Cannot get logs for '{resource_name}': no selector found.")

        label_selector_str = ",".join([f"{k}={v}" for k, v in match_labels.items()])
        log_target_name = f"pods with selector '{label_selector_str}'"
        
        # Construct kubectl command parts
        command_parts = [
            "kubectl", 
            "logs", 
            f"--selector={label_selector_str}", 
            "--namespace", 
            namespace, 
            "--all-containers"
        ]

        # Get log options from user, then display
        return await self._get_options_and_display_logs(context, command_parts, log_target_name, allow_follow=False)


    async def _get_options_and_display_logs(
        self,
        context: ActionContext,
        base_command_parts: list[str],
        log_target_name: str,
        allow_follow: bool = True,
    ) -> Optional[NavigationSignal]:
        try:
            input_specs = [
                InputSpec(
                    result_key="tail_lines",
                    prompt_message="Tail lines (e.g., 500, default: all): ",
                    default_value="5000",
                    validator=validate_positive_integer,
                ),
                InputSpec(
                    result_key="previous",
                    prompt_message="View previous termination (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                ),
                InputSpec(
                    result_key="timestamps",
                    prompt_message="Add timestamps (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                ),
                InputSpec(
                    result_key="since",
                    prompt_message="Only logs since duration (e.g., 5m, 2h): ",
                    default_value="",
                    validator=validate_duration,
                ),
            ]

            if allow_follow:
                input_specs.insert(1, InputSpec(
                    result_key="follow",
                    prompt_message="Follow logs (y/n): ",
                    default_value="n",
                    validator=validate_yes_no,
                ))

            log_options = await context.user_input_manager.get_multiple_inputs(
                specs=input_specs, task_name=f"Log Options for {log_target_name}"
            )

            # --- Construct and execute the kubectl command ---
            final_command_parts = list(base_command_parts)

            if tail_lines := log_options.get("tail_lines"):
                final_command_parts.extend(["--tail", str(tail_lines)])
            
            should_follow = allow_follow and log_options.get("follow", "n").lower() == "y"
            if should_follow:
                final_command_parts.append("-f")

            if log_options.get("previous", "n").lower() == "y":
                final_command_parts.append("--previous")

            if log_options.get("timestamps", "n").lower() == "y":
                final_command_parts.append("--timestamps")
            
            if since := log_options.get("since"):
                final_command_parts.extend(["--since", since])

            final_log_command = " ".join(shlex.quote(part) for part in final_command_parts)

            # --- Create a temporary file for logs to enable fzf searching ---
            # The pager will read from this file. If following, a background
            # process will continuously write to it.
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
                log_file_path = temp_file.name

            # Start a background task to stream kubectl logs into the temp file
            log_process = await asyncio.create_subprocess_shell(
                final_log_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def stream_to_file(stream, file):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    file.write(line.decode())
                    file.flush()

            log_file_handle = open(log_file_path, "a")
            
            # Start streaming tasks
            stdout_task = asyncio.create_task(stream_to_file(log_process.stdout, log_file_handle))
            stderr_task = asyncio.create_task(stream_to_file(log_process.stderr, log_file_handle))

            # Brief delay to allow the first few log lines to be written to the file
            # This prevents the pager from opening an empty file initially.
            await asyncio.sleep(0.5)

            # --- Set up pager and fzf key bindings ---
            pager_command = f"less -j.5 -R -N {'+F' if should_follow else ''} {shlex.quote(log_file_path)}"

            key_bindings = None
            fzf_log_search_script = self.app_services.config.fzf_log_search_script_path
            if fzf_log_search_script:
                debug_log_path = "/tmp/fzf_search_errors.log"
                # Construct the command with a placeholder for the pane ID.
                # The UI manager will replace %TMUX_PANE% with the real ID.
                command = f"{shlex.quote(str(fzf_log_search_script))} {shlex.quote(log_file_path)} %TMUX_PANE% 2> {shlex.quote(debug_log_path)}"
                key_bindings = {"f2": command}
            else:
                context.logger.warning(
                    "fzf-log-search script not found, F2 binding will be disabled."
                )

            # Define the cleanup coroutine for file resources
            async def _cleanup_resources():
                context.logger.info(f"Cleaning up resources for log view of '{log_target_name}'")
                if log_process.returncode is None:
                    try:
                        log_process.terminate()
                        await log_process.wait()  # ensure it's terminated
                    except ProcessLookupError:
                        pass  # Process already finished

                # Wait for streaming tasks to finish processing any remaining output
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

                log_file_handle.close()

                try:
                    os.remove(log_file_path)
                except OSError as e:
                    context.logger.error(f"Error removing temp log file {log_file_path}: {e}")

            # Define the key unbinding coroutine
            async def _unbind_keys():
                if key_bindings:
                    context.logger.info("Unbinding keys for closed log viewer.")
                    await context.tmux_ui_manager.unbind_keys(list(key_bindings.keys()))
            
            # Non-blocking call to display logs
            await context.tmux_ui_manager.display_logs_in_pager(
                pager_command=pager_command,
                task_name=f"Logs: {log_target_name}",
                key_bindings=key_bindings,
                on_close_callbacks=[_cleanup_resources, _unbind_keys],
            )

        except (UserInputCancelledError, UserInputFailedError) as e:
            await context.tmux_ui_manager.show_toast(str(e), bg_color="blue")
        except ActionFailedError as e:
            context.logger.error(f"Action failed: {e}", exc_info=True)
            await context.tmux_ui_manager.show_toast(
                f"Error viewing logs: {e}", bg_color="red", duration=8
            )

        return StaySignal()
