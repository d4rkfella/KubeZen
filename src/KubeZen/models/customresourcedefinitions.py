from .base import (
    UIRow,
    CATEGORIES,
    apiextensions_v1_api,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
)


@dataclass(frozen=True)
class CustomResourceDefinitionRow(UIRow):
    """Represents a Custom Resource Definition for UI display."""

    # --- API Metadata ---
    api_info: ClassVar[ApiInfo] = apiextensions_v1_api
    kind: ClassVar[str] = "CustomResourceDefinition"
    plural: ClassVar[str] = "customresourcedefinitions"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Definitions"
    category: ClassVar[str] = CATEGORIES["Custom Resources"].name
    index: ClassVar[int] = 0

    # --- Instance Fields ---
    age: str = column_field(label="Age", width=10, is_age=True)
    group: str = column_field(label="Group", width=5)
    versions: str = column_field(label="Versions", width=5)
    scope: str = column_field(label="Scope", width=5)

    def __init__(self, raw: Any):
        """Initialize the custom resource definition row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "group", self.raw.spec.group)
        object.__setattr__(
            self, "versions", ", ".join([v.name for v in self.raw.spec.versions or []])
        )
        object.__setattr__(self, "scope", self.raw.spec.scope)
