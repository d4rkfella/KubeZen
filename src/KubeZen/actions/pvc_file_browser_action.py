from __future__ import annotations
import logging
import time
import asyncio
from kubernetes_asyncio.client.exceptions import ApiException

from KubeZen.actions.base_action import BaseAction, supports_resources
from KubeZen.models.base import UIRow
from KubeZen.screens.input_screen import InputScreen, InputInfo


log = logging.getLogger(__name__)


def _create_pod_definition(pod_name: str, pvc_name: str, user_id: str) -> dict:
    """Creates the dictionary definition for the file browser pod."""
    # Truncate pvc_name for the label to respect Kubernetes 63-char limit
    pvc_label = pvc_name[:63]

    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {"app": "filebrowser", "pvc": pvc_label},
        },
        "spec": {
            "volumes": [
                {
                    "name": "target-pvc",
                    "persistentVolumeClaim": {"claimName": pvc_name},
                },
                {"name": "fb-data", "emptyDir": {}},
                {"name": "fb-config", "emptyDir": {}},
            ],
            "containers": [
                {
                    "name": "filebrowser",
                    "image": "filebrowser/filebrowser:latest",
                    "args": ["--noauth", "--database", "/data/filebrowser.db"],
                    "ports": [{"containerPort": 80}],
                    "volumeMounts": [
                        {"mountPath": "/srv", "name": "target-pvc"},
                        {"mountPath": "/data", "name": "fb-data"},
                        {"mountPath": "/config", "name": "fb-config"},
                    ],
                    "securityContext": {
                        "runAsUser": int(user_id),
                        "runAsGroup": int(user_id),
                        "readOnlyRootFilesystem": True,
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                }
            ],
            "securityContext": {
                "runAsNonRoot": True,
                "fsGroup": int(user_id),
                "seccompProfile": {"type": "RuntimeDefault"},
            },
        },
    }


@supports_resources("persistentvolumeclaims")
class PVCFileBrowserAction(BaseAction):
    """
    An action to launch a web-based file browser for a PVC.
    """

    name = "Browse Files"

    _row_info: UIRow

    async def execute(self, row_info: UIRow) -> None:
        self._row_info = row_info

        def on_submit(results: dict[str, str] | None) -> None:
            """Callback executed after the user provides input."""
            if not results:
                return  # User cancelled

            port = results.get("port")
            user_id = results.get("user_id", "65532")

            if not port or not port.isdigit():
                self.app.notify("Invalid port provided.", severity="error")
                return

            if not user_id or not user_id.isdigit():
                self.app.notify("Invalid user ID provided.", severity="error")
                return

            pod_name = f"fb-{row_info.name}-{int(time.time())}"
            self.app.run_worker(
                self._launch_file_browser_pod(pod_name, port, user_id),
                exclusive=True,
                group="pvc_file_browser",
            )

        inputs_to_request = [
            InputInfo(name="port", label="Local Port", initial_value="8080"),
            InputInfo(
                name="user_id", label="User ID (for fsGroup)", initial_value="65532"
            ),
        ]

        self.app.push_screen(
            InputScreen(
                title="File Browser Options",
                inputs=inputs_to_request,
            ),
            on_submit,
        )

    async def _launch_file_browser_pod(
        self, pod_name: str, local_port: str, user_id: str
    ) -> None:
        """Creates the pod, waits for it, and starts the port-forward script."""
        try:
            self.app.notify(f"🚀 Deploying pod '{pod_name}'...", title="File Browser")
            pod_manifest = _create_pod_definition(
                pod_name, self._row_info.name, user_id
            )

            log.info(
                f"Creating file browser pod '{pod_name}' for PVC '{self._row_info.name}'."
            )
            await self.app.kubernetes_client.CoreV1Api.create_namespaced_pod(
                namespace=self._row_info.namespace, body=pod_manifest
            )

            # Wait for the pod to be running
            log.info(f"Waiting for pod '{pod_name}' to be running.")
            self.app.notify(
                f"Waiting for pod '{pod_name}' to be running.", title="File Browser"
            )
            await self._wait_for_pod_running(pod_name)
            log.info(f"Pod '{pod_name}' is running.")
            self.app.notify(
                f"Pod '{pod_name}' is running. Starting port-forward...",
                title="File Browser",
            )

            # Start port-forwarding in a new tmux window
            script_path = "bin/pvc_file_browser.sh"
            command = f"{script_path} {self._row_info.namespace} {pod_name} {local_port} {self._row_info.name}"

            log.info(f"Launching file browser script with command: {command}")
            await self.app.tmux_manager.launch_command_in_new_window(
                command=command,
                window_name=f"fb-{self._row_info.name}",
            )
            self.app.notify(
                f"🌐 Port forward active: http://localhost:{local_port}",
                title="File Browser",
                timeout=5,
            )
        except Exception as e:
            message = f"Failed to launch file browser: {e}"
            log.error(message, exc_info=True)
            self.app.notify(message, title="Error", severity="error", timeout=10)
            await self._cleanup_pod(pod_name)

    async def _wait_for_pod_running(self, pod_name: str, timeout: int = 60) -> None:
        """
        Waits for the specified pod to be in the 'Running' phase and for all its
        containers to be ready.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                pod = await self.app.kubernetes_client.CoreV1Api.read_namespaced_pod(
                    name=pod_name, namespace=self._row_info.namespace
                )
                # Check 1: Pod phase must be 'Running'
                if pod.status.phase == "Running":
                    # Check 2: All containers must be ready
                    if pod.status.container_statuses and all(
                        cs.ready for cs in pod.status.container_statuses
                    ):
                        return
            except ApiException as e:
                if e.status != 404:
                    log.error(f"API error waiting for pod: {e}")
                    raise
            await asyncio.sleep(2)
        raise TimeoutError(
            f"Pod '{pod_name}' did not become ready within {timeout} seconds."
        )

    async def _cleanup_pod(self, pod_name: str) -> None:
        """Best-effort attempt to clean up the pod."""
        log.info(f"Cleaning up pod '{pod_name}' due to an error.")
        try:
            await self.app.kubernetes_client.CoreV1Api.delete_namespaced_pod(
                name=pod_name, namespace=self._row_info.namespace
            )
            self.app.notify(f"🧹 Cleaned up pod '{pod_name}'.", title="Cleanup")
        except ApiException:
            pass
