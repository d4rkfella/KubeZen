from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Optional
from dataclasses import dataclass, field

from KubeZen.logger import Logger

if TYPE_CHECKING:
    from KubeZen.config import AppConfig
    from KubeZen.core.tmux_ui_manager import TmuxUIManager
    from KubeZen.core.kubernetes_client import KubernetesClient
    from KubeZen.core.user_input_manager import UserInputManager
    from KubeZen.core.fzf_ui_manager import FzfUIManager
    from KubeZen.core.app_services import AppServices

    # If AppServices is still a relevant container, it could be here too,
    # or its individual components are listed as above.


@dataclass
class ActionContext:
    """
    Provides the necessary services and data for an Action to execute.
    """

    logger: Logger
    config: AppConfig
    tmux_ui_manager: TmuxUIManager
    kubernetes_client: KubernetesClient
    user_input_manager: UserInputManager
    fzf_ui_manager: FzfUIManager  # For refocusing after actions

    # Current Kubernetes context information
    current_namespace: Optional[str]

    # Other contextual data that might be useful for actions
    # e.g., the raw resource object if different from the one passed to execute()
    additional_data: Optional[Dict[str, Any]] = None

    # TODO: Consider if selected_resource_name, selected_resource_kind are needed
    # if the 'resource' object passed to action.execute() is already specific enough.

    # Data specific to the current action invocation
    namespace: Optional[str] = None
    resource_name: Optional[str] = None
    resource_kind: Optional[str] = None
    raw_k8s_object: Optional[Any] = None  # The actual K8s object the action operates on
    action_code: Optional[str] = None  # The code of the action being executed

    # For actions that might need to pass specific data not part of the resource itself
    custom_data: Optional[Dict[str, Any]] = field(default_factory=dict)

    # The full context dictionary of the view that invoked the action.
    # Useful for actions that need to push new views with callback data (e.g. ContainerSelectionView)
    original_view_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the context to a dictionary.
        Note: Service objects (logger, config, etc.) are not serialized.
        They are expected to be reconstituted from AppServices during deserialization.
        """
        return {
            "current_namespace": self.current_namespace,
            "additional_data": self.additional_data,
            "namespace": self.namespace,
            "resource_name": self.resource_name,
            "resource_kind": self.resource_kind,
            "raw_k8s_object": self.raw_k8s_object,
            "action_code": self.action_code,
            "custom_data": self.custom_data,
            "original_view_context": self.original_view_context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], app_services: "AppServices") -> "ActionContext":
        """
        Deserializes an ActionContext from a dictionary, re-hydrating it with live services.
        """
        assert app_services.logger is not None
        assert app_services.config is not None
        assert app_services.tmux_ui_manager is not None
        assert app_services.kubernetes_client is not None
        assert app_services.user_input_manager is not None
        assert app_services.fzf_ui_manager is not None

        return cls(
            logger=app_services.logger,
            config=app_services.config,
            tmux_ui_manager=app_services.tmux_ui_manager,
            kubernetes_client=app_services.kubernetes_client,
            user_input_manager=app_services.user_input_manager,
            fzf_ui_manager=app_services.fzf_ui_manager,
            current_namespace=data.get("current_namespace"),
            additional_data=data.get("additional_data"),
            namespace=data.get("namespace"),
            resource_name=data.get("resource_name"),
            resource_kind=data.get("resource_kind"),
            raw_k8s_object=data.get("raw_k8s_object"),
            action_code=data.get("action_code"),
            custom_data=data.get("custom_data", {}),
            original_view_context=data.get("original_view_context"),
        )
