from __future__ import annotations

from typing import Optional, Any, TYPE_CHECKING, List, Dict
from kubernetes_asyncio.client import AppsV1Api
import logging
import datetime
from zoneinfo import ZoneInfo
import asyncio


if TYPE_CHECKING:
    from .base import KubernetesClient


class WorkloadsMixin:
    _apps_v1_api: Optional[AppsV1Api] = None
    logger: logging.Logger
    app_services: Any = None  # This will be set by the parent class

    # Temporarily removing broken methods until their dependencies can be restored.
    pass

    async def get_workloads_in_namespace(
        self: "KubernetesClient", namespace: str
    ) -> List[Dict[str, Any]]:
        # ... implementation ...
        return []

    async def scale_resource(
        self: "KubernetesClient",
        resource_type: str,
        namespace: str,
        name: str,
        replicas: int,
    ) -> None:
        """
        Scales a resource to the specified number of replicas.
        """
        if not self._apps_v1_api:
            raise RuntimeError("AppsV1Api not initialized.")

        scale_body = {
            "spec": {"replicas": replicas},
            "metadata": {"name": name, "namespace": namespace},
        }

        if resource_type == "Deployment":
            await self._apps_v1_api.patch_namespaced_deployment_scale(
                name=name, namespace=namespace, body=scale_body
            )
        elif resource_type == "StatefulSet":
            await self._apps_v1_api.patch_namespaced_stateful_set_scale(
                name=name, namespace=namespace, body=scale_body
            )
        elif resource_type == "ReplicaSet":
            await self._apps_v1_api.patch_namespaced_replica_set_scale(
                name=name, namespace=namespace, body=scale_body
            )
        else:
            raise ValueError(f"Scaling not supported for resource type: {resource_type}")

        if self.logger:
            self.logger.info(
                f"Successfully initiated scaling for {resource_type} '{name}' in namespace '{namespace}' to {replicas} replicas."
            )

    async def restart_deployment_rollout(
        self: "KubernetesClient",
        namespace: str,
        name: str,
    ) -> None:
        """
        Triggers a rolling restart of a deployment by setting an annotation.
        """
        if not self._apps_v1_api:
            raise RuntimeError("AppsV1Api not initialized.")

        now = datetime.datetime.now(ZoneInfo("UTC")).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        await self._apps_v1_api.patch_namespaced_deployment(
            name=name, namespace=namespace, body=body
        )

        if self.logger:
            self.logger.info(
                f"Successfully triggered rollout restart for Deployment '{name}' in namespace '{namespace}'."
            )

    async def get_deployment_rollout_history(
        self: "KubernetesClient",
        namespace: str,
        name: str,
    ) -> List[Dict[str, Any]]:
        """
        Gets the rollout history for a deployment by fetching its ReplicaSets.
        """
        if not self._apps_v1_api:
            raise RuntimeError("AppsV1Api not initialized.")

        deployment = await self._apps_v1_api.read_namespaced_deployment(name=name, namespace=namespace)
        selector = deployment.spec.selector
        label_selector = ",".join([f"{k}={v}" for k, v in selector.match_labels.items()])

        replicasets = await self._apps_v1_api.list_namespaced_replica_set(
            namespace=namespace, label_selector=label_selector
        )

        history = []
        for rs in replicasets.items:
            revision = rs.metadata.annotations.get("deployment.kubernetes.io/revision")
            if revision and revision.isdigit():
                history.append(
                    {
                        "revision": int(revision),
                        "spec": rs.spec.template.spec.to_dict(),
                        "change_cause": rs.metadata.annotations.get("kubernetes.io/change-cause", "<none>")
                    }
                )
        
        # Sort by revision number, descending
        history.sort(key=lambda x: x["revision"], reverse=True)
        return history

    async def rollback_deployment_to_revision(
        self: "KubernetesClient",
        namespace: str,
        name: str,
        revision: int,
    ) -> None:
        """
        Rolls back a deployment to a specific revision using kubectl.
        """
        command = ["kubectl", "rollout", "undo", "deployment", name, f"--to-revision={revision}", "--namespace", namespace]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise Exception(f"kubectl error: {stderr.decode().strip()}")
