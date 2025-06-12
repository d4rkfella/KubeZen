from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices


class ServiceBase:
    """
    A base class for services, providing common initialization such as
    access to AppServices and a pre-configured logger.
    """

    def __init__(self, app_services: AppServices):
        self.app_services = app_services
        # The logger for each service is a child of the main 'KubeZen' logger.
        # This gives us automatic hierarchical naming (e.g., 'KubeZen.FzfUIManager').
        self.logger = logging.getLogger(f"KubeZen.{self.__class__.__name__}")

        assert app_services.config is not None, "ServiceBase requires a valid AppConfig"
        assert (
            app_services.logger is not None
        ), "ServiceBase requires a configured Logger in AppServices"
        assert (
            app_services.event_bus is not None
        ), "ServiceBase requires a configured EventBus in AppServices"

        self.logger.debug("Initialized.")
