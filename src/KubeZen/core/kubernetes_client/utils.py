from __future__ import annotations
from typing import Optional, Any, cast, TYPE_CHECKING
import yaml
import logging
from kubernetes_asyncio.client.rest import ApiException
from KubeZen.core.exceptions import K8sClientError

if TYPE_CHECKING:
    pass


class UtilsMixin:
    logger: logging.Logger
    app_services: Any = None  # This will be set by the parent class
    _core_v1_api: Any = None
    _apps_v1_api: Any = None
    _batch_v1_api: Any = None
    _networking_v1_api: Any = None
    last_api_error_body: Optional[str] = None

    async def get_namespaced_resource_object(
        self,
        resource_type_str: str,
        name: str,
        namespace: str,
    ) -> Any:
        logger = getattr(self, "logger", None) or getattr(self.app_services, "logger", None)
        core_v1_api = getattr(self, "_core_v1_api", None)
        apps_v1_api = getattr(self, "_apps_v1_api", None)
        batch_v1_api = getattr(self, "_batch_v1_api", None)
        networking_v1_api = getattr(self, "_networking_v1_api", None)
        api_method_map = {
            "pod": (core_v1_api, "read_namespaced_pod"),
            "pods": (core_v1_api, "read_namespaced_pod"),
            "deployment": (apps_v1_api, "read_namespaced_deployment"),
            "deployments": (apps_v1_api, "read_namespaced_deployment"),
            "service": (core_v1_api, "read_namespaced_service"),
            "services": (core_v1_api, "read_namespaced_service"),
            "configmap": (core_v1_api, "read_namespaced_config_map"),
            "configmaps": (core_v1_api, "read_namespaced_config_map"),
            "secret": (core_v1_api, "read_namespaced_secret"),
            "secrets": (core_v1_api, "read_namespaced_secret"),
            "persistentvolumeclaim": (core_v1_api, "read_namespaced_persistent_volume_claim"),
            "persistentvolumeclaims": (core_v1_api, "read_namespaced_persistent_volume_claim"),
            "statefulset": (apps_v1_api, "read_namespaced_stateful_set"),
            "statefulsets": (apps_v1_api, "read_namespaced_stateful_set"),
            "daemonset": (apps_v1_api, "read_namespaced_daemon_set"),
            "daemonsets": (apps_v1_api, "read_namespaced_daemon_set"),
            "job": (batch_v1_api, "read_namespaced_job"),
            "jobs": (batch_v1_api, "read_namespaced_job"),
            "cronjob": (batch_v1_api, "read_namespaced_cron_job"),
            "cronjobs": (batch_v1_api, "read_namespaced_cron_job"),
            "ingress": (networking_v1_api, "read_namespaced_ingress"),
            "ingresses": (networking_v1_api, "read_namespaced_ingress"),
        }
        normalized_resource_type = resource_type_str.lower()
        api_client_instance, method_name = api_method_map.get(normalized_resource_type, (None, ""))
        if not api_client_instance:
            if logger:
                logger.error(
                    f"No API client configured for resource type '{normalized_resource_type}' (original: '{resource_type_str}')."
                )
            return None
        if not hasattr(api_client_instance, method_name):
            if logger:
                logger.error(
                    f"API method '{method_name}' not found on client for resource type '{normalized_resource_type}'."
                )
            return None
        try:
            api_call = getattr(api_client_instance, method_name)
            resource_obj = await api_call(name=name, namespace=namespace)
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = None
            return resource_obj
        except Exception as e:
            if logger:
                logger.error(
                    f"Error fetching {normalized_resource_type} named '{name}' in namespace '{namespace}': {e}",
                    exc_info=True,
                )
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = str(e)
            return None

    async def get_cluster_scoped_resource_object(
        self,
        resource_type_str: str,
        name: str,
    ) -> Any:
        logger = getattr(self, "logger", None) or getattr(self.app_services, "logger", None)
        core_v1_api = getattr(self, "_core_v1_api", None)
        api_method_map = {
            "namespace": (core_v1_api, "read_namespace"),
            # Add more cluster-scoped resources as needed
        }
        normalized_resource_type = resource_type_str.lower()
        api_client_instance, method_name = api_method_map.get(normalized_resource_type, (None, ""))
        if not api_client_instance:
            if logger:
                logger.error(
                    f"No API client configured for cluster-scoped resource type '{normalized_resource_type}' (original: '{resource_type_str}')."
                )
            return None
        if not hasattr(api_client_instance, method_name):
            if logger:
                logger.error(
                    f"API method '{method_name}' not found on client for cluster-scoped resource type '{normalized_resource_type}'."
                )
            return None
        try:
            api_call = getattr(api_client_instance, method_name)
            resource_obj = await api_call(name=name)
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = None
            return resource_obj
        except Exception as e:
            if logger:
                logger.error(
                    f"Error fetching cluster-scoped {normalized_resource_type} named '{name}': {e}",
                    exc_info=True,
                )
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = str(e)
            return None

    async def delete_namespaced_resource(
        self,
        resource_type_str: str,
        name: str,
        namespace: str,
        delete_options: Any = None,
        grace_period_seconds: Any = None,
        propagation_policy: Any = None,
    ) -> bool:
        logger = getattr(self, "logger", None) or getattr(self.app_services, "logger", None)
        core_v1_api = getattr(self, "_core_v1_api", None)
        apps_v1_api = getattr(self, "_apps_v1_api", None)
        api_method_map = {
            "pod": (core_v1_api, "delete_namespaced_pod"),
            "deployment": (apps_v1_api, "delete_namespaced_deployment"),
            "service": (core_v1_api, "delete_namespaced_service"),
            # Add more as needed
        }
        normalized_resource_type = resource_type_str.lower()
        api_client_instance, method_name = api_method_map.get(normalized_resource_type, (None, ""))
        if not api_client_instance:
            if logger:
                logger.error(
                    f"No API client configured for resource type '{normalized_resource_type}' (original: '{resource_type_str}')."
                )
            return False
        if not hasattr(api_client_instance, str(method_name)):
            if logger:
                logger.error(
                    f"API method '{method_name}' not found on client for resource type '{normalized_resource_type}'."
                )
            return False
        try:
            api_call = getattr(api_client_instance, str(method_name))
            await api_call(
                name=name,
                namespace=namespace,
                body=delete_options,
                grace_period_seconds=grace_period_seconds,
                propagation_policy=propagation_policy,
            )
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = None
            return True
        except Exception as e:
            if logger:
                logger.error(
                    f"Error deleting {normalized_resource_type} named '{name}' in namespace '{namespace}': {e}",
                    exc_info=True,
                )
            if hasattr(self, "last_api_error_body"):
                self.last_api_error_body = str(e)
            return False

    def _extract_error_body(self, e: Exception) -> str:
        if hasattr(e, "body"):
            return str(getattr(e, "body"))
        return str(e)

    async def get_resource_as_yaml(
        self,
        resource_type: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        logger = getattr(self, "logger", None) or getattr(self.app_services, "logger", None)
        api_client = getattr(self, "_api_client", None)

        if not api_client:
            if logger:
                logger.error("ApiClient not initialized. Cannot fetch resource YAML.")
            return None

        resource_obj = None
        if namespace:
            resource_obj = await self.get_namespaced_resource_object(
                resource_type, name, namespace
            )
        else:
            resource_obj = await self.get_cluster_scoped_resource_object(resource_type, name)

        if not resource_obj:
            return None

        try:
            sanitized_data = api_client.sanitize_for_serialization(resource_obj)
            if "metadata" in sanitized_data and "managedFields" in sanitized_data["metadata"]:
                del sanitized_data["metadata"]["managedFields"]
            return cast(
                Optional[str], yaml.dump(sanitized_data, sort_keys=False, default_flow_style=False)
            )
        except Exception as e:
            if logger:
                logger.error(f"Failed to serialize resource object to YAML: {e}", exc_info=True)
            return None

    def sanitize_for_serialization(self, obj: Any) -> Any:
        """
        Sanitizes a Kubernetes API object for serialization by calling the
        underlying ApiClient's sanitize_for_serialization method.
        """
        if hasattr(self, "_api_client") and self._api_client:
            return self._api_client.sanitize_for_serialization(obj)
        return obj  # Fallback if no api_client is available

    async def replace_namespaced_resource(
        self,
        resource_type: str,
        name: str,
        namespace: str,
        body: Any,
    ) -> Any:
        logger = getattr(self, "logger", None)
        log_prefix = "KubernetesClient"

        if logger:
            logger.debug(
                f"[{log_prefix}] Attempting to replace resource. Raw resource_type received: '{resource_type}'"
            )

        api_method_map = {
            "Pod": (self._core_v1_api, "replace_namespaced_pod"),
            "Deployment": (self._apps_v1_api, "replace_namespaced_deployment"),
            "Service": (self._core_v1_api, "replace_namespaced_service"),
            "ConfigMap": (self._core_v1_api, "replace_namespaced_config_map"),
            "Secret": (self._core_v1_api, "replace_namespaced_secret"),
            "StatefulSet": (self._apps_v1_api, "replace_namespaced_stateful_set"),
            "DaemonSet": (self._apps_v1_api, "replace_namespaced_daemon_set"),
            "Job": (self._batch_v1_api, "replace_namespaced_job"),
            "CronJob": (self._batch_v1_api, "replace_namespaced_cron_job"),
            "Ingress": (self._networking_v1_api, "replace_namespaced_ingress"),
            "PersistentVolumeClaim": (
                self._core_v1_api,
                "replace_namespaced_persistent_volume_claim",
            ),
        }

        normalized_resource_type = resource_type.capitalize()
        api_client_instance, method_name = api_method_map.get(
            normalized_resource_type, (None, None)
        )

        if not api_client_instance or not (
            isinstance(method_name, str) and hasattr(api_client_instance, method_name)
        ):
            if logger:
                logger.error(
                    f"{log_prefix}: No supported 'replace' method found for resource kind '{resource_type}'."
                )
            self.last_api_error_body = f"Unsupported resource type for edit: {resource_type}"
            return False

        try:
            api_call = getattr(api_client_instance, str(method_name))
            await api_call(name=name, namespace=namespace, body=body)
            self.last_api_error_body = None  # Clear last error on success
            if logger:
                logger.info(
                    f"{log_prefix}: Successfully replaced {resource_type} '{name}' in '{namespace}'."
                )
            return True
        except ApiException as e:
            if logger:
                logger.error(
                    f"{log_prefix}: Failed to replace {resource_type} '{name}' in '{namespace}': {e}",
                    exc_info=True,
                )
            self.last_api_error_body = self._extract_error_body(e)
            raise K8sClientError(f"API Error: {e.reason}")
        except Exception as e:
            if logger:
                logger.error(
                    f"{log_prefix}: An unexpected error occurred replacing {resource_type} '{name}': {e}",
                    exc_info=True,
                )
            self.last_api_error_body = str(e)
            raise K8sClientError(f"Unexpected error: {e}")
