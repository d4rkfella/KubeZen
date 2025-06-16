from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging
import yaml
import time
import asyncio
from kubernetes_asyncio.client.exceptions import ApiException

from .base_action import BaseAction
from ..screens.input_screen import InputScreen

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp
    from ..core.kubernetes_client import KubernetesClient
    from ..core.tmux_manager import TmuxManager

log = logging.getLogger(__name__)

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
        - "--noauth"
        - "--database"
        - "/data/filebrowser.db"
      ports:
        - containerPort: 80
      volumeMounts:
        - mountPath: "/srv"
          name: "target-pvc"
        - mountPath: "/data"
          name: "fb-data"
      securityContext:
        runAsUser: {user_id}
        runAsGroup: {user_id}
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
  securityContext:
    runAsNonRoot: true
    fsGroup: {user_id}
    seccompProfile:
      type: "RuntimeDefault"
"""


class PVCFileBrowserAction(BaseAction):
    """
    An action to launch a web-based file browser for a PVC.
    """

    def __init__(
        self,
        app: KubeZenTuiApp,
        resource: dict[str, Any],
        object_name: str,
        resource_key: str,
    ):
        super().__init__(app, resource, object_name, resource_key)

    async def run(self) -> None:
        """
        Prompts for a local port and then orchestrates the file browser pod.
        """
        await self.app.push_screen(
            InputScreen(
                title="File Browser Port",
                prompt="Enter local port for port-forward (e.g., 8080):",
                initial_value="8080",
                callback=self._on_port_selected,
            )
        )

    async def _on_port_selected(self, port: str | None) -> None:
        """Callback executed after the user provides a port."""
        if not port or not port.isdigit():
            # TODO: Show error notification
            log.warning("Invalid port provided for file browser action.")
            self.app.pop_screen()  # Pop the input screen
            return

        # Pop the InputScreen and the ActionScreen
        self.app.pop_screen()
        self.app.pop_screen()

        pod_name = f"fb-{self.resource_name}-{int(time.time())}"

        try:
            self.app.notify(f"🚀 Deploying pod '{pod_name}'...", title="File Browser")
            await self._launch_file_browser_pod(pod_name, port)
        except Exception as e:
            message = f"Failed to launch file browser: {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error", timeout=10)
            await self._cleanup_pod(pod_name)

    async def _launch_file_browser_pod(self, pod_name: str, local_port: str) -> None:
        """Creates the pod, waits for it, and starts the port-forward script."""

        # 1. Create the pod manifest
        # Using 65532 (nobody) as a safe default UID.
        pod_manifest_str = POD_TEMPLATE.format(
            pod_name=pod_name, pvc_name=self.resource_name, user_id="65532"
        )
        pod_manifest = yaml.safe_load(pod_manifest_str)

        # 2. Create the pod
        if not self.client.core_v1:
            raise RuntimeError("CoreV1Api not initialized.")

        log.info(
            f"Creating file browser pod '{pod_name}' for PVC '{self.resource_name}'."
        )
        await self.client.core_v1.create_namespaced_pod(
            namespace=self.namespace, body=pod_manifest
        )

        # 3. Wait for the pod to be running
        log.info(f"Waiting for pod '{pod_name}' to be running.")
        await self._wait_for_pod_running(pod_name)
        log.info(f"Pod '{pod_name}' is running.")
        self.app.notify(
            f"Pod '{pod_name}' is running. Starting port-forward...",
            title="File Browser",
        )

        # 4. Start port-forwarding in a new tmux window
        script_path = "bin/pvc_file_browser.sh"  # Assuming it's in the project root
        command = f"{script_path} {self.namespace} {pod_name} {local_port} {self.resource_name}"

        log.info(f"Launching file browser script with command: {command}")
        await self.tmux_manager.launch_command_in_new_window(
            command=command,
            window_name=f"fb-{self.resource_name}",
            attach=True,
        )
        self.app.notify(
            f"🌐 Port forward active: http://localhost:{local_port}",
            title="File Browser",
            timeout=10,
        )

    async def _wait_for_pod_running(self, pod_name: str, timeout: int = 60) -> None:
        """Waits for the specified pod to enter the 'Running' phase."""
        if not self.client.core_v1 or not self.namespace:
            raise RuntimeError("Client or namespace not available for waiting.")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                pod_status = await self.client.core_v1.read_namespaced_pod_status(
                    name=pod_name, namespace=self.namespace
                )
                if pod_status.status.phase == "Running":
                    return
            except ApiException as e:
                # 404 means the pod might not have been created yet, keep trying
                if e.status != 404:
                    raise
            await asyncio.sleep(2)
        raise TimeoutError(f"Pod '{pod_name}' did not start within {timeout} seconds.")

    async def _cleanup_pod(self, pod_name: str) -> None:
        """Best-effort attempt to clean up the pod."""
        log.info(f"Cleaning up pod '{pod_name}' due to an error.")
        if not self.client.core_v1 or not self.namespace:
            return
        try:
            await self.client.core_v1.delete_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            self.app.notify(f"🧹 Cleaned up pod '{pod_name}'.", title="Cleanup")
        except ApiException:
            # Ignore if pod is already gone or other errors.
            pass
