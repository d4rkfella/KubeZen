from __future__ import annotations
from typing import TYPE_CHECKING, Any
import warnings

if TYPE_CHECKING:
    from ..app import KubeZenTuiApp


class BaseAction:
    """Abstract base class for all actions."""

    def __init__(
        self,
        app: KubeZenTuiApp,
        resource: dict[str, Any],
        object_name: str,
        resource_key: str,
    ):
        self.app = app
        self.client = app.kubernetes_client
        self.tmux_manager = app.tmux_manager
        self.resource = resource
        self.object_name = object_name

        # For backward compatibility with actions that rely on these
        self.resource_kind = resource_key
        self.namespace = resource.get("metadata", {}).get("namespace")
        self.resource_name = object_name

    async def run(self) -> None:
        """
        The main entry point for the action's logic.
        This method should be overridden by subclasses.
        """
        # This is for backward compatibility with older actions
        # that still use execute().
        if type(self).execute != BaseAction.execute:
            warnings.warn(
                "`execute()` is deprecated, implement `run()` instead",
                DeprecationWarning,
            )
            await self.execute()
        else:
            raise NotImplementedError("Subclasses must implement the run() method.")

    async def execute(self) -> None:
        """
        Legacy entry point for actions.
        Modern actions should implement run() instead.
        """
        pass
