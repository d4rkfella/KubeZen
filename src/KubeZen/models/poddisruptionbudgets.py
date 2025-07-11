from .base import UIRow, CATEGORIES, policy_v1_api, ApiInfo, dataclass, Any, ClassVar, column_field


@dataclass(frozen=True)
class PodDisruptionBudgetRow(UIRow):
    """Represents a PodDisruptionBudget for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = policy_v1_api
    kind: ClassVar[str] = "PodDisruptionBudget"
    plural: ClassVar[str] = "poddisruptionbudgets"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Pod Disruption Budgets"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 5

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    min_available: str = column_field(label="Min Available", width=10)
    max_unavailable: str = column_field(label="Max Unavailable", width=10)
    current_healthy: str = column_field(label="Current Healthy", width=10)
    desired_healthy: str = column_field(label="Desired Healthy", width=10)

    def __init__(self, raw: Any):
        """Initialize the pod disruption budget row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "min_available", self.raw.spec.min_available)
        object.__setattr__(self, "max_unavailable", self.raw.spec.max_unavailable)
        object.__setattr__(self, "current_healthy", self.raw.status.current_healthy)
        object.__setattr__(self, "desired_healthy", self.raw.status.desired_healthy)
