import json

from action_executor import ActionExecutor
from decision_engine import CloudState, DecisionEngine


def main() -> None:
    engine = DecisionEngine()
    executor = ActionExecutor()

    test_state = CloudState(
        cpu_percent=5.0,
        network_mbps=2.0,
        requests_per_minute=10,
        current_instances=2,
        budget_used_percent=40.0,
        environment="development",

        cpu_low_duration_minutes=10,
        network_low_duration_minutes=10,
        requests_low_duration_minutes=10,

        minutes_since_last_scale_out=30,
        minutes_since_last_scale_in=30,
        scaling_actions_last_hour=0,
    )

    decision = engine.decide(test_state)

    execution = executor.execute(
        action=decision.action.value,
        current_instances=decision.current_instances,
        target_instances=decision.target_instances,
        dry_run=decision.dry_run,
    )

    print(
        json.dumps(
            {
                "decision": decision.to_dict(),
                "execution_result": execution.to_dict(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()