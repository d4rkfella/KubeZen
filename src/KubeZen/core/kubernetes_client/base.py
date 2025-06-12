# Main entry point for KubernetesClient, composed of resource mixins.
# Each mixin implements methods for a specific resource type (namespaces, pods, etc).
from __future__ import annotations

from kubernetes_asyncio import client, config
from .misc import MiscMixin
from .workloads import WorkloadsMixin
from .describe import DescribeMixin
from .utils import UtilsMixin
from typing import Optional, Any, TYPE_CHECKING
from pathlib import Path
import os
import tempfile
import logging
from KubeZen.core.service_base import ServiceBase

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class KubernetesClient(
    ServiceBase,
    MiscMixin,
    WorkloadsMixin,
    DescribeMixin,
    UtilsMixin,
):
    app_services: AppServices
    current_kube_context: Optional[str]
    logger: logging.Logger
    _core_v1_api: Optional[Any]
    _apps_v1_api: Optional[Any]
    _batch_v1_api: Optional[Any]
    _networking_v1_api: Optional[Any]
    _api_client: Optional[Any]
    last_api_error_body: Optional[str]
    current_kube_context_name: Optional[str]
    _initialized: bool

    def __init__(
        self, app_services: AppServices, current_kube_context: Optional[str] = None
    ) -> None:
        super().__init__(app_services)
        self.current_kube_context = current_kube_context
        self._core_v1_api = None
        self._apps_v1_api = None
        self._batch_v1_api = None
        self._networking_v1_api = None
        self._api_client = None
        self.last_api_error_body = None
        self.current_kube_context_name = current_kube_context
        # Access config through app_services since ServiceBase guarantees it exists
        if not self.current_kube_context_name and self.app_services.config:
            self.current_kube_context_name = self.app_services.config.current_kube_context_name

    @classmethod
    async def create(
        cls, app_services: AppServices, current_kube_context: Optional[str] = None
    ) -> "KubernetesClient":
        """
        Async factory method to create and initialize a KubernetesClient instance.
        """
        instance = cls(app_services, current_kube_context)
        if instance.logger:
            instance.logger.info(
                f"{getattr(instance, '_log_prefix', lambda: '')()} KubernetesClient factory: instance created, proceeding to async initialization."
            )
        await instance._initialize_clients()
        return instance

    async def _initialize_clients(self) -> None:
        """Initializes the Kubernetes API clients."""
        if not self.logger:
            print("ERROR: KubernetesClient cannot initialize without a logger.")
            return

        self.logger.info("Initializing Kubernetes clients...")
        kube_context_name = self.current_kube_context_name
        kube_config_file_to_use = (
            str(self.app_services.config.kube_config_path)
            if self.app_services.config and self.app_services.config.kube_config_path
            else None
        )

        try:
            if kube_config_file_to_use:
                self.logger.info(f"Using Kubeconfig override path: {kube_config_file_to_use}")
            else:
                self.logger.info(
                    "No Kubeconfig path override. Will use default resolution (e.g., KUBECONFIG env var, ~/.kube/config)."
                )
            if kube_context_name:
                self.logger.info(f"Using Kubeconfig context: {kube_context_name}")
            else:
                self.logger.info(
                    "No Kubeconfig context override. Will use current-context from Kubeconfig."
                )

            # Only pass context if it's not empty
            context_kwarg = {"context": kube_context_name} if kube_context_name else {}

            # Set temp directory for certificate files
            if self.app_services.config:
                temp_dir = Path(self.app_services.config.get_temp_dir_path()) / "k8s_certs"
                temp_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Fallback to a system default temp dir if config is not available
                temp_dir = Path(tempfile.gettempdir()) / "kubezen_k8s_certs"
                temp_dir.mkdir(parents=True, exist_ok=True)

            # Set environment variables to control where temp files are created
            os.environ["KUBERNETES_TEMP_DIR"] = str(temp_dir)
            os.environ["TMPDIR"] = str(
                temp_dir
            )  # This affects where tempfile.mkstemp creates files
            os.environ["TEMP"] = str(temp_dir)  # Windows compatibility
            os.environ["TMP"] = str(temp_dir)  # Windows compatibility

            await config.load_kube_config(
                config_file=kube_config_file_to_use,
                client_configuration=None,
                persist_config=True,
                **context_kwarg,
            )

            loaded_config = client.Configuration.get_default_copy()
            effective_host = loaded_config.host
            if self.logger:
                self.logger.info(
                    f"Kubeconfig loaded (via default). Effective API host: {effective_host}"
                )
            if not effective_host and self.logger:
                self.logger.error(
                    "CRITICAL: API host is NOT SET after load_kube_config (via default). This will cause API call failures."
                )

            self._api_client = client.ApiClient(configuration=loaded_config)
            self._core_v1_api = client.CoreV1Api(api_client=self._api_client)
            self._apps_v1_api = client.AppsV1Api(api_client=self._api_client)
            self._batch_v1_api = client.BatchV1Api(api_client=self._api_client)
            self._networking_v1_api = client.NetworkingV1Api(api_client=self._api_client)

            if self._api_client and hasattr(self._api_client, "configuration") and self.logger:
                config_log_prefix = "[ApiClientConfig_Debug]"
                conf = self._api_client.configuration
                self.logger.debug(f"{config_log_prefix} Host: {getattr(conf, 'host', 'N/A')}")
                self.logger.debug(
                    f"{config_log_prefix} SSL CA Cert: {getattr(conf, 'ssl_ca_cert', 'N/A')}"
                )
                self.logger.debug(
                    f"{config_log_prefix} Cert File: {getattr(conf, 'cert_file', 'N/A')}"
                )
                self.logger.debug(
                    f"{config_log_prefix} Key File: {getattr(conf, 'key_file', 'N/A')}"
                )
                self.logger.debug(
                    f"{config_log_prefix} API Key Prefix: {getattr(conf, 'api_key_prefix', 'N/A')}"
                )
                self.logger.debug(
                    f"{config_log_prefix} Verify SSL: {getattr(conf, 'verify_ssl', 'N/A')}"
                )
                self.logger.debug(f"{config_log_prefix} Debug: {getattr(conf, 'debug', 'N/A')}")
            elif self.logger:
                self.logger.warning(
                    "[ApiClientConfig_Debug] api_client or its configuration is not available for detailed logging."
                )

            if self.logger:
                self.logger.info(
                    f"Kubernetes API clients initialized successfully for context '{self.current_kube_context_name if self.current_kube_context_name else 'default'}' (using kubernetes_asyncio)."
                )
        except config.ConfigException as e:
            if self.logger:
                self.logger.error(
                    f"Could not load Kubernetes configuration (async init): {e}", exc_info=True
                )
            raise
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"An unexpected error occurred during Kubernetes client initialization (async init): {e}",
                    exc_info=True,
                )
            raise

    async def stop(self) -> None:
        """Close the underlying ApiClient session if it exists (for asyncio cleanup)."""
        if hasattr(self, "_api_client") and self._api_client:
            try:
                await self._api_client.close()
                if hasattr(self, "logger"):
                    self.logger.info("KubernetesClient: ApiClient closed successfully.")
            except Exception as e:
                if hasattr(self, "logger"):
                    self.logger.warning(f"KubernetesClient: Error closing ApiClient: {e}")
        else:
            if hasattr(self, "logger"):
                self.logger.info("KubernetesClient: No ApiClient to close.")
