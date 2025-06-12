from __future__ import annotations
from typing import Optional, Dict, Any
import time
import asyncio
import yaml
import os
from kubernetes_asyncio.client.exceptions import ApiException

from KubeZen.core.actions import Action
from KubeZen.core.contexts import ActionContext
from KubeZen.core.signals import NavigationSignal, StaySignal
from KubeZen.core.exceptions import ActionFailedError, UserInputCancelledError
from KubeZen.core.user_input_manager import InputSpec

# Define the pod template in a multi-line string
POD_TEMPLATE = """
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
  labels:
    app: filebrowser
    pvc: {pvc_name}
spec:
  volumes:
    - name: target-pvc
      persistentVolumeClaim:
        claimName: {pvc_name}
    - name: fb-data
      emptyDir: {{}}
  containers:
    - name: filebrowser
      image: filebrowser/filebrowser:latest
      args:
        - "--database"
        - "/data/filebrowser.db"
      ports:
        - containerPort: 80
      volumeMounts:
        - mountPath: "/srv"
          name: target-pvc
        - mountPath: "/data"
          name: "fb-data"
      securityContext:
        runAsUser: {user_id}
        runAsGroup: {user_id}
        fsGroup: {user_id}
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - "ALL"
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: "RuntimeDefault"
"""

def validate_port(port_str: str):
    """Validator to ensure input is a valid port number."""
    if not port_str.isdigit():
        raise ValueError("Port must be a number.")
    port = int(port_str)
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")

def validate_user_id(uid_str: str):
    """Validator to ensure input is a valid numeric user ID."""
    if not uid_str.isdigit():
        raise ValueError("User ID must be a number.")

class PVCBrowserAction(Action):
    def is_applicable(self, context: ActionContext) -> bool:
        resource = context.raw_k8s_object
        return bool(resource and resource.get("kind") == "PersistentVolumeClaim")

    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        pvc_name = resource.get("metadata", {}).get("name")
        namespace = resource.get("metadata", {}).get("namespace")

        if not pvc_name or not namespace:
            raise ActionFailedError("PVC name or namespace is missing.")

        # 1. Prompt for user input
        try:
            input_specs = [
                InputSpec(
                    result_key="local_port",
                    prompt_message="Enter local port for port-forward (e.g., 8080): ",
                    default_value="8080",
                    validator=validate_port,
                    validation_error_message="Invalid local port."
                ),
                InputSpec(
                    result_key="user_id",
                    prompt_message="Enter user ID to run pod as (default: 65532): ",
                    default_value="65532",
                    validator=validate_user_id,
                    validation_error_message="Invalid user ID."
                ),
            ]
            results = await context.user_input_manager.get_multiple_inputs(
                input_specs, task_name="File Browser Options"
            )
            local_port = results["local_port"]
            user_id = results["user_id"]
        except UserInputCancelledError:
            return StaySignal()

        # 2. Prepare the pod manifest
        pod_name = f"filebrowser-{pvc_name}-{int(time.time())}"
        pod_manifest_str = POD_TEMPLATE.format(
            pod_name=pod_name, pvc_name=pvc_name, user_id=user_id
        )
        pod_manifest = yaml.safe_load(pod_manifest_str)

        # 3. Create the pod
        try:
            if not context.kubernetes_client or not context.kubernetes_client._core_v1_api:
                raise ActionFailedError("Kubernetes API client not available.")

            await context.kubernetes_client._core_v1_api.create_namespaced_pod(
                namespace=namespace, body=pod_manifest
            )
            await context.tmux_ui_manager.show_toast(f"🚀 Deploying pod '{pod_name}'...")

            # 4. Wait for the pod to be running
            timeout = 60
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not context.kubernetes_client or not context.kubernetes_client._core_v1_api:
                    raise ActionFailedError("Kubernetes API client not available during wait.")
                pod_status = (
                    await context.kubernetes_client._core_v1_api.read_namespaced_pod_status(
                        name=pod_name, namespace=namespace
                    )
                )
                if pod_status.status.phase == "Running":
                    break
                await asyncio.sleep(2)
            else:
                raise ActionFailedError(f"Pod '{pod_name}' did not start in time.")

            await context.tmux_ui_manager.show_toast(
                f"Pod '{pod_name}' is running.", bg_color="green", fg_color="white"
            )

            # 5. Start port-forwarding in a new tmux window with cleanup
            if not os.path.exists(context.config.pvc_file_browser_script_path):
                raise ActionFailedError(
                    f"File browser script not found at {context.config.pvc_file_browser_script_path}"
                )

            command = [
                str(context.config.pvc_file_browser_script_path),
                namespace,
                pod_name,
                local_port,
                pvc_name,
            ]

            await context.tmux_ui_manager.launch_command_in_new_window(
                command_str=command,
                window_name=f"File Browser: {pvc_name}",
                attach=True,
                set_remain_on_exit=False,  # Let the script handle exit
            )

            await context.tmux_ui_manager.show_toast(
                f"🌐 Port forward active: http://localhost:{local_port}",
                bg_color="blue",
                fg_color="white",
                duration=10,
            )

        except ApiException as e:
            # If something fails, try to clean up the pod we might have created
            await self._cleanup_pod(context, pod_name, namespace)
            raise ActionFailedError(f"API Error: {e.reason}")
        except Exception as e:
            await self._cleanup_pod(context, pod_name, namespace)
            raise ActionFailedError(f"Failed to start file browser: {e}")

        return StaySignal()

    async def _cleanup_pod(self, context: ActionContext, pod_name: str, namespace: str) -> None:
        """Best-effort attempt to clean up the pod."""
        try:
            if context.kubernetes_client and context.kubernetes_client._core_v1_api:
                await context.kubernetes_client._core_v1_api.delete_namespaced_pod(
                    name=pod_name, namespace=namespace
                )
                await context.tmux_ui_manager.show_toast(f"🧹 Cleaned up pod '{pod_name}'.")
        except ApiException:
            pass
