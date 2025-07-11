from .base import (
    UIRow,
    CATEGORIES,
    scheduling_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
)


@dataclass(frozen=True)
class PriorityClassRow(
    UIRow,
):
    """Represents a PriorityClass for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = scheduling_v1_api
    kind: ClassVar[str] = "PriorityClass"
    plural: ClassVar[str] = "priorityclasses"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Priority Classes"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 6

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    value: str = column_field(label="Value", width=5)
    global_default: str = column_field(label="Global Default", width=5)

    def __init__(self, raw: Any):
        """Initialize the priority class row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "value", self.raw.value)
        object.__setattr__(self, "global_default", self.raw.global_default)
