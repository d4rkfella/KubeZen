from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, TypeVar, Generic, TYPE_CHECKING, Any, Dict

from KubeZen.core.signals import NavigationSignal
from KubeZen.core.contexts import ActionContext

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices

    # from KubeZen.ui.navigation_coordinator import NavigationCoordinator

# Generic type for the resource, can be specialized by concrete actions
R = TypeVar("R")


class Action(ABC, Generic[R]):
    """
    Abstract Base Class for all actions that can be performed on a resource.
    The context provided to execute and is_applicable must be an ActionContext instance.
    """

    def __init__(
        self, app_services: AppServices, name: str, shortcut: str, icon: str, **kwargs: Any
    ):
        self.app_services = app_services
        self.name = name
        self.shortcut = shortcut
        self._icon = icon

    @property
    def action_code(self) -> str:
        return self.name.lower().replace(" ", "_")

    @property
    def display_text(self) -> str:
        return self.name

    @property
    def icon(self) -> str:
        return self._icon

    @abstractmethod
    def is_applicable(self, context: ActionContext) -> bool:
        """
        Determines if the action is applicable to the given resource and context.
        This method must be overridden by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, context: ActionContext, resource: Dict[str, Any]
    ) -> Optional[NavigationSignal]:
        """
        Executes the action with the given resource and context.
        This method must be overridden by subclasses.
        It can return a NavigationSignal to trigger UI changes or None.
        """
        raise NotImplementedError
