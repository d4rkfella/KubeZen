from abc import abstractmethod
from .base import (
    UIRow,
    CATEGORIES,
    ApiInfo,
    dataclass,
    Any,
    ClassVar,
    column_field,
    batch_v1_api,
    ABC,
)
from datetime import datetime, timezone
from croniter import croniter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BaseBatchV1Row(UIRow, ABC):
    """Base class for Batch V1 API resources."""

    api_info: ClassVar[ApiInfo] = batch_v1_api
    category: ClassVar[str] = CATEGORIES["Workloads"].name

    age: str = column_field(label="Age", width=10, is_age=True, index=999)

    @abstractmethod
    def __init__(self, raw: Any):
        super().__init__(raw=raw)


@dataclass(frozen=True)
class JobRow(BaseBatchV1Row):
    """Represents a Job for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "Job"
    plural: ClassVar[str] = "jobs"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "Jobs"
    index: ClassVar[int] = 1

    # --- Instance Fields ---
    completion: str = column_field(label="Completion", width=10)
    conditions: str = column_field(label="Conditions", width=10)

    def __init__(self, raw: Any):
        """Initialize the job row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)

        succeeded = self.raw.status.succeeded or 0
        completions = self.raw.spec.completions or 1

        object.__setattr__(self, "completion", f"{succeeded}/{completions}")
        object.__setattr__(self, "conditions", self._get_condition_type())

    def _get_condition_type(self) -> str:
        """
        Determines the status of a Job from its conditions by returning the
        type of the first condition found.
        """
        if self.raw.status and self.raw.status.conditions:
            return str(self.raw.status.conditions[0].type)

        return "Unknown"


@dataclass(frozen=True)
class CronJobRow(BaseBatchV1Row):
    """Represents a CronJob for UI display."""

    # --- API Metadata ---
    kind: ClassVar[str] = "CronJob"
    plural: ClassVar[str] = "cronjobs"
    resource_name_snake: ClassVar[str] = "cron_job"
    namespaced: ClassVar[bool] = True
    display_name: ClassVar[str] = "CronJobs"
    index: ClassVar[int] = 2

    # --- Instance Fields ---
    schedule: str = column_field(label="Schedule", width=10)
    suspend: str = column_field(label="Suspend", width=10)
    active: int = column_field(label="Active", width=8)
    last_schedule: str = column_field(label="Last Schedule", width=10, is_age=True)
    next_execution: str = column_field(
        label="Next Execution", width=10, is_countdown=True
    )
    time_zone: str = column_field(label="Time zone", width=15)

    def __init__(self, raw: Any):
        """Initialize the cron job row with data from the raw Kubernetes resource."""
        super().__init__(raw=raw)
        object.__setattr__(self, "schedule", self.raw.spec.schedule)
        object.__setattr__(self, "time_zone", self.raw.spec.time_zone or "-")
        object.__setattr__(
            self, "active", len(self.raw.status.active) if self.raw.status.active else 0
        )
        object.__setattr__(self, "suspend", str(self.raw.spec.suspend))
        object.__setattr__(self, "next_execution", self._get_next_schedule())
        object.__setattr__(
            self, "last_schedule", self.to_datetime(self.raw.status.last_schedule_time)
        )

    def _get_next_schedule(self) -> datetime | None:
        """Calculates the next scheduled time for the cronjob."""
        if self.raw.spec.suspend:
            return None

        # Use the last scheduled time as the base for calculation,
        # falling back to the current time if it's not available.
        base_time = self.to_datetime(
            self.raw.status.last_schedule_time
        ) or datetime.now(timezone.utc)

        try:
            schedule = self.raw.spec.schedule
            tz_str = self.raw.spec.time_zone

            # If a timezone is specified in the spec, we must use it for calculation.
            if tz_str:
                try:
                    target_tz = ZoneInfo(tz_str)
                    # Convert the base time (which is in UTC) to the target timezone.
                    base_time_local = base_time.astimezone(target_tz)
                    cron = croniter(schedule, base_time_local)
                    return cron.get_next(datetime)
                except ZoneInfoNotFoundError:
                    log.warning(
                        f"Invalid timezone '{tz_str}' in CronJob {self.raw.metadata.name}"
                    )
                    return None  # Can't calculate if timezone is invalid

            # If no timezone is specified, assume the schedule is in UTC.
            cron = croniter(schedule, base_time)
            return cron.get_next(datetime)
        except Exception as e:
            log.error(
                f"Error calculating next schedule for {self.raw.metadata.name}: {e}"
            )
            return None
