from .base import (
    CATEGORIES,
    dataclass,
    Any,
    ClassVar,
    column_field,
    UIRow,
    ApiInfo,
    rbac_authorization_v1_api,
    ABC,
    abstractmethod,
)
    
class BaseRbacAuthorizationV1Row(UIRow, ABC):
    """Base class for RBAC Authorization V1 API resources."""

    api_info: ClassVar[ApiInfo] = rbac_authorization_v1_api
    category: ClassVar[str] = CATEGORIES["Access Control"].name

    @abstractmethod
    def __init__(self, raw: Any):
        super().__init__(raw=raw)


@dataclass(frozen=True)
class RoleRow(BaseRbacAuthorizationV1Row):
    """Represents a Role for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Role"
    plural: ClassVar[str] = "roles"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Roles"
    category: ClassVar[str] = CATEGORIES["Access Control"].name
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the role row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class ClusterRoleRow(BaseRbacAuthorizationV1Row):
    """Represents a ClusterRole for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ClusterRole"
    plural: ClassVar[str] = "clusterroles"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Cluster Roles"
    index: ClassVar[int] = 3

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the cluster role row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class RoleBindingRow(BaseRbacAuthorizationV1Row):
    """Represents a RoleBinding for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "RoleBinding"
    plural: ClassVar[str] = "rolebindings"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Role Bindings"
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the role binding row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class ClusterRoleBindingRow(BaseRbacAuthorizationV1Row):
    """Represents a ClusterRoleBinding for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ClusterRoleBinding"
    plural: ClassVar[str] = "clusterrolebindings"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Cluster Role Bindings"
    index: ClassVar[int] = 4

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the cluster role binding row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
