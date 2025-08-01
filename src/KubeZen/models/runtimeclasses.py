from .base import (
    UIRow,
    CATEGORIES,
    node_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
)


@dataclass(frozen=True)
class RuntimeClassRow(UIRow):
    """Represents a RuntimeClass for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = node_v1_api
    kind: ClassVar[str] = "RuntimeClass"
    plural: ClassVar[str] = "runtimeclasses"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Runtime Classes"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 7

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    handler: str = column_field(label="Handler", width=5)

    def __init__(self, raw: Any):
        """Initialize the runtime class row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "handler", self.raw.handler)
