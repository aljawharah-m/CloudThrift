"""
CloudThrift Orchestrator

Coordinates live Azure telemetry collection, infrastructure decisions,
persistent FinOps analysis, cost estimation, scaling execution,
orphaned-resource detection, safe cleanup execution, and structured
audit logging.

Workflow:
1. Collect live Azure telemetry.
2. Run persistent FinOps utilization assessment.
3. Convert telemetry into a CloudState.
4. Evaluate operational scaling requirements.
5. Apply FinOps optimization when safe.
6. Estimate the financial impact.
7. Execute or simulate the selected scaling action.
8. Detect orphaned and unused Azure resources.
9. Execute or simulate policy-controlled cleanup.
10. Write a structured audit record.
"""

from __future__ import annotations

import json
import logging
from typing import Any

try:
    from .action_executor import ActionExecutor
    from .audit_logger import AuditLogger
    from .cleanup_executor import CleanupExecutor
    from .cost_estimator import CostEstimator
    from .decision_engine import CloudState, DecisionEngine
    from .finops_optimizer import FinOpsOptimizer
    from .resource_optimizer import ResourceOptimizer
    from .telemetry_collector import (
        TelemetryCollector,
        TelemetrySnapshot,
    )
except ImportError:
    from action_executor import ActionExecutor
    from audit_logger import AuditLogger
    from cleanup_executor import CleanupExecutor
    from cost_estimator import CostEstimator
    from decision_engine import CloudState, DecisionEngine
    from finops_optimizer import FinOpsOptimizer
    from resource_optimizer import ResourceOptimizer
    from telemetry_collector import (
        TelemetryCollector,
        TelemetrySnapshot,
    )


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger("cloudthrift.orchestrator")


def build_cloud_state(
    telemetry: TelemetrySnapshot,
    *,
    cpu_high_duration_minutes: int = 0,
    network_high_duration_minutes: int = 0,
    requests_high_duration_minutes: int = 0,
    cpu_low_duration_minutes: int = 0,
    network_low_duration_minutes: int = 0,
    requests_low_duration_minutes: int = 0,
    minutes_since_last_scale_out: int = 9999,
    minutes_since_last_scale_in: int = 9999,
    scaling_actions_last_hour: int = 0,
) -> CloudState:
    """
    Convert a telemetry snapshot into a Decision Engine CloudState.

    Duration values default to zero because one telemetry snapshot does
    not prove that a workload condition was sustained over time.
    """

    return CloudState(
        cpu_percent=telemetry.cpu_percent,
        network_mbps=telemetry.network_mbps,
        requests_per_minute=telemetry.requests_per_minute,
        current_instances=telemetry.current_instances,
        budget_used_percent=telemetry.budget_used_percent,
        environment=telemetry.environment,
        cpu_high_duration_minutes=cpu_high_duration_minutes,
        network_high_duration_minutes=(
            network_high_duration_minutes
        ),
        requests_high_duration_minutes=(
            requests_high_duration_minutes
        ),
        cpu_low_duration_minutes=cpu_low_duration_minutes,
        network_low_duration_minutes=(
            network_low_duration_minutes
        ),
        requests_low_duration_minutes=(
            requests_low_duration_minutes
        ),
        minutes_since_last_scale_out=(
            minutes_since_last_scale_out
        ),
        minutes_since_last_scale_in=(
            minutes_since_last_scale_in
        ),
        scaling_actions_last_hour=(
            scaling_actions_last_hour
        ),
    )


