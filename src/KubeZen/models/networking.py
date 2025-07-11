from abc import abstractmethod
from .base import (
    UIRow,
    CATEGORIES,
    networking_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
    ABC,
)

class BaseNetworkingV1Row(UIRow, ABC):
    """Base class for Networking V1 API resources."""

    api_info: ClassVar[ApiInfo] = networking_v1_api
    category: ClassVar[str] = CATEGORIES["Network"].name

    @abstractmethod
    def __init__(self, raw: Any):
        super().__init__(raw=raw)


@dataclass(frozen=True)
class IngressRow(BaseNetworkingV1Row):
    """Represents an Ingress for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Ingress"
    plural: ClassVar[str] = "ingresses"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Ingresses"
    list_method_name: ClassVar[str] = "list_ingress_for_all_namespaces"
    delete_method_name: ClassVar[str] = "delete_namespaced_ingress"
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    hosts: str = column_field(label="Hosts", width=10)
    class_name: str = column_field(label="Class", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the ingress row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(
            self,
            "hosts",
            ", ".join([rule.host for rule in self.raw.spec.rules if rule.host]),
        )
        object.__setattr__(self, "class_name", self.raw.spec.ingress_class_name)


@dataclass(frozen=True)
class IngressClassRow(BaseNetworkingV1Row):
    """Represents an IngressClass for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "IngressClass"
    plural: ClassVar[str] = "ingressclasses"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Ingress Classes"
    list_method_name: ClassVar[str] = "list_ingress_class"
    delete_method_name: ClassVar[str] = "delete_ingress_class"
    index: ClassVar[int] = 3

    # --- Instance Fields ---
    controller: str = column_field(label="Controller", width=10)
    api_group: str = column_field(label="API Group", width=10)
    scope: str = column_field(label="Scope", width=10)
    kind_resource: str = column_field(label="Kind", width=10)

    def __init__(self, raw: Any):
        """Initialize the ingress class row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "controller", self.raw.spec.controller)
        object.__setattr__(self, "api_group", self.raw.spec.api_group)
        object.__setattr__(self, "scope", self.raw.spec.scope)
        object.__setattr__(self, "kind", self.raw.spec.kind)


@dataclass(frozen=True)
class NetworkPolicyRow(BaseNetworkingV1Row):
    """Represents a NetworkPolicy for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "NetworkPolicy"
    plural: ClassVar[str] = "networkpolicies"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Network Policies"
    list_method_name: ClassVar[str] = "list_network_policy_for_all_namespaces"
    delete_method_name: ClassVar[str] = "delete_namespaced_network_policy"
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    # pod_selector: str = column_field(label="Pod Selector", width=10)
    policy_types: str = column_field(label="Policy Types", width=10)

    def __init__(self, raw: Any):
        """Initialize the network policy row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "policy_types", ", ".join(self.raw.spec.policy_types))
