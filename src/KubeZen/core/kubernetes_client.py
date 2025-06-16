import asyncio
import logging
from typing import Optional

from kubernetes_asyncio import client, config
from kubernetes_asyncio.config.config_exception import ConfigException
import os
import traceback

log = logging.getLogger(__name__)


class KubernetesClient:
    """Manages the Kubernetes API client configuration and initialization."""

    def __init__(self, kubeconfig: str | None = None, context: str | None = None):
        """Initialize the Kubernetes API client with optional kubeconfig and context."""
        self.api_client: Optional[client.ApiClient] = None
        self.core_v1: Optional[client.CoreV1Api] = None
        self.apps_v1: Optional[client.AppsV1Api] = None
        self.kubeconfig = kubeconfig
        self.context = context

    async def connect(self) -> None:
        """Connect to the Kubernetes cluster using the kubeconfig and context from __init__."""
        try:
            # Add a timeout to the config loading
            async with asyncio.timeout(5.0):  # 5 second timeout
                try:
                    loader = await config.load_kube_config(
                        config_file=self.kubeconfig,
                        context=self.context,
                    )
                except ConfigException as e:
                    log.error("Failed to load kubeconfig: %s", str(e))
                    traceback.print_exc()
                    os._exit(1)
                except Exception as e:
                    log.error("Unexpected error loading kubeconfig: %s", str(e))
                    traceback.print_exc()
                    os._exit(1)

            # If we get here, config loaded successfully
            try:
                # Create base configuration
                configuration = client.Configuration()
                
                # Only set attributes that exist in the loader
                if hasattr(loader, 'host'):
                    configuration.host = loader.host
                if hasattr(loader, 'ssl_ca_cert'):
                    configuration.ssl_ca_cert = loader.ssl_ca_cert
                if hasattr(loader, 'cert_file'):
                    configuration.cert_file = loader.cert_file
                if hasattr(loader, 'key_file'):
                    configuration.key_file = loader.key_file
                if hasattr(loader, 'api_key'):
                    configuration.api_key = loader.api_key

                self.api_client = client.ApiClient(configuration)
                self.core_v1 = client.CoreV1Api(self.api_client)
                self.apps_v1 = client.AppsV1Api(self.api_client)

                log.info("Successfully loaded and connected Kubernetes async client.")
            except Exception as e:
                log.error("Failed to initialize Kubernetes client: %s", str(e))
                traceback.print_exc()
                os._exit(1)

        except asyncio.TimeoutError:
            log.error("Timeout while trying to load Kubernetes configuration")
            traceback.print_exc()
            os._exit(1)
        except Exception as e:
            log.error("Fatal error in Kubernetes client initialization: %s", str(e))
            traceback.print_exc()
            os._exit(1)

    async def close(self) -> None:
        """Closes the API client's session."""
        if self.api_client:
            log.debug("Closing Kubernetes API client session.")
            await self.api_client.close()
            log.info("Kubernetes async client session closed.")

    def _format_age(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)}m"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h"
        days = hours / 24
        return f"{int(days)}d"
