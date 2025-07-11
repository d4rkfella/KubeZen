from .base import (
    UIRow,
    CATEGORIES,
    coordination_v1_api,
    ApiInfo,
    dataclass,
    ClassVar,
    Any,
    column_field,
)


@dataclass(frozen=True)
class LeaseRow(UIRow):
    """Represents a Lease for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = coordination_v1_api
    kind: ClassVar[str] = "Lease"
    plural: ClassVar[str] = "leases"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Leases"
    category: ClassVar[str] = CATEGORIES["Config"].name
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    holder: str = column_field(label="Holder", width=5)
    lease_duration: str = column_field(label="Lease Duration", width=5)
    age: str = column_field(label="Age", width=10, is_age=True)

    def __init__(self, raw: Any):
        """Initialize the lease row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "holder", self.raw.spec.holder_identity)
        object.__setattr__(self, "lease_duration", self.raw.spec.lease_duration_seconds)
