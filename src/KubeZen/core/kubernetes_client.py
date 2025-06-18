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
        self._loader = None

    async def connect(self, context: str | None = None) -> None:
        """Connect to the Kubernetes cluster using the kubeconfig and context from __init__."""
        try:
            # Add a timeout to the config loading
            async with asyncio.timeout(5.0):  # 5 second timeout
                if context:
                    self.context = context
                await config.load_kube_config(config_file=self.kubeconfig, context=self.context)
                self.api_client = client.ApiClient()
                self.core_v1 = client.CoreV1Api(self.api_client)
                self.apps_v1 = client.AppsV1Api(self.api_client)
                log.info("Successfully loaded and connected Kubernetes async client.")
        except Exception as e:
            log.error(f"Failed to connect to Kubernetes cluster: {e}")
            log.debug(f"Stack trace: {traceback.format_exc()}")
            raise

    async def close(self) -> None:
        """Closes the API client's session."""
        if self.api_client:
            log.debug("Closing Kubernetes API client session.")
            await self.api_client.close()
            log.info("Kubernetes async client session closed.")

    async def get_available_contexts(self) -> list[str]:
        """Get a list of available Kubernetes context names."""
        try:
            contexts, _ = config.list_kube_config_contexts(config_file=self.kubeconfig)
            return [context['name'] for context in contexts]
        except (ConfigException, KeyError) as e:
            log.error(f"Failed to get available contexts: {e}")
            return []

    async def get_current_context(self) -> str:
        """Get the current Kubernetes context name."""
        try:
            contexts, active_context = config.list_kube_config_contexts(config_file=self.kubeconfig)
            return active_context['name']
        except (ConfigException, KeyError) as e:
            log.error(f"Failed to get current context: {e}")
            return "unknown"

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

    async def switch_context(self, context_name: str) -> bool:
        """Switch to a different Kubernetes context.
        
        Args:
            context_name: The name of the context to switch to.
            
        Returns:
            bool: True if switch was successful, False otherwise.
        """
        try:
            # Store the current context name
            self.context = context_name
            
            # Reconnect with the new context
            await self.connect()
            return True
        except Exception as e:
            log.error(f"Failed to switch to context {context_name}: {e}")
            return False