class CloudThriftOrchestrator:
    def __init__(
        self,
        *,
        environment: str = "development",
    ) -> None:
        self.environment = environment

        self.telemetry_collector = TelemetryCollector(
            environment=environment,
        )

        self.decision_engine = DecisionEngine()
        self.cost_estimator = CostEstimator()

        self.finops_optimizer = FinOpsOptimizer(
            environment=environment,
        )

        self.action_executor = ActionExecutor()

        self.resource_optimizer = ResourceOptimizer()
        self.cleanup_executor = CleanupExecutor()

        self.audit_logger = AuditLogger()

    def run_cycle(
        self,
        *,
        requests_per_minute: int | None = None,
        budget_used_percent: float | None = None,
        cpu_high_duration_minutes: int = 0,
        network_high_duration_minutes: int = 0,
        requests_high_duration_minutes: int = 0,
        cpu_low_duration_minutes: int = 0,
        network_low_duration_minutes: int = 0,
        requests_low_duration_minutes: int = 0,
        minutes_since_last_scale_out: int = 9999,
        minutes_since_last_scale_in: int = 9999,
        scaling_actions_last_hour: int = 0,
    ) -> dict[str, Any]:
        logger.info(
            "Starting CloudThrift orchestration cycle | "
            "environment=%s",
            self.environment,
        )

        # ---------------------------------------------------------
        # 1. Collect live Azure telemetry
        # ---------------------------------------------------------

        telemetry = (
            self.telemetry_collector.collect_azure_snapshot(
                requests_per_minute=requests_per_minute,
                budget_used_percent=budget_used_percent,
            )
        )

        # ---------------------------------------------------------
        # 2. Run persistent FinOps assessment
        # ---------------------------------------------------------

        finops_assessment = self.finops_optimizer.assess(
            cpu_percent=telemetry.cpu_percent,
            current_instances=telemetry.current_instances,
        )

        logger.info(
            "FinOps assessment completed | "
            "status=%s | average_cpu=%.2f | "
            "observed_minutes=%.2f | samples=%s | "
            "current_capacity=%s | optimized_capacity=%s",
            finops_assessment.status.value,
            finops_assessment.average_cpu_percent,
            finops_assessment.observed_duration_minutes,
            finops_assessment.sample_count,
            finops_assessment.previous_capacity,
            finops_assessment.optimized_capacity,
        )

        # ---------------------------------------------------------
        # 3. Build operational cloud state
        # ---------------------------------------------------------

        cloud_state = build_cloud_state(
            telemetry,
            cpu_high_duration_minutes=(
                cpu_high_duration_minutes
            ),
            network_high_duration_minutes=(
                network_high_duration_minutes
            ),
            requests_high_duration_minutes=(
                requests_high_duration_minutes
            ),
            cpu_low_duration_minutes=(
                cpu_low_duration_minutes
            ),
            network_low_duration_minutes=(
                network_low_duration_minutes
            ),
            requests_low_duration_minutes=(
                requests_low_duration_minutes
            ),
            minutes_since_last_scale_out=(
                minutes_since_last_scale_out
            ),
            minutes_since_last_scale_in=(
                minutes_since_last_scale_in
            ),
            scaling_actions_last_hour=(
                scaling_actions_last_hour
            ),
        )

        # ---------------------------------------------------------
        # 4. Get the normal operational scaling decision
        # ---------------------------------------------------------

        decision = self.decision_engine.decide(
            cloud_state
        )

        operational_action = decision.action.value

        selected_action = operational_action
        selected_current_instances = (
            decision.current_instances
        )
        selected_target_instances = (
            decision.target_instances
        )
        selected_dry_run = decision.dry_run

        action_source = "DECISION_ENGINE"
        finops_optimization_applied = False

        # ---------------------------------------------------------
        # 5. Apply FinOps optimization safely
        # ---------------------------------------------------------
        #
        # Availability has priority over cost optimization.
        # FinOps must never override an operational SCALE_OUT.
        # ---------------------------------------------------------

        if (
            finops_assessment.status.value == "ELIGIBLE"
            and operational_action != "SCALE_OUT"
            and (
                finops_assessment.optimized_capacity
                < telemetry.current_instances
            )
        ):
            selected_action = "SCALE_IN"

            selected_current_instances = (
                telemetry.current_instances
            )

            selected_target_instances = (
                finops_assessment.optimized_capacity
            )

            action_source = "FINOPS_OPTIMIZER"
            finops_optimization_applied = True

            logger.warning(
                "FinOps optimization selected | "
                "resource=%s | capacity=%s->%s | "
                "average_cpu=%.2f | "
                "observed_minutes=%.2f | "
                "estimated_monthly_savings=%.2f",
                finops_assessment.resource,
                selected_current_instances,
                selected_target_instances,
                finops_assessment.average_cpu_percent,
                finops_assessment.observed_duration_minutes,
                finops_assessment.estimated_monthly_savings,
            )

        elif (
            finops_assessment.status.value == "ELIGIBLE"
            and operational_action == "SCALE_OUT"
        ):
            logger.warning(
                "FinOps optimization deferred because the "
                "Decision Engine requested SCALE_OUT."
            )

        # ---------------------------------------------------------
        # 6. Estimate cost using the selected scaling action
        # ---------------------------------------------------------

        cost_estimate = self.cost_estimator.estimate(
            current_instances=selected_current_instances,
            target_instances=selected_target_instances,
        )

        # ---------------------------------------------------------
        # 7. Execute or simulate the selected scaling action
        # ---------------------------------------------------------

        execution_result = self.action_executor.execute(
            action=selected_action,
            current_instances=selected_current_instances,
            target_instances=selected_target_instances,
            dry_run=selected_dry_run,
        )

        execution_status = (
            execution_result.status.value
        )

        if (
            finops_optimization_applied
            and execution_status == "EXECUTED"
        ):
            self.finops_optimizer.clear_observation_state()

            logger.info(
                "FinOps observation state cleared after "
                "successful capacity optimization."
            )

        # ---------------------------------------------------------
        # 8. Detect orphaned and unused Azure resources
        # ---------------------------------------------------------

        try:
            resource_assessment = (
                self.resource_optimizer.assess()
            )

        except Exception as exc:
            logger.exception(
                "Azure resource waste assessment failed."
            )

            resource_assessment = {
                "status": "ASSESSMENT_FAILED",
                "dry_run": True,
                "resource_count": 0,
                "resources": [],
                "error": str(exc),
            }

        logger.info(
            "Resource waste assessment completed | "
            "status=%s | detected=%s | dry_run=%s",
            resource_assessment.get(
                "status",
                "UNKNOWN",
            ),
            resource_assessment.get(
                "resource_count",
                0,
            ),
            resource_assessment.get(
                "dry_run",
                True,
            ),
        )

        # ---------------------------------------------------------
        # 9. Execute or simulate safe resource cleanup
        # ---------------------------------------------------------

        try:
            cleanup_result = self.cleanup_executor.execute(
                resources=resource_assessment.get(
                    "resources",
                    [],
                ),
                dry_run=resource_assessment.get(
                    "dry_run",
                    True,
                ),
            )

        except Exception as exc:
            logger.exception(
                "Azure resource cleanup cycle failed."
            )

            cleanup_result = {
                "status": "FAILED",
                "dry_run": resource_assessment.get(
                    "dry_run",
                    True,
                ),
                "executed_count": 0,
                "blocked_count": 0,
                "simulated_count": 0,
                "failed_count": 1,
                "results": [],
                "error": str(exc),
            }

        cleanup_executed_count = int(
            cleanup_result.get(
                "executed_count",
                0,
            )
        )

        cleanup_blocked_count = int(
            cleanup_result.get(
                "blocked_count",
                0,
            )
        )

        cleanup_simulated_count = int(
            cleanup_result.get(
                "simulated_count",
                0,
            )
        )

        cleanup_failed_count = int(
            cleanup_result.get(
                "failed_count",
                0,
            )
        )

        resource_cleanup_applied = (
            cleanup_executed_count > 0
        )

        logger.warning(
            "Resource cleanup cycle completed | "
            "detected=%s | executed=%s | "
            "simulated=%s | blocked=%s | "
            "failed=%s | dry_run=%s",
            resource_assessment.get(
                "resource_count",
                0,
            ),
            cleanup_executed_count,
            cleanup_simulated_count,
            cleanup_blocked_count,
            cleanup_failed_count,
            cleanup_result.get(
                "dry_run",
                True,
            ),
        )

        # ---------------------------------------------------------
        # 10. Select the audit event type
        # ---------------------------------------------------------

        if resource_cleanup_applied:
            event_type = "RESOURCE_CLEANUP"

        elif cleanup_simulated_count > 0:
            event_type = "RESOURCE_CLEANUP_SIMULATION"

        elif finops_optimization_applied:
            event_type = "FINOPS_OPTIMIZATION"

        else:
            event_type = "SCALING_DECISION"

        # ---------------------------------------------------------
        # 11. Write a structured audit record
        # ---------------------------------------------------------

        audit_record = self.audit_logger.write_record(
            event_type=event_type,
            telemetry=telemetry,
            decision=decision,
            execution_result={
                "selected_action": {
                    "source": action_source,
                    "action": selected_action,
                    "current_instances": (
                        selected_current_instances
                    ),
                    "target_instances": (
                        selected_target_instances
                    ),
                    "dry_run": selected_dry_run,
                },
                "finops_assessment": (
                    finops_assessment.to_dict()
                ),
                "cost_estimate": (
                    cost_estimate.to_dict()
                ),
                "action_execution": (
                    execution_result.to_dict()
                ),
                "resource_assessment": (
                    resource_assessment
                ),
                "resource_cleanup": (
                    cleanup_result
                ),
            },
            metadata={
                "environment": self.environment,
                "orchestrator": (
                    "CloudThriftOrchestrator"
                ),
                "telemetry_source": telemetry.source,
                "action_source": action_source,
                "finops_optimization_applied": (
                    finops_optimization_applied
                ),
                "resource_cleanup_applied": (
                    resource_cleanup_applied
                ),
                "resource_cleanup_dry_run": (
                    cleanup_result.get(
                        "dry_run",
                        True,
                    )
                ),
                "orphaned_resources_detected": (
                    resource_assessment.get(
                        "resource_count",
                        0,
                    )
                ),
            },
        )

        # ---------------------------------------------------------
        # 12. Build the final orchestration result
        # ---------------------------------------------------------

        result: dict[str, Any] = {
            "telemetry": telemetry.to_dict(),
            "finops_assessment": (
                finops_assessment.to_dict()
            ),
            "cloud_state": {
                "cpu_high_duration_minutes": (
                    cloud_state.cpu_high_duration_minutes
                ),
                "network_high_duration_minutes": (
                    cloud_state.network_high_duration_minutes
                ),
                "requests_high_duration_minutes": (
                    cloud_state.requests_high_duration_minutes
                ),
                "cpu_low_duration_minutes": (
                    cloud_state.cpu_low_duration_minutes
                ),
                "network_low_duration_minutes": (
                    cloud_state.network_low_duration_minutes
                ),
                "requests_low_duration_minutes": (
                    cloud_state.requests_low_duration_minutes
                ),
                "minutes_since_last_scale_out": (
                    cloud_state.minutes_since_last_scale_out
                ),
                "minutes_since_last_scale_in": (
                    cloud_state.minutes_since_last_scale_in
                ),
                "scaling_actions_last_hour": (
                    cloud_state.scaling_actions_last_hour
                ),
            },
            "decision": decision.to_dict(),
            "selected_action": {
                "source": action_source,
                "action": selected_action,
                "current_instances": (
                    selected_current_instances
                ),
                "target_instances": (
                    selected_target_instances
                ),
                "dry_run": selected_dry_run,
                "finops_optimization_applied": (
                    finops_optimization_applied
                ),
            },
            "cost_estimate": (
                cost_estimate.to_dict()
            ),
            "execution_result": (
                execution_result.to_dict()
            ),
            "resource_assessment": (
                resource_assessment
            ),
            "resource_cleanup": (
                cleanup_result
            ),
            "autonomous_cycle_summary": {
                "scaling_action": selected_action,
                "scaling_execution_status": (
                    execution_status
                ),
                "orphaned_resources_detected": (
                    resource_assessment.get(
                        "resource_count",
                        0,
                    )
                ),
                "cleanup_status": (
                    cleanup_result.get(
                        "status",
                        "UNKNOWN",
                    )
                ),
                "cleanup_executed_count": (
                    cleanup_executed_count
                ),
                "cleanup_simulated_count": (
                    cleanup_simulated_count
                ),
                "cleanup_blocked_count": (
                    cleanup_blocked_count
                ),
                "cleanup_failed_count": (
                    cleanup_failed_count
                ),
            },
            "audit": {
                "event_type": event_type,
                "audit_id": audit_record["audit_id"],
                "timestamp_utc": (
                    audit_record["timestamp_utc"]
                ),
                "file": str(
                    self.audit_logger.audit_file
                ),
            },
        }

        logger.info(
            "CloudThrift orchestration cycle completed | "
            "action_source=%s | action=%s | "
            "scaling_status=%s | "
            "resource_assessment=%s | "
            "cleanup_status=%s",
            action_source,
            selected_action,
            execution_status,
            resource_assessment.get(
                "status",
                "UNKNOWN",
            ),
            cleanup_result.get(
                "status",
                "UNKNOWN",
            ),
        )

        return result


def run_demo() -> None:
    orchestrator = CloudThriftOrchestrator(
        environment="development",
    )

    result = orchestrator.run_cycle()

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    run_demo()