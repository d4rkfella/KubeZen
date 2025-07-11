from __future__ import annotations
import asyncio
import logging
import os
import traceback
from pathlib import Path
from typing import Optional, cast, Dict, TYPE_CHECKING, Any, ClassVar, Callable, Union, Type

import yaml
from kubernetes_asyncio.utils.create_from_yaml import create_from_yaml, create_from_dict, FailToCreateError

from kubernetes_asyncio import client, config
from kubernetes_asyncio.config.config_exception import ConfigException

from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.api_client import ApiClient

from KubeZen.models.base import ALL_APIS, UIRow

if TYPE_CHECKING:
    from KubeZen.app import KubeZenTuiApp

log = logging.getLogger(__name__)


import orjson
import re


class KubernetesClient:
    """Manages the Kubernetes API client configuration and initialization."""

    # --- Singleton Pattern ---
    _instance: ClassVar[KubernetesClient | None] = None

    @classmethod
    def get_instance(cls, app: "KubeZenTuiApp") -> KubernetesClient:
        """Returns the singleton instance of the KubernetesClient."""
        if cls._instance is None:
            cls._instance = KubernetesClient(app)
            log.info("KubernetesClient singleton initialized.")
        return cls._instance

    def __init__(self, app: "KubeZenTuiApp"):
        """Initialize the Kubernetes API client with optional kubeconfig and context."""
        self.app = app
        self.client: Optional[client.ApiClient] = None
        self.config = self.app.config
        self.kubeconfig = os.environ.get("KUBE_CONFIG")
        self.context: str | None = os.environ.get("KUBE_CONTEXT")
        self._loader = None
        self._api_cache: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        """Dynamically create and cache Kubernetes API client instances."""
        if name in self._api_cache:
            #log.debug(f"API cache hit for {name}")
            log.debug(f"API cache: {self._api_cache}")
            return self._api_cache[name]

        if self.client is None:
            raise RuntimeError(
                "Kubernetes client is not connected. Call connect() first."
            )

        if name in ALL_APIS:
            api_info = ALL_APIS[name]
            api_class = getattr(client, api_info.client_name)
            api_instance = api_class(self.client)
            self._api_cache[name] = api_instance
            return api_instance
        log.debug(f"API cache: {self._api_cache}")

        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    async def connect(self, context: str | None = None) -> None:
        """Connect to the Kubernetes cluster using the kubeconfig and context from __init__."""
        try:
            # First, try to load in-cluster configuration
            try:
                config.load_incluster_config()
                log.info("Successfully loaded in-cluster Kubernetes configuration.")
            except config.ConfigException:
                # Fallback to a kube-config file for local development
                # Set TMPDIR to control where the k8s client saves transient cert files
                temp_dir = self.app.config.paths.temp_dir
                os.environ["TMPDIR"] = str(temp_dir)
                log.debug(f"Set TMPDIR for Kubernetes client to: {temp_dir}")
                current_context = context or self.context
                await config.load_kube_config(
                    config_file=self.kubeconfig, context=current_context
                )
                log.info(
                    "Successfully loaded local kubeconfig " "(context: %s).",
                    current_context or "default",
                )

            # --- API Client Configuration ---
            # Get a copy of the default configuration
            client_config = client.Configuration.get_default_copy()

            client_config.json_dumps = orjson.dumps
            client_config.json_loads = orjson.loads

            self.client = ApiClient(configuration=client_config)

        except config.ConfigException:
            log.error(
                "Could not load Kubernetes configuration. "
                "Please ensure you are running in a cluster or have a valid kubeconfig file."
            )
            raise
        except Exception as e:
            log.error("Failed to connect to Kubernetes cluster: %s", e)
            log.debug("Stack trace: %s", traceback.format_exc())
            raise

    async def close(self) -> None:
        """Closes the underlying API client."""
        if self.client:
            await self.client.close()
            self.client = None
            # Clear the API cache
            self._api_cache.clear()
            log.info("Kubernetes client session closed.")

    async def get_current_context(self) -> str:
        """Get the current Kubernetes context name."""
        try:
            _, active_context = config.list_kube_config_contexts(
                config_file=self.kubeconfig
            )
            return cast(str, active_context["name"])
        except (ConfigException, KeyError) as e:
            log.error("Failed to get current context: %s", e)
            return "unknown"

    @staticmethod
    def _parse_cpu_metric(cpu_str: str) -> float:
        """Parse CPU metric string into core value."""
        if not cpu_str or cpu_str == "0":
            return 0.0

        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000  # millicores to cores
        if cpu_str.endswith("n"):
            return float(cpu_str[:-1]) / 1_000_000_000  # nanocores to cores
        if cpu_str.endswith("u"):
            return float(cpu_str[:-1]) / 1_000_000  # microseconds to cores
        return float(cpu_str)  # already in cores

    @staticmethod
    def _parse_memory_metric(memory_str: str) -> float:
        """Parse memory metric string into byte value."""
        if not memory_str or memory_str == "0":
            return 0.0

        # Strip units and convert to bytes
        memory_value = float("".join(c for c in memory_str if c.isdigit() or c == "."))

        if "Ki" in memory_str:
            return memory_value * 1024
        if "Mi" in memory_str:
            return memory_value * 1024 * 1024
        if "Gi" in memory_str:
            return memory_value * 1024 * 1024 * 1024
        return memory_value  # already in bytes

    def _process_container_metrics(self, containers: list[dict]) -> tuple[float, float]:
        """Process container metrics and return total CPU and memory."""
        total_cpu = 0.0
        total_memory = 0.0

        for container in containers:
            usage = container.get("usage", {})
            total_cpu += self._parse_cpu_metric(usage.get("cpu", "0"))
            total_memory += self._parse_memory_metric(usage.get("memory", "0"))

        return total_cpu, total_memory

    async def fetch_pod_metrics(self) -> Dict[str, Dict[str, float]]:
        """Fetch CPU and memory metrics for all pods using the metrics API."""
        try:
            # Query the metrics API
            response = await self.CustomObjectsApi.list_cluster_custom_object(  # type: ignore
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )

            pod_metrics: Dict[str, Dict[str, float]] = {}

            # Process each pod's metrics
            for pod in response.get("items", []):
                metadata = pod.get("metadata", {})
                namespace = metadata.get("namespace")
                name = metadata.get("name")
                if not (namespace and name):
                    continue

                total_cpu, total_memory = self._process_container_metrics(
                    pod.get("containers", [])
                )

                pod_metrics[f"{namespace}/{name}"] = {
                    "cpu": total_cpu,
                    "memory": total_memory,
                }

            return pod_metrics

        except ApiException as e:
            if e.status == 404:
                log.warning(
                    "Metrics API not available (404 Not Found). "
                    "Is metrics-server installed?"
                )
            else:
                log.error(
                    "Error fetching metrics from Metrics API (HTTP %s): %s",
                    e.status,
                    e.reason,
                )
            return {}
        except Exception as e:
            log.error("Unexpected error fetching metrics: %s", e, exc_info=True)
            return {}

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Converts PascalCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def get_api_method_for_resource(
        self, model_class: Type[UIRow], action: str, namespace: str | None = None
    ) -> tuple[Callable, dict[str, Any]]:
        """
        Gets the appropriate API method and kwargs for a given resource model and action.
        """
        api_client = getattr(self, model_class.api_info.client_name)

        kind_snake = self._to_snake_case(model_class.kind)

        # Determine the base method name.
        method_name = f"{action}_"
        if model_class.namespaced:
            # The 'list' action has a special "..._for_all_namespaces" variant.
            if action == "list" and (not namespace or namespace == "all"):
                method_name += f"{kind_snake}_for_all_namespaces"
            else:
                method_name += f"namespaced_{kind_snake}"
        else:
            method_name += kind_snake

        # Handle special cases for CustomObjectsApi
        if model_class.api_info.client_name == "CustomObjectsApi":
            if action in ["create", "patch", "delete"]:
                method_name = (
                    f"{action}_namespaced_custom_object"
                    if model_class.namespaced
                    else f"{action}_cluster_custom_object"
                )
            elif action == "list":
                method_name = (
                    "list_namespaced_custom_object"
                    if model_class.namespaced and namespace and namespace != "all"
                    else "list_cluster_custom_object"
                )

        api_method = getattr(api_client, method_name)

        # Prepare kwargs
        kwargs = {}
        if model_class.api_info.client_name == "CustomObjectsApi":
            kwargs.update({
                "group": model_class.api_info.group,
                "version": model_class.api_info.version,
                "plural": model_class.plural,
            })

        # Add namespace to kwargs if it's a namespaced resource and not a cluster-wide list
        if model_class.namespaced and not (
            action == "list" and (not namespace or namespace == "all")
        ):
            if namespace and namespace != "all":
                kwargs["namespace"] = namespace

        return api_method, kwargs

    async def get_active_context_info(self) -> dict[str, Any]:
        """Get the full context dictionary for the active context."""
        try:
            _, active_context = await asyncio.to_thread(
                config.list_kube_config_contexts, config_file=self.kubeconfig
            )
            return cast(dict[str, Any], active_context)
        except (ConfigException, KeyError) as e:
            log.error("Failed to get active context info: %s", e)
            return {}

    async def create_resource(
        self,
        resource: Union[str, dict],
        namespace: str = "default",
        verbose: bool = False,
        dry_run: str = None,
        **kwargs,
    ):
        """
        Create a Kubernetes resource from YAML path or dict.
        Returns the created object(s), or None if creation failed.
        """
        try:
            if isinstance(resource, str):
                if Path(resource).exists():
                    # It's a file path
                    return await create_from_yaml(
                        self.client,
                        yaml_file=resource,
                        namespace=namespace,
                        verbose=verbose,
                        dry_run=dry_run,
                        **kwargs
                    )
                else:
                    # Try parsing as raw YAML string
                    parsed = yaml.safe_load(resource)
                    return await create_from_dict(
                        self.client,
                        data=parsed,
                        namespace=namespace,
                        verbose=verbose,
                        dry_run=dry_run,
                        **kwargs
                    )
            elif isinstance(resource, dict):
                return await create_from_dict(
                    self.client,
                    data=resource,
                    namespace=namespace,
                    verbose=verbose,
                    dry_run=dry_run,
                    **kwargs
                )
            else:
                raise ValueError("Invalid resource input: must be a dict, YAML string, or valid path.")
        except FailToCreateError as e:
            log.error("Failed to create resource: %s", e)
            raise
