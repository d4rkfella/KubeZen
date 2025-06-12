from __future__ import annotations
from typing import Optional, Dict, Any, List
import asyncio
import time

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.signals import NavigationSignal, StaySignal, PushViewSignal
from KubeZen.core.exceptions import ActionFailedError, UserInputCancelledError, UserInputFailedError
from KubeZen.core.user_input_manager import InputSpec
from KubeZen.ui.views.port_forward_view import PortForwardView


def validate_port(port_str: str) -> None:
    """Validator to ensure input is a valid port number."""
    if not port_str.isdigit():
        raise ValueError("Port must be a number.")
    port = int(port_str)
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")


class PortForwardAction(Action):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def is_applicable(self, context: ActionContext) -> bool:
        resource = context.raw_k8s_object
        if not resource:
            return False

        kind = resource.get("kind")
        return kind in ["Pod", "Service"]

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        action_name = self.__class__.__name__
        if not resource:
            raise ActionFailedError(f"{action_name}: Resource object is missing.")

        metadata = resource.get("metadata", {})
        if not metadata:
            raise ActionFailedError(f"{action_name}: Resource metadata is missing.")

        resource_name = metadata.get("name")
        namespace = metadata.get("namespace")
        kind = resource.get("kind")

        if not resource_name or not namespace or not kind:
            raise ActionFailedError(
                f"{action_name}: Resource name, namespace or kind is missing."
            )

        remote_port = None
        if context.custom_data:
            remote_port = context.custom_data.get("selected_remote_port")
        local_port = None

        if not remote_port:
            remote_ports = self._get_remote_ports(resource)
            if remote_ports:
                if context.custom_data is None:
                    context.custom_data = {}
                context.custom_data["provider"] = lambda _: [
                    {
                        "metadata": {"name": str(port)},
                        "spec": {"display_text": f"Port {port}"},
                    }
                    for port in remote_ports
                ]
                context.custom_data[
                    "header"
                ] = f"Select a remote port for {resource_name}"
                return PushViewSignal(
                    view_key="PortForwardView", context=context.to_dict()
                )
            else:
                try:
                    input_specs = [
                        InputSpec(
                            result_key="remote_port",
                            prompt_message="Enter remote port: ",
                            validator=validate_port,
                            validation_error_message="Invalid remote port.",
                        ),
                        InputSpec(
                            result_key="local_port",
                            prompt_message="Enter local port (or press Enter to use remote port): ",
                            validator=lambda p: validate_port(p) if p else None,
                            validation_error_message="Invalid local port.",
                        ),
                    ]
                    results = await context.user_input_manager.get_multiple_inputs(
                        specs=input_specs, task_name="Port Forward Options"
                    )
                    remote_port_str = results.get("remote_port")
                    local_port_str = results.get("local_port")

                    if not remote_port_str or not remote_port_str.isdigit():
                        raise ActionFailedError("Invalid remote port provided.")
                    remote_port = int(remote_port_str)

                    local_port = (
                        local_port_str
                        if local_port_str
                        else str(remote_port)
                    )

                except (UserInputCancelledError, UserInputFailedError):
                    return StaySignal()

        if remote_port and not local_port:
            try:
                local_port_spec = InputSpec(
                    result_key="local_port",
                    prompt_message="Enter local port: ",
                    default_value=str(remote_port),
                    validator=validate_port,
                    validation_error_message="Invalid local port.",
                )
                local_port_input = await context.user_input_manager.get_single_input(
                    prompt_text=local_port_spec.prompt_message,
                    initial_value=local_port_spec.default_value,
                )
                if local_port_input:
                    local_port = local_port_input

            except UserInputCancelledError:
                return StaySignal()

        if not local_port or not remote_port:
            raise ActionFailedError("Local or remote port not provided.")

        resource_identifier = (
            f"service/{resource_name}" if kind == "Service" else f"pod/{resource_name}"
        )

        port_forward_command = (
            f"kubectl port-forward --namespace {namespace} {resource_identifier} "
            f"{local_port}:{remote_port}"
        )

        task_name = f"PortForward_{namespace}_{resource_name}_{int(time.time())}"

        try:
            await context.tmux_ui_manager.launch_command_in_new_window(
                command_str=port_forward_command,
                window_name=task_name,
                attach=True,
                wait_for_completion=True,
            )
            await context.tmux_ui_manager.show_toast(
                f"Port-forwarding started for {resource_name} on local port {local_port}"
            )
        except Exception as e:
            # The error message from TmuxOperationError will contain the specific kubectl error
            context.logger.error(f"Port-forward failed with exception: {e}", exc_info=True)
            await context.tmux_ui_manager.show_toast(
                message=str(e),
                bg_color="red",
                fg_color="white",
                duration=8,
            )
            return StaySignal()

        return StaySignal()

    def _get_remote_ports(self, resource: Dict[str, Any]) -> List[int]:
        ports: List[int] = []
        spec = resource.get("spec", {})

        if resource.get("kind") == "Pod" and "containers" in spec:
            for container in spec.get("containers", []):
                for port_spec in container.get("ports", []):
                    if "containerPort" in port_spec:
                        ports.append(port_spec["containerPort"])
        elif resource.get("kind") == "Service" and "ports" in spec:
            for port_spec in spec.get("ports", []):
                if "port" in port_spec:
                    ports.append(port_spec["port"])
        return sorted(list(set(ports))) 