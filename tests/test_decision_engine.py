import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FUNCTION_APP = PROJECT_ROOT / "function_app"

sys.path.append(str(FUNCTION_APP))

from decision_engine import CloudState, DecisionEngine


def create_state(
    cpu,
    network,
    requests,
    budget,
    instances=1,
):
    return CloudState(
        cpu_percent=cpu,
        network_mbps=network,
        requests_per_minute=requests,
        current_instances=instances,
        budget_used_percent=budget,
        environment="production",
        cpu_high_duration_minutes=10,
        network_high_duration_minutes=10,
        requests_high_duration_minutes=10,
        cpu_low_duration_minutes=10,
        network_low_duration_minutes=10,
        requests_low_duration_minutes=10,
        minutes_since_last_scale_out=30,
        minutes_since_last_scale_in=30,
        scaling_actions_last_hour=0,
    )


def test_scale_out():
    engine = DecisionEngine()

    state = create_state(
        cpu=85,
        network=90,
        requests=1500,
        budget=40,
    )

    decision = engine.decide(state)

    assert decision.action.name == "SCALE_OUT"


def test_no_action():
    engine = DecisionEngine()

    state = create_state(
        cpu=40,
        network=30,
        requests=300,
        budget=40,
    )

    decision = engine.decide(state)

    assert decision.action.name == "NO_ACTION"