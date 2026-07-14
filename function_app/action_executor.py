"""
CloudThrift Azure Action Executor

Executes or simulates infrastructure scaling actions produced by the
CloudThrift Decision Engine.

Supported actions:
- SCALE_OUT
- SCALE_IN
- NO_ACTION
- Any blocked or non-scaling decision is safely skipped

Authentication:
- Local development: Azure CLI credentials
- Azure deployment: Managed Identity through DefaultAzureCredential
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from azure.core.exceptions import AzureError, ClientAuthenticationError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cloudthrift.action_executor")


DEFAULT_SUBSCRIPTION_ID = (
    "58c0ae28-0f9a-4e69-93f9-c70697185cbe"
)
DEFAULT_RESOURCE_GROUP_NAME = "rg-cloudthrift"
DEFAULT_VM_SCALE_SET_NAME = "cloudthrift-development-vmss"

SUPPORTED_SCALING_ACTIONS = {
    "SCALE_OUT",
    "SCALE_IN",
}

NON_EXECUTABLE_ACTIONS = {
    "NO_ACTION",
    "BLOCKED_BY_BUDGET",
    "BLOCKED_BY_COOLDOWN",
    "BLOCKED_BY_PROTECTION",
    "POLICY_DISABLED",
    "INVALID_STATE",
}


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    SIMULATED = "SIMULATED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    action: str
    current_instances: int
    target_instances: int
    message: str
    executed_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_environment_variable(
    name: str,
    default: str,
) -> str:
    value = os.getenv(name, default).strip()

    if not value:
        raise ValueError(
            f"Environment variable {name} cannot be empty."
        )

    return value


class ActionExecutor:
    def __init__(
        self,
        *,
        subscription_id: str | None = None,
        resource_group_name: str | None = None,
        vm_scale_set_name: str | None = None,
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

        self.credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False,
        )

        self.compute_client = ComputeManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

    def get_actual_instance_count(self) -> int:
        logger.info(
            "Reading actual VMSS capacity | "
            "resource_group=%s | vmss=%s",
            self.resource_group_name,
            self.vm_scale_set_name,
        )

        vm_scale_set = (
            self.compute_client.virtual_machine_scale_sets.get(
                resource_group_name=self.resource_group_name,
                vm_scale_set_name=self.vm_scale_set_name,
            )
        )

        capacity = getattr(
            getattr(vm_scale_set, "sku", None),
            "capacity",
            None,
        )

        if capacity is None:
            instances = list(
                self.compute_client.virtual_machine_scale_set_vms.list(
                    resource_group_name=self.resource_group_name,
                    virtual_machine_scale_set_name=(
                        self.vm_scale_set_name
                    ),
                )
            )

            capacity = len(instances)

        actual_count = int(capacity)

        if actual_count < 0:
            raise ValueError(
                "Azure returned an invalid VMSS capacity."
            )

        logger.info(
            "Actual VMSS capacity=%d",
            actual_count,
        )

        return actual_count

    def update_vmss_capacity(
        self,
        target_instances: int,
    ) -> int:
        if target_instances < 1:
            raise ValueError(
                "Target instance count must be at least 1."
            )

        logger.info(
            "Updating Azure VMSS capacity | "
            "vmss=%s | target=%d",
            self.vm_scale_set_name,
            target_instances,
        )

        update_parameters = {
            "sku": {
                "capacity": target_instances,
            }
        }

        poller = (
            self.compute_client.virtual_machine_scale_sets.begin_update(
                resource_group_name=self.resource_group_name,
                vm_scale_set_name=self.vm_scale_set_name,
                parameters=update_parameters,
            )
        )

        poller.result()

        final_instance_count = self.get_actual_instance_count()

        logger.info(
            "Azure VMSS capacity update completed | "
            "final_instances=%d",
            final_instance_count,
        )

        return final_instance_count

    def execute(
        self,
        *,
        action: str,
        current_instances: int,
        target_instances: int,
        dry_run: bool,
    ) -> ExecutionResult:
        normalized_action = action.strip().upper()

        logger.info(
            "Processing infrastructure action | "
            "Action=%s | Current=%d | Target=%d | DryRun=%s",
            normalized_action,
            current_instances,
            target_instances,
            dry_run,
        )

        if current_instances < 0:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "Current instance count cannot be negative."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if target_instances < 1:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "Target instance count must be at least 1."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if normalized_action in NON_EXECUTABLE_ACTIONS:
            return ExecutionResult(
                status=ExecutionStatus.SKIPPED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "The decision does not require an Azure "
                    "infrastructure change."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if normalized_action not in SUPPORTED_SCALING_ACTIONS:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    f"Unsupported infrastructure action: "
                    f"{normalized_action}"
                ),
                executed_at_utc=utc_now_iso(),
            )

        if target_instances == current_instances:
            return ExecutionResult(
                status=ExecutionStatus.SKIPPED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "The requested action does not change "
                    "the instance count."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if (
            normalized_action == "SCALE_OUT"
            and target_instances <= current_instances
        ):
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "SCALE_OUT requires a target count greater "
                    "than the current count."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if (
            normalized_action == "SCALE_IN"
            and target_instances >= current_instances
        ):
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "SCALE_IN requires a target count lower "
                    "than the current count."
                ),
                executed_at_utc=utc_now_iso(),
            )

        if dry_run:
            logger.info(
                "Dry-run enabled. Azure VMSS will not be modified."
            )

            return ExecutionResult(
                status=ExecutionStatus.SIMULATED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "The infrastructure action was simulated. "
                    "No Azure resources were modified."
                ),
                executed_at_utc=utc_now_iso(),
            )

        try:
            actual_current_instances = (
                self.get_actual_instance_count()
            )

            if actual_current_instances != current_instances:
                logger.warning(
                    "Decision state differs from Azure state | "
                    "decision_current=%d | azure_current=%d",
                    current_instances,
                    actual_current_instances,
                )

            if target_instances == actual_current_instances:
                return ExecutionResult(
                    status=ExecutionStatus.SKIPPED,
                    action=normalized_action,
                    current_instances=actual_current_instances,
                    target_instances=target_instances,
                    message=(
                        "Azure VMSS is already operating at "
                        "the requested capacity."
                    ),
                    executed_at_utc=utc_now_iso(),
                )

            final_instance_count = self.update_vmss_capacity(
                target_instances
            )

            if final_instance_count != target_instances:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    action=normalized_action,
                    current_instances=actual_current_instances,
                    target_instances=target_instances,
                    message=(
                        "Azure accepted the scaling operation, "
                        "but the verified final capacity does not "
                        "match the requested target."
                    ),
                    executed_at_utc=utc_now_iso(),
                )

            return ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                action=normalized_action,
                current_instances=actual_current_instances,
                target_instances=final_instance_count,
                message=(
                    "Azure VMSS capacity was updated successfully "
                    f"from {actual_current_instances} to "
                    f"{final_instance_count} instances."
                ),
                executed_at_utc=utc_now_iso(),
            )

        except ClientAuthenticationError as exc:
            logger.exception(
                "Azure authentication failed."
            )

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "Azure authentication failed. Run 'az login' "
                    f"and try again. Details: {exc}"
                ),
                executed_at_utc=utc_now_iso(),
            )

        except AzureError as exc:
            logger.exception(
                "Azure API request failed."
            )

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "Azure rejected the infrastructure action. "
                    f"Details: {exc}"
                ),
                executed_at_utc=utc_now_iso(),
            )

        except (ValueError, RuntimeError) as exc:
            logger.exception(
                "Infrastructure action failed."
            )

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                action=normalized_action,
                current_instances=current_instances,
                target_instances=target_instances,
                message=(
                    "The infrastructure action failed validation. "
                    f"Details: {exc}"
                ),
                executed_at_utc=utc_now_iso(),
            )