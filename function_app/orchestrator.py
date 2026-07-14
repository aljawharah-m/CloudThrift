"""
CloudThrift Orchestrator

Coordinates live Azure telemetry collection, infrastructure
decision-making, cost estimation, action execution, and audit logging.

Workflow:
1. Collect live Azure telemetry.
2. Convert telemetry into a CloudState.
3. Evaluate the state using the Decision Engine.
4. Estimate the financial impact.
5. Execute or simulate the infrastructure action.
6. Write a structured audit record.
"""

from __future__ import annotations

import json
import logging
from typing import Any

try:
    from .action_executor import ActionExecutor
    from .audit_logger import AuditLogger
    from .cost_estimator import CostEstimator
    from .decision_engine import CloudState, DecisionEngine
    from .telemetry_collector import (
        TelemetryCollector,
        TelemetrySnapshot,
    )
except ImportError:
    from action_executor import ActionExecutor
    from audit_logger import AuditLogger
    from cost_estimator import CostEstimator
    from decision_engine import CloudState, DecisionEngine
    from telemetry_collector import (
        TelemetryCollector,
        TelemetrySnapshot,
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
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

    Duration values default to zero because a single telemetry snapshot
    does not prove that a condition has been sustained over time.
    """

    return CloudState(
        cpu_percent=telemetry.cpu_percent,
        network_mbps=telemetry.network_mbps,
        requests_per_minute=telemetry.requests_per_minute,
        current_instances=telemetry.current_instances,
        budget_used_percent=telemetry.budget_used_percent,
        environment=telemetry.environment,
        cpu_high_duration_minutes=cpu_high_duration_minutes,
        network_high_duration_minutes=network_high_duration_minutes,
        requests_high_duration_minutes=requests_high_duration_minutes,
        cpu_low_duration_minutes=cpu_low_duration_minutes,
        network_low_duration_minutes=network_low_duration_minutes,
        requests_low_duration_minutes=requests_low_duration_minutes,
        minutes_since_last_scale_out=minutes_since_last_scale_out,
        minutes_since_last_scale_in=minutes_since_last_scale_in,
        scaling_actions_last_hour=scaling_actions_last_hour,
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
        self.action_executor = ActionExecutor()
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

        telemetry = (
            self.telemetry_collector.collect_azure_snapshot(
                requests_per_minute=requests_per_minute,
                budget_used_percent=budget_used_percent,
            )
        )

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

        decision = self.decision_engine.decide(
            cloud_state
        )

        cost_estimate = self.cost_estimator.estimate(
            current_instances=decision.current_instances,
            target_instances=decision.target_instances,
        )

        execution_result = self.action_executor.execute(
            action=decision.action.value,
            current_instances=decision.current_instances,
            target_instances=decision.target_instances,
            dry_run=decision.dry_run,
        )

        audit_record = self.audit_logger.write_record(
            event_type="SCALING_DECISION",
            telemetry=telemetry,
            decision=decision,
            execution_result={
                "cost_estimate": cost_estimate.to_dict(),
                "action_execution": (
                    execution_result.to_dict()
                ),
            },
            metadata={
                "environment": self.environment,
                "orchestrator": (
                    "CloudThriftOrchestrator"
                ),
                "telemetry_source": telemetry.source,
            },
        )

        result: dict[str, Any] = {
            "telemetry": telemetry.to_dict(),
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
            "cost_estimate": cost_estimate.to_dict(),
            "execution_result": (
                execution_result.to_dict()
            ),
            "audit": {
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
            "action=%s | execution_status=%s",
            decision.action.value,
            execution_result.status.value,
        )

        return result


def run_demo() -> None:
    orchestrator = CloudThriftOrchestrator(
        environment="development",
    )

    result = orchestrator.run_cycle(
        requests_per_minute=1500,
        cpu_high_duration_minutes=5,
        requests_high_duration_minutes=5,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    run_demo()