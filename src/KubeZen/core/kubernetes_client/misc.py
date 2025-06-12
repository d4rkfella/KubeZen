from typing import Any


class MiscMixin:
    app_services: Any = None  # This will be set by the parent class

    # Removed get_pod_logs to avoid conflict with LogsMixin
