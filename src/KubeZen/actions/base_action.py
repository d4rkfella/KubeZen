from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Type, TypeVar, Callable, ClassVar, Generic
import logging

from KubeZen.models.base import UIRow


if TYPE_CHECKING:
    from KubeZen.app import KubeZen

ActionResult = Optional[str]

T = TypeVar("T", bound="BaseAction")
R = TypeVar("R", bound=UIRow)

log = logging.getLogger(__name__)


def supports_resources(*resource_types: str) -> Callable[[Type[T]], Type[T]]:
    """Decorator to mark which resource types an action supports.

    Args:
        *resource_types: Variable number of resource type strings (e.g. 'pods', 'services')
                        Use "*" as a wildcard to support all resource types.

    Example:
        @supports_resources('pods', 'deployments')  # Specific resources
        class MyAction(BaseAction):
            pass

        @supports_resources('*')  # All resources
        class MyOtherAction(BaseAction):
            pass
    """

    def decorator(cls: Type[T]) -> Type[T]:
        cls.supported_resource_types = set(resource_types)
        return cls

    return decorator


class BaseAction(Generic[R], ABC):
    """Abstract base class for all actions."""

    name: ClassVar[str]
    supported_resource_types: ClassVar[set[str]] = set()

    def __init__(self, app: KubeZen):
        self.app = app

    def can_perform(self, row_info: R) -> bool:
        """Runtime check if this action can be performed on the specific resource instance.
        While supports_resource() checks if an action works with a resource type in general,
        this method checks if the action can be performed on a specific resource instance
        based on its current state.

        Examples:
        - Scale action might check if the resource is not being deleted
        - Exec action might check if the pod is running
        - Edit action might check if the resource is not in a terminal state

        Returns:
            True if the action can be performed, False otherwise
        """
        return True  # Default to True unless overridden by subclass

    @abstractmethod
    async def execute(self, row_info: R) -> ActionResult:
        raise NotImplementedError
