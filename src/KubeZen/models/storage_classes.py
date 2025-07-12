from .base import (
    UIRow,
    CATEGORIES,
    storage_v1_api,
    ApiInfo,
    dataclass,
    ClassVar,
    column_field,
)
from kubernetes_asyncio.client import V1StorageClass
from typing import cast

@dataclass(frozen=True)
class StorageClassRow(UIRow):
    """Represents a StorageClass for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = storage_v1_api
    kind: ClassVar[str] = "StorageClass"
    plural: ClassVar[str] = "storageclasses"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Storage Classes"
    category: ClassVar[str] = CATEGORIES["Storage"].name
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    provisioner: str = column_field(label="Provisioner", width=10)
    reclaim_policy: str = column_field(label="Reclaim Policy", width=10)
    age: str = column_field(label="Age", width=10, is_age=True)
    default: str = column_field(label="Default", width=10)

    def __init__(self, raw: V1StorageClass):
        """Initialize the storage class row with data from the raw Kubernetes resource."""
        super().__init__(raw=cast(V1StorageClass, raw))
        object.__setattr__(self, "provisioner", self.raw.provisioner)
        object.__setattr__(self, "reclaim_policy", self.raw.reclaim_policy)
        object.__setattr__(
            self,
            "default",
            (
                "true"
                if self.raw.metadata.annotations.get(
                    "storageclass.kubernetes.io/is-default-class"
                )
                == "true"
                else "false"
            ),
        )
