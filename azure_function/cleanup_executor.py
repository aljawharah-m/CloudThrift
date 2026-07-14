"""
CloudThrift Safe Multi-Resource Cleanup Executor

Deletion requires:
1. An allowed environment tag.
2. cloudthrift_cleanup=true.
3. No cloudthrift_protected=true tag.
4. A non-protected resource group.
5. A supported waste type.
6. The minimum resource age.
7. A second live validation immediately before deletion.
8. dry_run=false.

Supported cleanup types:
- Public IP
- Network Interface
- Managed Disk
- Network Security Group
- Route Table
- Load Balancer
- Application Gateway
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from azure.core.exceptions import (
    AzureError,
    ResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient


logger = logging.getLogger("cloudthrift.cleanup_executor")


DEFAULT_SUBSCRIPTION_ID = (
    "58c0ae28-0f9a-4e69-93f9-c70697185cbe"
)


SUPPORTED_WASTE_TYPES = {
    "UNASSOCIATED_PUBLIC_IP",
    "UNUSED_NETWORK_INTERFACE",
    "UNATTACHED_DISK",
    "UNUSED_NETWORK_SECURITY_GROUP",
    "UNUSED_ROUTE_TABLE",
    "EMPTY_LOAD_BALANCER",
    "EMPTY_APPLICATION_GATEWAY",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def normalize_text(
    value: Any,
) -> str:
    return str(value or "").strip().lower()


def count_items(
    value: Any,
) -> int:
    if value is None:
        return 0

    try:
        return len(value)
    except TypeError:
        return 0


class CleanupExecutor:
    def __init__(
        self,
        *,
        subscription_id: str | None = None,
    ) -> None:
        self.subscription_id = (
            subscription_id
            or os.getenv(
                "AZURE_SUBSCRIPTION_ID",
                DEFAULT_SUBSCRIPTION_ID,
            )
        )

        self.credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False,
        )

        self.network_client = NetworkManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

        self.compute_client = ComputeManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

        project_root = Path(__file__).resolve().parent.parent

        self.policy_path = (
            project_root
            / "policies"
            / "cleanup_policy.json"
        )

        with self.policy_path.open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            self.policy = json.load(file)

    def _parse_created_at(
        self,
        resource: dict[str, Any],
    ) -> datetime | None:
        raw_value = (
            resource.get("createdAt")
            or resource.get("timeCreated")
            or (resource.get("tags") or {}).get("createdAt")
        )

        if not raw_value:
            return None

        text = str(raw_value).strip()

        if not text:
            return None

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc,
            )

        return parsed.astimezone(timezone.utc)

    def _resource_age_days(
        self,
        resource: dict[str, Any],
    ) -> float | None:
        created_at = self._parse_created_at(resource)

        if created_at is None:
            return None

        age = utc_now() - created_at

        return max(
            age.total_seconds() / 86400,
            0.0,
        )

    def is_cleanup_allowed(
        self,
        resource: dict[str, Any],
    ) -> tuple[bool, str]:
        tags = resource.get("tags") or {}

        if not isinstance(tags, dict):
            tags = {}

        waste_type = str(
            resource.get("waste_type", "")
        ).strip().upper()

        resource_group = normalize_text(
            resource.get("resourceGroup")
        )

        allowed_environments = {
            normalize_text(value)
            for value in self.policy.get(
                "allowed_environments",
                ["development", "test"],
            )
        }

        protected_resource_groups = {
            normalize_text(value)
            for value in self.policy.get(
                "protected_resource_groups",
                [],
            )
        }

        required_tag = str(
            self.policy.get(
                "required_cleanup_tag",
                "cloudthrift_cleanup",
            )
        )

        required_tag_value = normalize_text(
            self.policy.get(
                "required_cleanup_tag_value",
                "true",
            )
        )

        protected_tag = str(
            self.policy.get(
                "protected_tag",
                "cloudthrift_protected",
            )
        )

        protected_tag_value = normalize_text(
            self.policy.get(
                "protected_tag_value",
                "true",
            )
        )

        environment = normalize_text(
            tags.get("environment")
        )

        cleanup_enabled = normalize_text(
            tags.get(required_tag)
        )

        protected = normalize_text(
            tags.get(protected_tag)
        )

        if not self.policy.get("enabled", False):
            return False, "Cleanup policy is disabled."

        if waste_type not in SUPPORTED_WASTE_TYPES:
            return False, (
                "Resource waste type is not supported."
            )

        if environment not in allowed_environments:
            return False, (
                "Resource environment is not allowed."
            )

        if cleanup_enabled != required_tag_value:
            return False, (
                "Required cleanup approval tag is missing."
            )

        if protected == protected_tag_value:
            return False, "Resource is protected."

        if resource_group in protected_resource_groups:
            return False, (
                "Resource group is protected by cleanup policy."
            )

        minimum_age_days = float(
            self.policy.get(
                "minimum_resource_age_days",
                1,
            )
        )

        age_days = self._resource_age_days(resource)

        require_known_age = bool(
            self.policy.get(
                "require_known_resource_age",
                True,
            )
        )

        if age_days is None and require_known_age:
            return False, (
                "Resource creation time is unknown."
            )

        if (
            age_days is not None
            and age_days < minimum_age_days
        ):
            return False, (
                f"Resource is only {age_days:.2f} days old; "
                f"minimum age is {minimum_age_days:.2f} days."
            )

        return True, "Cleanup policy approved."

    def _validate_public_ip(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = self.network_client.public_ip_addresses.get(
            resource_group,
            resource_name,
        )

        if getattr(item, "ip_configuration", None):
            return False, (
                "Public IP became associated with an IP configuration."
            )

        if getattr(item, "nat_gateway", None):
            return False, (
                "Public IP became associated with a NAT gateway."
            )

        return True, "Public IP is still unassociated."

    def _validate_network_interface(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = self.network_client.network_interfaces.get(
            resource_group,
            resource_name,
        )

        if getattr(item, "virtual_machine", None):
            return False, (
                "Network interface became attached to a VM."
            )

        if getattr(item, "private_endpoint", None):
            return False, (
                "Network interface belongs to a private endpoint."
            )

        return True, (
            "Network interface is still unattached."
        )

    def _validate_disk(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = self.compute_client.disks.get(
            resource_group,
            resource_name,
        )

        if getattr(item, "managed_by", None):
            return False, (
                "Managed disk became attached to a resource."
            )

        managed_by_extended = getattr(
            item,
            "managed_by_extended",
            None,
        )

        if managed_by_extended:
            return False, (
                "Managed disk has extended resource attachments."
            )

        disk_state = normalize_text(
            getattr(item, "disk_state", "")
        )

        disk_state = disk_state.replace(
            "diskstate.",
            ""
        )

        if disk_state and disk_state != "unattached":
            return False, (
                f"Managed disk state is '{disk_state}', "
                "not 'unattached'."
            )

        return True, (
            "Managed disk is still unattached."
        )

    def _validate_network_security_group(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = (
            self.network_client
            .network_security_groups
            .get(
                resource_group,
                resource_name,
            )
        )

        if count_items(
            getattr(item, "network_interfaces", None)
        ) > 0:
            return False, (
                "NSG became associated with a network interface."
            )

        if count_items(
            getattr(item, "subnets", None)
        ) > 0:
            return False, (
                "NSG became associated with a subnet."
            )

        return True, (
            "Network security group is still unused."
        )

    def _validate_route_table(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = self.network_client.route_tables.get(
            resource_group,
            resource_name,
        )

        if count_items(
            getattr(item, "subnets", None)
        ) > 0:
            return False, (
                "Route table became associated with a subnet."
            )

        return True, "Route table is still unused."

    def _validate_load_balancer(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = self.network_client.load_balancers.get(
            resource_group,
            resource_name,
        )

        checks = {
            "backend address pools": getattr(
                item,
                "backend_address_pools",
                None,
            ),
            "load balancing rules": getattr(
                item,
                "load_balancing_rules",
                None,
            ),
            "inbound NAT rules": getattr(
                item,
                "inbound_nat_rules",
                None,
            ),
            "outbound rules": getattr(
                item,
                "outbound_rules",
                None,
            ),
        }

        for label, value in checks.items():
            if count_items(value) > 0:
                return False, (
                    f"Load balancer now contains {label}."
                )

        return True, "Load balancer is still empty."

    def _validate_application_gateway(
        self,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        item = (
            self.network_client
            .application_gateways
            .get(
                resource_group,
                resource_name,
            )
        )

        checks = {
            "HTTP listeners": getattr(
                item,
                "http_listeners",
                None,
            ),
            "routing rules": getattr(
                item,
                "request_routing_rules",
                None,
            ),
            "backend pools": getattr(
                item,
                "backend_address_pools",
                None,
            ),
            "redirect configurations": getattr(
                item,
                "redirect_configurations",
                None,
            ),
        }

        for label, value in checks.items():
            if count_items(value) > 0:
                return False, (
                    f"Application Gateway now contains {label}."
                )

        return True, (
            "Application Gateway is still empty."
        )

    def _live_validate(
        self,
        waste_type: str,
        resource_group: str,
        resource_name: str,
    ) -> tuple[bool, str]:
        validators: dict[
            str,
            Callable[[str, str], tuple[bool, str]],
        ] = {
            "UNASSOCIATED_PUBLIC_IP": (
                self._validate_public_ip
            ),
            "UNUSED_NETWORK_INTERFACE": (
                self._validate_network_interface
            ),
            "UNATTACHED_DISK": (
                self._validate_disk
            ),
            "UNUSED_NETWORK_SECURITY_GROUP": (
                self._validate_network_security_group
            ),
            "UNUSED_ROUTE_TABLE": (
                self._validate_route_table
            ),
            "EMPTY_LOAD_BALANCER": (
                self._validate_load_balancer
            ),
            "EMPTY_APPLICATION_GATEWAY": (
                self._validate_application_gateway
            ),
        }

        validator = validators.get(waste_type)

        if validator is None:
            return False, (
                "No live validator exists for this waste type."
            )

        return validator(
            resource_group,
            resource_name,
        )

    def _delete_resource(
        self,
        waste_type: str,
        resource_group: str,
        resource_name: str,
    ) -> None:
        if waste_type == "UNASSOCIATED_PUBLIC_IP":
            poller = (
                self.network_client
                .public_ip_addresses
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == "UNUSED_NETWORK_INTERFACE":
            poller = (
                self.network_client
                .network_interfaces
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == "UNATTACHED_DISK":
            poller = (
                self.compute_client
                .disks
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == (
            "UNUSED_NETWORK_SECURITY_GROUP"
        ):
            poller = (
                self.network_client
                .network_security_groups
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == "UNUSED_ROUTE_TABLE":
            poller = (
                self.network_client
                .route_tables
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == "EMPTY_LOAD_BALANCER":
            poller = (
                self.network_client
                .load_balancers
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        elif waste_type == (
            "EMPTY_APPLICATION_GATEWAY"
        ):
            poller = (
                self.network_client
                .application_gateways
                .begin_delete(
                    resource_group,
                    resource_name,
                )
            )

        else:
            raise ValueError(
                f"Unsupported waste type: {waste_type}"
            )

        poller.result()

    def execute(
        self,
        *,
        resources: list[dict[str, Any]],
        dry_run: bool,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        deletion_enabled = bool(
            self.policy.get(
                "actions",
                {},
            ).get(
                "delete_orphaned_resources",
                False,
            )
        )

        effective_dry_run = (
            bool(dry_run)
            or not deletion_enabled
        )

        for resource in resources:
            waste_type = str(
                resource.get("waste_type", "")
            ).strip().upper()

            resource_group = str(
                resource.get("resourceGroup", "")
            ).strip()

            resource_name = str(
                resource.get("name", "")
            ).strip()

            age_days = self._resource_age_days(
                resource
            )

            base_result = {
                "name": resource_name,
                "resource_group": resource_group,
                "resource_type": resource.get("type"),
                "waste_type": waste_type,
                "resource_age_days": (
                    round(age_days, 2)
                    if age_days is not None
                    else None
                ),
                "executed_at_utc": utc_now_iso(),
            }

            allowed, reason = self.is_cleanup_allowed(
                resource
            )

            if not allowed:
                results.append(
                    {
                        **base_result,
                        "status": "BLOCKED",
                        "message": reason,
                    }
                )
                continue

            if not resource_group or not resource_name:
                results.append(
                    {
                        **base_result,
                        "status": "FAILED",
                        "message": (
                            "Resource group or resource name "
                            "is missing."
                        ),
                    }
                )
                continue

            try:
                live_valid, live_reason = (
                    self._live_validate(
                        waste_type,
                        resource_group,
                        resource_name,
                    )
                )

                if not live_valid:
                    results.append(
                        {
                            **base_result,
                            "status": "BLOCKED",
                            "message": live_reason,
                        }
                    )
                    continue

                if effective_dry_run:
                    dry_run_reason = (
                        "Cleanup approved and live validation "
                        "passed, but dry-run prevented deletion."
                    )

                    if not deletion_enabled:
                        dry_run_reason = (
                            "Cleanup approved and live validation "
                            "passed, but delete_orphaned_resources "
                            "is disabled."
                        )

                    results.append(
                        {
                            **base_result,
                            "status": "SIMULATED",
                            "message": dry_run_reason,
                            "live_validation": live_reason,
                        }
                    )
                    continue

                logger.warning(
                    "Deleting unused Azure resource | "
                    "type=%s | resource_group=%s | name=%s",
                    waste_type,
                    resource_group,
                    resource_name,
                )

                self._delete_resource(
                    waste_type,
                    resource_group,
                    resource_name,
                )

                results.append(
                    {
                        **base_result,
                        "status": "EXECUTED",
                        "message": (
                            "Unused Azure resource was deleted "
                            "successfully."
                        ),
                        "live_validation": live_reason,
                    }
                )

            except ResourceNotFoundError:
                results.append(
                    {
                        **base_result,
                        "status": "NOT_FOUND",
                        "message": (
                            "Resource no longer exists in Azure."
                        ),
                    }
                )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid cleanup resource data."
                )

                results.append(
                    {
                        **base_result,
                        "status": "FAILED",
                        "message": (
                            f"Invalid cleanup data: {exc}"
                        ),
                    }
                )

            except AzureError as exc:
                logger.exception(
                    "Azure cleanup operation failed | "
                    "type=%s | resource_group=%s | name=%s",
                    waste_type,
                    resource_group,
                    resource_name,
                )

                results.append(
                    {
                        **base_result,
                        "status": "FAILED",
                        "message": (
                            f"Azure rejected cleanup: {exc}"
                        ),
                    }
                )

            except Exception as exc:
                logger.exception(
                    "Unexpected cleanup failure."
                )

                results.append(
                    {
                        **base_result,
                        "status": "FAILED",
                        "message": (
                            f"Unexpected cleanup failure: {exc}"
                        ),
                    }
                )

        executed_count = sum(
            item["status"] == "EXECUTED"
            for item in results
        )

        blocked_count = sum(
            item["status"] == "BLOCKED"
            for item in results
        )

        simulated_count = sum(
            item["status"] == "SIMULATED"
            for item in results
        )

        failed_count = sum(
            item["status"] == "FAILED"
            for item in results
        )

        not_found_count = sum(
            item["status"] == "NOT_FOUND"
            for item in results
        )

        if executed_count > 0:
            status = "EXECUTED"

        elif failed_count > 0:
            status = "PARTIAL_OR_COMPLETE_FAILURE"

        elif simulated_count > 0:
            status = "NO_CLEANUP_EXECUTED"

        elif blocked_count > 0:
            status = "BLOCKED"

        else:
            status = "NO_CLEANUP_REQUIRED"

        return {
            "status": status,
            "dry_run": effective_dry_run,
            "policy_dry_run": bool(dry_run),
            "deletion_enabled": deletion_enabled,
            "executed_count": executed_count,
            "blocked_count": blocked_count,
            "simulated_count": simulated_count,
            "failed_count": failed_count,
            "not_found_count": not_found_count,
            "results": results,
        }
