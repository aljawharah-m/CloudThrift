"""
CloudThrift Azure Telemetry Collector

Collects real telemetry from an Azure Virtual Machine Scale Set and
normalizes it for the CloudThrift Decision Engine.

Collected values:
- Average CPU percentage
- Network throughput in Mbps
- Current VM Scale Set instance count
- Budget usage percentage
- Requests per minute when provided externally

Authentication:
- Local development: Azure CLI credentials
- Azure deployment: Managed Identity through DefaultAzureCredential
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from azure.core.exceptions import AzureError, ClientAuthenticationError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cloudthrift.telemetry_collector")


DEFAULT_SUBSCRIPTION_ID = "58c0ae28-0f9a-4e69-93f9-c70697185cbe"
DEFAULT_RESOURCE_GROUP_NAME = "rg-cloudthrift"
DEFAULT_VM_SCALE_SET_NAME = "cloudthrift-development-vmss"
DEFAULT_ENVIRONMENT = "development"

CPU_METRIC_NAME = "Percentage CPU"
NETWORK_IN_METRIC_NAME = "Network In Total"
NETWORK_OUT_METRIC_NAME = "Network Out Total"

METRIC_INTERVAL = "PT1M"
METRIC_AGGREGATION = "Average,Total"
METRIC_LOOKBACK_MINUTES = 10


@dataclass(frozen=True)
class TelemetrySnapshot:
    cpu_percent: float
    network_mbps: float
    requests_per_minute: int
    current_instances: int
    budget_used_percent: float
    environment: str
    collected_at_utc: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def get_environment_variable(
    name: str,
    default: str | None = None,
    *,
    required: bool = False,
) -> str:
    value = os.getenv(name, default)

    if required and not value:
        raise ValueError(
            f"Required environment variable is missing: {name}"
        )

    if value is None:
        return ""

    return value.strip()


def get_float_environment_variable(
    name: str,
    default: float,
) -> float:
    raw_value = os.getenv(name)

    if raw_value is None or not raw_value.strip():
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be numeric."
        ) from exc


def get_integer_environment_variable(
    name: str,
    default: int,
) -> int:
    raw_value = os.getenv(name)

    if raw_value is None or not raw_value.strip():
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be an integer."
        ) from exc


def validate_telemetry(snapshot: TelemetrySnapshot) -> list[str]:
    errors: list[str] = []

    if not 0 <= snapshot.cpu_percent <= 100:
        errors.append("CPU percentage must be between 0 and 100.")

    if snapshot.network_mbps < 0:
        errors.append("Network throughput cannot be negative.")

    if snapshot.requests_per_minute < 0:
        errors.append("Requests per minute cannot be negative.")

    if snapshot.current_instances < 1:
        errors.append("Current instance count must be at least 1.")

    if snapshot.budget_used_percent < 0:
        errors.append("Budget usage percentage cannot be negative.")

    return errors


def build_vmss_resource_id(
    subscription_id: str,
    resource_group_name: str,
    vm_scale_set_name: str,
) -> str:
    return (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group_name}"
        "/providers/Microsoft.Compute"
        f"/virtualMachineScaleSets/{vm_scale_set_name}"
    )


def safe_numeric_values(
    values: Iterable[float | int | None],
) -> list[float]:
    return [
        float(value)
        for value in values
        if value is not None
    ]


class TelemetryCollector:
    def __init__(
        self,
        *,
        subscription_id: str | None = None,
        resource_group_name: str | None = None,
        vm_scale_set_name: str | None = None,
        environment: str | None = None,
    ) -> None:
        self.subscription_id = (
            subscription_id
            or get_environment_variable(
                "AZURE_SUBSCRIPTION_ID",
                DEFAULT_SUBSCRIPTION_ID,
            )
        )

        self.resource_group_name = (
            resource_group_name
            or get_environment_variable(
                "AZURE_RESOURCE_GROUP_NAME",
                DEFAULT_RESOURCE_GROUP_NAME,
            )
        )

        self.vm_scale_set_name = (
            vm_scale_set_name
            or get_environment_variable(
                "AZURE_VMSS_NAME",
                DEFAULT_VM_SCALE_SET_NAME,
            )
        )

        self.environment = (
            environment
            or get_environment_variable(
                "CLOUDTHRIFT_ENVIRONMENT",
                DEFAULT_ENVIRONMENT,
            )
        )

        if not self.subscription_id:
            raise ValueError("Azure subscription ID cannot be empty.")

        self.credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False,
        )

        self.compute_client = ComputeManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

        self.monitor_client = MonitorManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

        self.vmss_resource_id = build_vmss_resource_id(
            subscription_id=self.subscription_id,
            resource_group_name=self.resource_group_name,
            vm_scale_set_name=self.vm_scale_set_name,
        )

    def get_current_instance_count(self) -> int:
        logger.info(
            "Reading current VMSS instance count | "
            "resource_group=%s | vmss=%s",
            self.resource_group_name,
            self.vm_scale_set_name,
        )

        vm_scale_set = self.compute_client.virtual_machine_scale_sets.get(
            resource_group_name=self.resource_group_name,
            vm_scale_set_name=self.vm_scale_set_name,
        )

        capacity = getattr(
            getattr(vm_scale_set, "sku", None),
            "capacity",
            None,
        )

        if capacity is None:
            logger.warning(
                "VMSS SKU capacity was unavailable. "
                "Counting VMSS instances directly."
            )

            instances = list(
                self.compute_client.virtual_machine_scale_set_vms.list(
                    resource_group_name=self.resource_group_name,
                    virtual_machine_scale_set_name=self.vm_scale_set_name,
                )
            )

            capacity = len(instances)

        instance_count = int(capacity)

        if instance_count < 1:
            raise ValueError(
                "Azure returned an invalid VMSS instance count."
            )

        logger.info(
            "Current VMSS instance count=%d",
            instance_count,
        )

        return instance_count

    def query_metrics(self) -> dict[str, float]:
        end_time = utc_now()
        start_time = end_time - timedelta(
            minutes=METRIC_LOOKBACK_MINUTES,
        )

        start_time_iso = start_time.replace(
            microsecond=0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        end_time_iso = end_time.replace(
            microsecond=0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        timespan = f"{start_time_iso}/{end_time_iso}"

        logger.info(
            "Querying Azure Monitor metrics | "
            "resource=%s | lookback=%d minutes",
            self.vm_scale_set_name,
            METRIC_LOOKBACK_MINUTES,
        )

        result = self.monitor_client.metrics.list(
            resource_uri=self.vmss_resource_id,
            timespan=timespan,
            interval=METRIC_INTERVAL,
            metricnames=",".join(
                [
                    CPU_METRIC_NAME,
                    NETWORK_IN_METRIC_NAME,
                    NETWORK_OUT_METRIC_NAME,
                ]
            ),
            aggregation=METRIC_AGGREGATION,
        )

        cpu_values: list[float] = []
        network_in_bytes: list[float] = []
        network_out_bytes: list[float] = []

        for metric in result.value:
            metric_name = metric.name.value

            for time_series in metric.timeseries:
                for data_point in time_series.data:
                    if metric_name == CPU_METRIC_NAME:
                        cpu_values.extend(
                            safe_numeric_values(
                                [data_point.average]
                            )
                        )

                    elif metric_name == NETWORK_IN_METRIC_NAME:
                        network_in_bytes.extend(
                            safe_numeric_values(
                                [
                                    data_point.total,
                                    data_point.average,
                                ]
                            )[:1]
                        )

                    elif metric_name == NETWORK_OUT_METRIC_NAME:
                        network_out_bytes.extend(
                            safe_numeric_values(
                                [
                                    data_point.total,
                                    data_point.average,
                                ]
                            )[:1]
                        )

        average_cpu = (
            sum(cpu_values) / len(cpu_values)
            if cpu_values
            else 0.0
        )

        total_network_bytes = (
            sum(network_in_bytes)
            + sum(network_out_bytes)
        )

        sample_count = max(
            len(network_in_bytes),
            len(network_out_bytes),
            1,
        )

        average_bytes_per_minute = (
            total_network_bytes / sample_count
        )

        network_mbps = (
            average_bytes_per_minute
            * 8
            / 60
            / 1_000_000
        )

        logger.info(
            "Azure metrics collected | CPU=%.2f%% | "
            "Network=%.4f Mbps",
            average_cpu,
            network_mbps,
        )

        return {
            "cpu_percent": round(
                max(0.0, min(average_cpu, 100.0)),
                2,
            ),
            "network_mbps": round(
                max(0.0, network_mbps),
                4,
            ),
        }

    def collect_azure_snapshot(
        self,
        *,
        requests_per_minute: int | None = None,
        budget_used_percent: float | None = None,
    ) -> TelemetrySnapshot:
        logger.info(
            "Collecting live Azure telemetry | "
            "environment=%s",
            self.environment,
        )

        current_instances = self.get_current_instance_count()
        metrics = self.query_metrics()

        resolved_requests_per_minute = (
            requests_per_minute
            if requests_per_minute is not None
            else get_integer_environment_variable(
                "CLOUDTHRIFT_REQUESTS_PER_MINUTE",
                0,
            )
        )

        resolved_budget_used_percent = (
            budget_used_percent
            if budget_used_percent is not None
            else get_float_environment_variable(
                "CLOUDTHRIFT_BUDGET_USED_PERCENT",
                0.0,
            )
        )

        snapshot = TelemetrySnapshot(
            cpu_percent=metrics["cpu_percent"],
            network_mbps=metrics["network_mbps"],
            requests_per_minute=resolved_requests_per_minute,
            current_instances=current_instances,
            budget_used_percent=round(
                resolved_budget_used_percent,
                2,
            ),
            environment=self.environment,
            collected_at_utc=utc_now_iso(),
            source="azure-monitor",
        )

        errors = validate_telemetry(snapshot)

        if errors:
            raise ValueError(
                "Invalid telemetry snapshot: "
                + " | ".join(errors)
            )

        logger.info(
            "Telemetry collected successfully | "
            "CPU=%.2f%% | Network=%.4f Mbps | "
            "Requests=%d/min | Instances=%d | "
            "Budget=%.2f%%",
            snapshot.cpu_percent,
            snapshot.network_mbps,
            snapshot.requests_per_minute,
            snapshot.current_instances,
            snapshot.budget_used_percent,
        )

        return snapshot


def run_demo() -> None:
    try:
        collector = TelemetryCollector()
        snapshot = collector.collect_azure_snapshot()

        print(
            json.dumps(
                snapshot.to_dict(),
                indent=2,
            )
        )

    except ClientAuthenticationError as exc:
        logger.error(
            "Azure authentication failed. "
            "Run 'az login' and try again."
        )
        raise SystemExit(1) from exc

    except AzureError as exc:
        logger.error(
            "Azure API request failed: %s",
            exc,
        )
        raise SystemExit(1) from exc

    except (ValueError, RuntimeError) as exc:
        logger.error(
            "Telemetry collection failed: %s",
            exc,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    run_demo()