from .base import (
    UIRow,
    CATEGORIES,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
    admissionregistration_v1_api,
    ABC,
    abstractmethod,
)


@dataclass(frozen=True)
class BaseAdmissionRegistrationV1Row(UIRow, ABC):
    """Base class for Admission Registration V1 API resources."""

    api_info: ClassVar[ApiInfo] = admissionregistration_v1_api
    category: ClassVar[str] = CATEGORIES["Config"].name

    webhooks: str = column_field(label="Webhooks", width=5)
    age: str = column_field(label="Age", width=10, is_age=True)

    @abstractmethod
    def __init__(self, raw: Any):
        """Initialize the base admission registration row."""
        super().__init__(raw=raw)
        if hasattr(self.raw, "webhooks"):
            object.__setattr__(self, "webhooks", str(len(self.raw.webhooks)))
        else:
            object.__setattr__(self, "webhooks", "0")


@dataclass(frozen=True)
class MutatingWebhookConfigurationRow(BaseAdmissionRegistrationV1Row):
    """Represents a MutatingWebhookConfiguration for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "MutatingWebhookConfiguration"
    plural: ClassVar[str] = "mutatingwebhookconfigurations"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Mutating Webhook Configurations"
    index: ClassVar[int] = 4

    def __init__(self, raw: Any):
        """Initialize the mutating webhook configuration row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)


@dataclass(frozen=True)
class ValidatingWebhookConfigurationRow(BaseAdmissionRegistrationV1Row):
    """Represents a ValidatingWebhookConfiguration for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "ValidatingWebhookConfiguration"
    plural: ClassVar[str] = "validatingwebhookconfigurations"
    namespaced: ClassVar[bool] = False
    display_name: ClassVar[str] = "Validating Webhook Configurations"
    resource_name_snake: ClassVar[str] = "validating_webhook_configuration"
    index: ClassVar[int] = 3

    def __init__(self, raw: Any):
        """Initialize the validating webhook configuration row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
