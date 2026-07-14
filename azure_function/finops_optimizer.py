"""
CloudThrift FinOps Optimizer

Tracks VMSS utilization across Azure Function executions and determines
whether sustained low utilization justifies a safe capacity reduction.

State is persisted in Azure Table Storage so the observation window
continues across separate timer-trigger executions.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.data.tables import TableServiceClient


logger = logging.getLogger("cloudthrift.finops")


class FinOpsStatus(str, Enum):
    OBSERVING = "OBSERVING"
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    MINIMUM_CAPACITY = "MINIMUM_CAPACITY"
    STATE_RESET = "STATE_RESET"


@dataclass(frozen=True)
class FinOpsAssessment:
    resource: str
    status: FinOpsStatus
    average_cpu_percent: float
    latest_cpu_percent: float
    observation_window_minutes: int
    observed_duration_minutes: float
    sample_count: int
    previous_capacity: int
    optimized_capacity: int
    estimated_hourly_savings: float
    estimated_monthly_savings: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


class FinOpsOptimizer:
    """
    Detect sustained VMSS underutilization.

    A scale-in recommendation is produced only when:

    - CPU stays below the configured threshold.
    - The low-usage condition lasts for the full observation window.
    - Samples remain reasonably continuous.
    - Current capacity is greater than the protected minimum.
    """

    def __init__(
        self,
        *,
        environment: str = "development",
        vmss_name: str | None = None,
        low_cpu_threshold_percent: float = 10.0,
        observation_window_minutes: int = 30,
        minimum_instances: int = 1,
        maximum_sample_gap_minutes: int = 10,
        instance_hourly_cost: float | None = None,
        storage_connection_string: str | None = None,
        table_name: str = "CloudThriftFinOps",
    ) -> None:
        self.environment = environment
        self.vmss_name = (
            vmss_name
            or os.getenv("AZURE_VMSS_NAME")
            or f"cloudthrift-{environment}-vmss"
        )

        self.low_cpu_threshold_percent = float(
            os.getenv(
                "FINOPS_LOW_CPU_THRESHOLD",
                str(low_cpu_threshold_percent),
            )
        )

        self.observation_window_minutes = int(
            os.getenv(
                "FINOPS_OBSERVATION_WINDOW_MINUTES",
                str(observation_window_minutes),
            )
        )

        self.minimum_instances = int(
            os.getenv(
                "FINOPS_MINIMUM_INSTANCES",
                str(minimum_instances),
            )
        )

        self.maximum_sample_gap_minutes = (
            maximum_sample_gap_minutes
        )
        configured_hourly_cost = (
            instance_hourly_cost
            if instance_hourly_cost is not None
            else os.getenv(
                "CLOUDTHRIFT_INSTANCE_HOURLY_COST",
                "0",
            )
        )

        self.instance_hourly_cost = float(
            configured_hourly_cost
        )

        self.storage_connection_string = (
            storage_connection_string
            or os.getenv("AzureWebJobsStorage")
        )

        if not self.storage_connection_string:
            raise ValueError(
                "AzureWebJobsStorage is required for persistent "
                "FinOps observation tracking."
            )

        self.table_service = (
            TableServiceClient.from_connection_string(
                self.storage_connection_string
            )
        )

        try:
            self.table_service.create_table(
                table_name=table_name
            )
        except ResourceExistsError:
            pass

        self.table_client = (
            self.table_service.get_table_client(
                table_name=table_name
            )
        )

    def assess(
        self,
        *,
        cpu_percent: float,
        current_instances: int,
        observed_at: datetime | None = None,
    ) -> FinOpsAssessment:
        now = observed_at or datetime.now(timezone.utc)

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if current_instances <= self.minimum_instances:
            self._delete_state()

            return self._build_assessment(
                status=FinOpsStatus.MINIMUM_CAPACITY,
                average_cpu_percent=cpu_percent,
                latest_cpu_percent=cpu_percent,
                observed_duration_minutes=0.0,
                sample_count=1,
                previous_capacity=current_instances,
                optimized_capacity=current_instances,
                reason=(
                    "VMSS is already at the protected minimum "
                    "capacity."
                ),
            )

        if cpu_percent > self.low_cpu_threshold_percent:
            self._delete_state()

            return self._build_assessment(
                status=FinOpsStatus.NOT_ELIGIBLE,
                average_cpu_percent=cpu_percent,
                latest_cpu_percent=cpu_percent,
                observed_duration_minutes=0.0,
                sample_count=1,
                previous_capacity=current_instances,
                optimized_capacity=current_instances,
                reason=(
                    f"CPU {cpu_percent:.2f}% is above the "
                    f"{self.low_cpu_threshold_percent:.2f}% "
                    "FinOps threshold."
                ),
            )

        state = self._get_state()

        if state is None:
            self._save_state(
                first_low_at=now,
                last_sample_at=now,
                cpu_sum=cpu_percent,
                sample_count=1,
            )

            return self._build_assessment(
                status=FinOpsStatus.OBSERVING,
                average_cpu_percent=cpu_percent,
                latest_cpu_percent=cpu_percent,
                observed_duration_minutes=0.0,
                sample_count=1,
                previous_capacity=current_instances,
                optimized_capacity=current_instances,
                reason=(
                    "Low utilization detected. The persistent "
                    "observation window has started."
                ),
            )

        first_low_at = self._parse_timestamp(
            state["FirstLowAt"]
        )
        last_sample_at = self._parse_timestamp(
            state["LastSampleAt"]
        )

        sample_gap_minutes = (
            now - last_sample_at
        ).total_seconds() / 60

        if (
            sample_gap_minutes
            > self.maximum_sample_gap_minutes
        ):
            self._save_state(
                first_low_at=now,
                last_sample_at=now,
                cpu_sum=cpu_percent,
                sample_count=1,
            )

            return self._build_assessment(
                status=FinOpsStatus.STATE_RESET,
                average_cpu_percent=cpu_percent,
                latest_cpu_percent=cpu_percent,
                observed_duration_minutes=0.0,
                sample_count=1,
                previous_capacity=current_instances,
                optimized_capacity=current_instances,
                reason=(
                    "Observation state was reset because the gap "
                    f"between samples reached "
                    f"{sample_gap_minutes:.1f} minutes."
                ),
            )

        cpu_sum = float(state["CpuSum"]) + cpu_percent
        sample_count = int(state["SampleCount"]) + 1

        observed_duration_minutes = (
            now - first_low_at
        ).total_seconds() / 60

        average_cpu_percent = cpu_sum / sample_count

        self._save_state(
            first_low_at=first_low_at,
            last_sample_at=now,
            cpu_sum=cpu_sum,
            sample_count=sample_count,
        )

        if (
            observed_duration_minutes
            < self.observation_window_minutes
        ):
            remaining_minutes = max(
                0.0,
                self.observation_window_minutes
                - observed_duration_minutes,
            )

            return self._build_assessment(
                status=FinOpsStatus.OBSERVING,
                average_cpu_percent=average_cpu_percent,
                latest_cpu_percent=cpu_percent,
                observed_duration_minutes=(
                    observed_duration_minutes
                ),
                sample_count=sample_count,
                previous_capacity=current_instances,
                optimized_capacity=current_instances,
                reason=(
                    "Low utilization remains sustained. "
                    f"Approximately {remaining_minutes:.1f} "
                    "minutes remain in the observation window."
                ),
            )

        optimized_capacity = max(
            self.minimum_instances,
            current_instances - 1,
        )

        return self._build_assessment(
            status=FinOpsStatus.ELIGIBLE,
            average_cpu_percent=average_cpu_percent,
            latest_cpu_percent=cpu_percent,
            observed_duration_minutes=(
                observed_duration_minutes
            ),
            sample_count=sample_count,
            previous_capacity=current_instances,
            optimized_capacity=optimized_capacity,
            reason=(
                "Sustained low utilization was verified across "
                "the full observation window. A safe capacity "
                "reduction is recommended."
            ),
        )

    def clear_observation_state(self) -> None:
        self._delete_state()

    def _build_assessment(
        self,
        *,
        status: FinOpsStatus,
        average_cpu_percent: float,
        latest_cpu_percent: float,
        observed_duration_minutes: float,
        sample_count: int,
        previous_capacity: int,
        optimized_capacity: int,
        reason: str,
    ) -> FinOpsAssessment:
        removed_instances = max(
            0,
            previous_capacity - optimized_capacity,
        )

        estimated_hourly_savings = (
            removed_instances * self.instance_hourly_cost
        )

        estimated_monthly_savings = (
            estimated_hourly_savings * 730
        )

        return FinOpsAssessment(
            resource=self.vmss_name,
            status=status,
            average_cpu_percent=round(
                average_cpu_percent,
                2,
            ),
            latest_cpu_percent=round(
                latest_cpu_percent,
                2,
            ),
            observation_window_minutes=(
                self.observation_window_minutes
            ),
            observed_duration_minutes=round(
                observed_duration_minutes,
                2,
            ),
            sample_count=sample_count,
            previous_capacity=previous_capacity,
            optimized_capacity=optimized_capacity,
            estimated_hourly_savings=round(
                estimated_hourly_savings,
                4,
            ),
            estimated_monthly_savings=round(
                estimated_monthly_savings,
                2,
            ),
            reason=reason,
        )

    def _get_state(self) -> dict[str, Any] | None:
        try:
            entity = self.table_client.get_entity(
                partition_key=self.environment,
                row_key=self.vmss_name,
            )
            return dict(entity)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)

            if status_code == 404:
                return None

            raise

    def _save_state(
        self,
        *,
        first_low_at: datetime,
        last_sample_at: datetime,
        cpu_sum: float,
        sample_count: int,
    ) -> None:
        entity = {
            "PartitionKey": self.environment,
            "RowKey": self.vmss_name,
            "FirstLowAt": first_low_at.isoformat(),
            "LastSampleAt": last_sample_at.isoformat(),
            "CpuSum": float(cpu_sum),
            "SampleCount": int(sample_count),
        }

        self.table_client.upsert_entity(
            entity=entity,
            mode="replace",
        )

        logger.info(
            "FinOps observation state saved | "
            "resource=%s | samples=%s",
            self.vmss_name,
            sample_count,
        )

    def _delete_state(self) -> None:
        try:
            self.table_client.delete_entity(
                partition_key=self.environment,
                row_key=self.vmss_name,
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)

            if status_code != 404:
                raise

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed