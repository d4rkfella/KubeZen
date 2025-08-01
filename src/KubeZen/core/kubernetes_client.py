from __future__ import annotations
import logging
import orjson
import re
from typing import (
    cast,
    Dict,
    Any,
    ClassVar,
    Callable,
    Type,
    Generator,
    TypeVar,
)


from kubernetes_asyncio import client, config
from kubernetes_asyncio.config.config_exception import ConfigException

from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.api_client import ApiClient

from KubeZen.models.base import ALL_APIS, UIRow

log = logging.getLogger(__name__)

R = TypeVar("R", bound=UIRow)


class KubernetesClient(ApiClient):
    _instance: ClassVar[KubernetesClient | None] = None

    @classmethod
    async def get_instance(cls) -> KubernetesClient:
        if cls._instance is None:
            await config.load_kube_config()
            configuration = client.Configuration.get_default_copy()
            configuration.client_side_timeout = 10
            configuration.json_dumps = orjson.dumps
            configuration.json_loads = orjson.loads
            cls._instance = KubernetesClient(configuration)
        return cls._instance

    def __init__(self, configuration: client.Configuration) -> None:
        super().__init__(configuration)
        self._api_cache: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        if name in self._api_cache:
            return self._api_cache[name]

        if name in ALL_APIS:
            api_info = ALL_APIS[name]
            api_class = getattr(client, api_info.client_name)
            api_instance = api_class(self)
            self._api_cache[name] = api_instance
            return api_instance

        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    async def get_current_context(self) -> str:
        """Get the current Kubernetes context name."""
        try:
            _, active_context = config.list_kube_config_contexts()
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

            def generate_metrics() -> (
                Generator[tuple[str, dict[str, float]], None, None]
            ):
                """Processes raw pod metrics and yields them one by one."""
                for pod in response.get("items", []):
                    metadata = pod.get("metadata", {})
                    namespace = metadata.get("namespace")
                    name = metadata.get("name")
                    if not (namespace and name):
                        continue

                    total_cpu, total_memory = self._process_container_metrics(
                        pod.get("containers", [])
                    )

                    yield f"{namespace}/{name}", {
                        "cpu": total_cpu,
                        "memory": total_memory,
                    }

            return dict(generate_metrics())

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
        self, model_class: Type[R], action: str, namespace: str | None = None
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
            kwargs.update(
                {
                    "group": model_class.api_info.group,
                    "version": model_class.api_info.version,
                    "plural": model_class.plural,
                }
            )

        # Add namespace to kwargs if it's a namespaced resource and not a cluster-wide list
        if model_class.namespaced and not (
            action == "list" and (not namespace or namespace == "all")
        ):
            if namespace and namespace != "all":
                kwargs["namespace"] = namespace

        return api_method, kwargs
