"""
CloudThrift Decision Engine

A policy-driven decision engine for autonomous Azure infrastructure
scaling and FinOps-aware workload management.

This module:
- Loads scaling policies from JSON.
- Evaluates CPU, network, and request-volume signals.
- Applies sustained-duration requirements.
- Enforces cooldown and stability controls.
- Applies FinOps budget guardrails.
- Protects production environments.
- Supports dry-run execution.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = PROJECT_ROOT / "policies" / "scaling_policy.json"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cloudthrift.decision_engine")


class Action(str, Enum):
    SCALE_OUT = "SCALE_OUT"
    SCALE_IN = "SCALE_IN"
    NO_ACTION = "NO_ACTION"
    BLOCKED_BY_BUDGET = "BLOCKED_BY_BUDGET"
    BLOCKED_BY_COOLDOWN = "BLOCKED_BY_COOLDOWN"
    BLOCKED_BY_PROTECTION = "BLOCKED_BY_PROTECTION"
    POLICY_DISABLED = "POLICY_DISABLED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class CloudState:
    cpu_percent: float
    network_mbps: float
    requests_per_minute: int
    current_instances: int

    budget_used_percent: float = 0.0
    environment: str = "development"

    cpu_high_duration_minutes: int = 0
    network_high_duration_minutes: int = 0
    requests_high_duration_minutes: int = 0

    cpu_low_duration_minutes: int = 0
    network_low_duration_minutes: int = 0
    requests_low_duration_minutes: int = 0

    minutes_since_last_scale_out: int = 9999
    minutes_since_last_scale_in: int = 9999
    scaling_actions_last_hour: int = 0


@dataclass(frozen=True)
class Decision:
    action: Action
    current_instances: int
    target_instances: int
    reason: str
    triggered_signals: tuple[str, ...]
    blocked_signals: tuple[str, ...]
    dry_run: bool
    confidence_score: int
    timestamp_utc: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["action"] = self.action.value
        result["triggered_signals"] = list(self.triggered_signals)
        result["blocked_signals"] = list(self.blocked_signals)
        return result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy(
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    if not policy_path.exists():
        raise FileNotFoundError(
            f"Policy file not found: {policy_path}"
        )

    try:
        with policy_path.open("r", encoding="utf-8") as file:
            policy = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in policy file: {error}"
        ) from error

    validate_policy(policy)

    logger.info(
        "Policy loaded successfully: %s",
        policy.get("policy_name", "Unnamed Policy"),
    )

    return policy


def validate_policy(policy: dict[str, Any]) -> None:
    required_sections = {
        "policy_name",
        "enabled",
        "instance_limits",
        "scale_out",
        "scale_in",
        "stability_controls",
        "cost_guardrails",
        "safety",
    }

    missing_sections = required_sections - policy.keys()

    if missing_sections:
        raise ValueError(
            "Missing required policy sections: "
            + ", ".join(sorted(missing_sections))
        )

    limits = policy["instance_limits"]
    minimum = limits["minimum"]
    normal_maximum = limits["normal_maximum"]
    emergency_maximum = limits["emergency_maximum"]

    if minimum < 1:
        raise ValueError(
            "Minimum instance count must be at least 1."
        )

    if normal_maximum < minimum:
        raise ValueError(
            "Normal maximum cannot be lower than the minimum."
        )

    if emergency_maximum < normal_maximum:
        raise ValueError(
            "Emergency maximum cannot be lower than the normal maximum."
        )

    for section_name in ("scale_out", "scale_in"):
        required_signals = policy[section_name]["required_signals"]

        if required_signals not in {1, 2, 3}:
            raise ValueError(
                f"{section_name}.required_signals must be between 1 and 3."
            )


def validate_state(state: CloudState) -> list[str]:
    errors: list[str] = []

    if not 0 <= state.cpu_percent <= 100:
        errors.append(
            "CPU percentage must be between 0 and 100."
        )

    if state.network_mbps < 0:
        errors.append(
            "Network throughput cannot be negative."
        )

    if state.requests_per_minute < 0:
        errors.append(
            "Requests per minute cannot be negative."
        )

    if state.current_instances < 0:
        errors.append(
            "Current instance count cannot be negative."
        )

    if state.budget_used_percent < 0:
        errors.append(
            "Budget usage percentage cannot be negative."
        )

    if state.scaling_actions_last_hour < 0:
        errors.append(
            "Scaling action count cannot be negative."
        )

    duration_values = (
        state.cpu_high_duration_minutes,
        state.network_high_duration_minutes,
        state.requests_high_duration_minutes,
        state.cpu_low_duration_minutes,
        state.network_low_duration_minutes,
        state.requests_low_duration_minutes,
        state.minutes_since_last_scale_out,
        state.minutes_since_last_scale_in,
    )

    if any(value < 0 for value in duration_values):
        errors.append(
            "Duration values cannot be negative."
        )

    return errors


def calculate_confidence_score(
    detected_signals: int,
    required_signals: int,
) -> int:
    if required_signals <= 0:
        return 0

    return min(
        int((detected_signals / required_signals) * 100),
        100,
    )


def create_decision(
    *,
    action: Action,
    state: CloudState,
    target_instances: int,
    reason: str,
    dry_run: bool,
    triggered_signals: list[str] | None = None,
    blocked_signals: list[str] | None = None,
    confidence_score: int = 0,
) -> Decision:
    return Decision(
        action=action,
        current_instances=state.current_instances,
        target_instances=target_instances,
        reason=reason,
        triggered_signals=tuple(triggered_signals or []),
        blocked_signals=tuple(blocked_signals or []),
        dry_run=dry_run,
        confidence_score=confidence_score,
        timestamp_utc=utc_now_iso(),
    )


def evaluate_scale_out_signals(
    state: CloudState,
    policy: dict[str, Any],
) -> list[str]:
    rules = policy["scale_out"]
    evaluation_period = rules["evaluation_period_minutes"]

    signals: list[str] = []

    if (
        state.cpu_percent >= rules["cpu_threshold_percent"]
        and state.cpu_high_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"CPU_HIGH:{state.cpu_percent:.1f}%"
        )

    if (
        state.network_mbps >= rules["network_threshold_mbps"]
        and state.network_high_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"NETWORK_HIGH:{state.network_mbps:.1f}Mbps"
        )

    if (
        state.requests_per_minute
        >= rules["request_threshold_per_minute"]
        and state.requests_high_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"REQUESTS_HIGH:{state.requests_per_minute}/min"
        )

    return signals


def evaluate_scale_in_signals(
    state: CloudState,
    policy: dict[str, Any],
) -> list[str]:
    rules = policy["scale_in"]
    evaluation_period = rules["evaluation_period_minutes"]

    signals: list[str] = []

    if (
        state.cpu_percent <= rules["cpu_threshold_percent"]
        and state.cpu_low_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"CPU_LOW:{state.cpu_percent:.1f}%"
        )

    if (
        state.network_mbps <= rules["network_threshold_mbps"]
        and state.network_low_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"NETWORK_LOW:{state.network_mbps:.1f}Mbps"
        )

    if (
        state.requests_per_minute
        <= rules["request_threshold_per_minute"]
        and state.requests_low_duration_minutes >= evaluation_period
    ):
        signals.append(
            f"REQUESTS_LOW:{state.requests_per_minute}/min"
        )

    return signals


class DecisionEngine:
    def __init__(
        self,
        policy_path: Path = DEFAULT_POLICY_PATH,
    ) -> None:
        self.policy = load_policy(policy_path)

    def decide(self, state: CloudState) -> Decision:
        logger.info(
            (
                "Evaluating workload state | CPU=%.1f%% | "
                "Network=%.1f Mbps | Requests=%d/min | "
                "Instances=%d | Budget=%.1f%%"
            ),
            state.cpu_percent,
            state.network_mbps,
            state.requests_per_minute,
            state.current_instances,
            state.budget_used_percent,
        )

        policy = self.policy
        dry_run = policy["safety"]["dry_run_mode"]

        state_errors = validate_state(state)

        if state_errors:
            return create_decision(
                action=Action.INVALID_STATE,
                state=state,
                target_instances=state.current_instances,
                reason="The received infrastructure state is invalid.",
                dry_run=dry_run,
                blocked_signals=state_errors,
            )

        if not policy["enabled"]:
            return create_decision(
                action=Action.POLICY_DISABLED,
                state=state,
                target_instances=state.current_instances,
                reason="The CloudThrift scaling policy is disabled.",
                dry_run=dry_run,
            )

        limits = policy["instance_limits"]
        scale_out_rules = policy["scale_out"]
        scale_in_rules = policy["scale_in"]
        stability = policy["stability_controls"]
        cost_rules = policy["cost_guardrails"]
        safety = policy["safety"]

        minimum_instances = limits["minimum"]
        normal_maximum = limits["normal_maximum"]
        emergency_maximum = limits["emergency_maximum"]

        production_protected = (
            safety["protect_production"]
            and state.environment.lower() == "production"
        )

        if (
            state.scaling_actions_last_hour
            >= stability["maximum_actions_per_hour"]
        ):
            return create_decision(
                action=Action.BLOCKED_BY_COOLDOWN,
                state=state,
                target_instances=state.current_instances,
                reason=(
                    "The hourly scaling-action limit has been reached. "
                    "Further actions are temporarily blocked to preserve stability."
                ),
                dry_run=dry_run,
                blocked_signals=[
                    "MAXIMUM_ACTIONS_PER_HOUR_REACHED"
                ],
            )

        scale_out_signals = evaluate_scale_out_signals(
            state,
            policy,
        )

        scale_in_signals = evaluate_scale_in_signals(
            state,
            policy,
        )

        required_scale_out_signals = (
            scale_out_rules["required_signals"]
        )

        required_scale_in_signals = (
            scale_in_rules["required_signals"]
        )

        scale_out_confidence = calculate_confidence_score(
            len(scale_out_signals),
            required_scale_out_signals,
        )

        scale_in_confidence = calculate_confidence_score(
            len(scale_in_signals),
            required_scale_in_signals,
        )

        allowed_maximum = normal_maximum
        emergency_scaling = False

        budget_block_threshold = cost_rules[
            "block_normal_scaling_above_budget_percent"
        ]

        emergency_budget_limit = cost_rules[
            "emergency_scaling_budget_limit_percent"
        ]

        if state.budget_used_percent >= budget_block_threshold:
            allowed_maximum = state.current_instances

        if (
            cost_rules["allow_emergency_scaling"]
            and state.budget_used_percent < emergency_budget_limit
            and len(scale_out_signals) == 3
        ):
            allowed_maximum = emergency_maximum
            emergency_scaling = True

        if len(scale_out_signals) >= required_scale_out_signals:
            if (
                state.minutes_since_last_scale_out
                < stability["scale_out_cooldown_minutes"]
            ):
                return create_decision(
                    action=Action.BLOCKED_BY_COOLDOWN,
                    state=state,
                    target_instances=state.current_instances,
                    reason=(
                        "Scale-out conditions were detected, but the "
                        "scale-out cooldown period is still active."
                    ),
                    dry_run=dry_run,
                    triggered_signals=scale_out_signals,
                    blocked_signals=[
                        "SCALE_OUT_COOLDOWN_ACTIVE"
                    ],
                    confidence_score=scale_out_confidence,
                )

            if state.current_instances >= allowed_maximum:
                if state.budget_used_percent >= budget_block_threshold:
                    return create_decision(
                        action=Action.BLOCKED_BY_BUDGET,
                        state=state,
                        target_instances=state.current_instances,
                        reason=(
                            "Sustained workload pressure was detected, "
                            "but normal scaling is blocked by active "
                            "FinOps budget guardrails."
                        ),
                        dry_run=dry_run,
                        triggered_signals=scale_out_signals,
                        blocked_signals=[
                            "BUDGET_GUARDRAIL_ACTIVE"
                        ],
                        confidence_score=scale_out_confidence,
                    )

                return create_decision(
                    action=Action.NO_ACTION,
                    state=state,
                    target_instances=state.current_instances,
                    reason=(
                        "The workload requires additional capacity, "
                        "but the permitted maximum instance count "
                        "has already been reached."
                    ),
                    dry_run=dry_run,
                    triggered_signals=scale_out_signals,
                    blocked_signals=[
                        "MAXIMUM_CAPACITY_REACHED"
                    ],
                    confidence_score=scale_out_confidence,
                )

            target_instances = min(
                state.current_instances
                + scale_out_rules["increase_by"],
                allowed_maximum,
            )

            scaling_mode = (
                "emergency"
                if emergency_scaling
                else "normal"
            )

            return create_decision(
                action=Action.SCALE_OUT,
                state=state,
                target_instances=target_instances,
                reason=(
                    f"Sustained workload pressure was detected using "
                    f"{len(scale_out_signals)} independent signals. "
                    f"A {scaling_mode} scale-out from "
                    f"{state.current_instances} to "
                    f"{target_instances} instances is recommended."
                ),
                dry_run=dry_run,
                triggered_signals=scale_out_signals,
                confidence_score=scale_out_confidence,
            )

        if len(scale_in_signals) >= required_scale_in_signals:
            if state.current_instances <= minimum_instances:
                return create_decision(
                    action=Action.NO_ACTION,
                    state=state,
                    target_instances=state.current_instances,
                    reason=(
                        "Low utilization was detected, but the "
                        "infrastructure is already operating at the "
                        "minimum safe instance count."
                    ),
                    dry_run=dry_run,
                    triggered_signals=scale_in_signals,
                    blocked_signals=[
                        "MINIMUM_CAPACITY_REACHED"
                    ],
                    confidence_score=scale_in_confidence,
                )

            if production_protected:
                return create_decision(
                    action=Action.BLOCKED_BY_PROTECTION,
                    state=state,
                    target_instances=state.current_instances,
                    reason=(
                        "Scale-in conditions were detected, but automatic "
                        "scale-in is blocked because production protection "
                        "is enabled."
                    ),
                    dry_run=dry_run,
                    triggered_signals=scale_in_signals,
                    blocked_signals=[
                        "PRODUCTION_PROTECTION_ACTIVE"
                    ],
                    confidence_score=scale_in_confidence,
                )

            if (
                state.minutes_since_last_scale_in
                < stability["scale_in_cooldown_minutes"]
            ):
                return create_decision(
                    action=Action.BLOCKED_BY_COOLDOWN,
                    state=state,
                    target_instances=state.current_instances,
                    reason=(
                        "Scale-in conditions were detected, but the "
                        "scale-in cooldown period is still active."
                    ),
                    dry_run=dry_run,
                    triggered_signals=scale_in_signals,
                    blocked_signals=[
                        "SCALE_IN_COOLDOWN_ACTIVE"
                    ],
                    confidence_score=scale_in_confidence,
                )

            target_instances = max(
                state.current_instances
                - scale_in_rules["decrease_by"],
                minimum_instances,
            )

            return create_decision(
                action=Action.SCALE_IN,
                state=state,
                target_instances=target_instances,
                reason=(
                    f"Sustained low utilization was detected using "
                    f"{len(scale_in_signals)} independent signals. "
                    f"Scaling from {state.current_instances} to "
                    f"{target_instances} instances would reduce cost "
                    "while preserving minimum capacity."
                ),
                dry_run=dry_run,
                triggered_signals=scale_in_signals,
                confidence_score=scale_in_confidence,
            )

        return create_decision(
            action=Action.NO_ACTION,
            state=state,
            target_instances=state.current_instances,
            reason=(
                "The current workload does not satisfy enough sustained "
                "signals for a safe scaling action."
            ),
            dry_run=dry_run,
            triggered_signals=(
                scale_out_signals + scale_in_signals
            ),
            confidence_score=max(
                scale_out_confidence,
                scale_in_confidence,
            ),
        )


def run_demo() -> None:
    engine = DecisionEngine()

    demo_state = CloudState(
        cpu_percent=84.5,
        network_mbps=96.0,
        requests_per_minute=1450,
        current_instances=1,
        budget_used_percent=42.0,
        environment="development",
        cpu_high_duration_minutes=7,
        network_high_duration_minutes=7,
        requests_high_duration_minutes=7,
        cpu_low_duration_minutes=0,
        network_low_duration_minutes=0,
        requests_low_duration_minutes=0,
        minutes_since_last_scale_out=30,
        minutes_since_last_scale_in=30,
        scaling_actions_last_hour=0,
    )

    decision = engine.decide(demo_state)

    print(json.dumps(
        decision.to_dict(),
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    run_demo()