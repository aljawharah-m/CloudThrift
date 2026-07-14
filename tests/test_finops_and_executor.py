import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FUNCTION_APP = PROJECT_ROOT / "function_app"

sys.path.append(str(FUNCTION_APP))

from action_executor import ActionExecutor
from cost_estimator import CostEstimator


def test_cost_estimator_uses_sar():
    estimator = CostEstimator(
        instance_hourly_price=0.36,
        currency="SAR",
    )

    estimate = estimator.estimate(
        current_instances=1,
        target_instances=2,
    )

    assert estimate.current_hourly_cost == 0.36
    assert estimate.target_hourly_cost == 0.72
    assert estimate.hourly_cost_change == 0.36
    assert estimate.estimated_monthly_cost_change == 259.2
    assert estimate.currency == "SAR"


def test_action_executor_simulates_dry_run():
    executor = ActionExecutor()

    result = executor.execute(
        action="SCALE_OUT",
        current_instances=1,
        target_instances=2,
        dry_run=True,
    )

    assert result.status.value == "SIMULATED"
    assert result.action == "SCALE_OUT"
    assert result.current_instances == 1
    assert result.target_instances == 2