from __future__ import annotations

from typing import Optional, Any
from kubernetes_asyncio.client import AppsV1Api
import logging


class WorkloadsMixin:
    _apps_v1_api: Optional[AppsV1Api] = None
    logger: logging.Logger
    app_services: Any = None  # This will be set by the parent class

    # Temporarily removing broken methods until their dependencies can be restored.
    pass
