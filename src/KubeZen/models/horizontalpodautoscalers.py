from .base import (
    UIRow,
    CATEGORIES,
    autoscaling_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
)


@dataclass(frozen=True)
class HorizontalPodAutoscalerRow(UIRow):
    """Represents a HorizontalPodAutoscaler for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = autoscaling_v1_api
    kind: ClassVar[str] = "HorizontalPodAutoscaler"
    plural: ClassVar[str] = "horizontalpodautoscalers"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Horizontal Pod Autoscalers"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 4

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    min_pods: str = column_field(label="Min Pods", width=5)
    max_pods: str = column_field(label="Max Pods", width=5)
    replicas: str = column_field(label="Replicas", width=5)
    status: str = column_field(label="Status", width=5)

    def __init__(self, raw: Any):
        """Initialize the horizontal pod autoscaler row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "min_pods", self.raw.spec.min_replicas)
        object.__setattr__(self, "max_pods", self.raw.spec.max_replicas)
        object.__setattr__(self, "replicas", self.raw.status.current_replicas)
        object.__setattr__(self, "status", self.raw.status.status)
