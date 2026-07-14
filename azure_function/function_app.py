from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import azure.functions as func


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLOUDTHRIFT_APP_PATH = PROJECT_ROOT / "function_app"

if str(CLOUDTHRIFT_APP_PATH) not in sys.path:
    sys.path.insert(0, str(CLOUDTHRIFT_APP_PATH))

from orchestrator import CloudThriftOrchestrator


app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def cloudthrift_timer(timer: func.TimerRequest) -> None:
    logging.info("CloudThrift scheduled cycle started.")

    if timer.past_due:
        logging.warning("CloudThrift timer execution is past due.")

    try:
        orchestrator = CloudThriftOrchestrator(
            environment="development"
        )

        result = orchestrator.run_cycle()

        logging.info(
            "CloudThrift scheduled cycle completed | result=%s",
            json.dumps(
                result,
                ensure_ascii=False,
                default=str,
            ),
        )

    except Exception:
        logging.exception(
            "CloudThrift scheduled cycle failed."
        )
        raise


@app.function_name(name="cloudthrift_event_handler")
@app.event_grid_trigger(arg_name="event")
def cloudthrift_event_handler(event: func.EventGridEvent) -> None:
    logging.info(
        "CloudThrift Event Grid event received | "
        "event_type=%s | subject=%s | data=%s",
        event.event_type,
        event.subject,
        event.get_json(),
    )

    try:
        orchestrator = CloudThriftOrchestrator(
            environment="development"
        )

        result = orchestrator.run_cycle()

        logging.info(
            "CloudThrift event-driven cycle completed | result=%s",
            json.dumps(
                result,
                ensure_ascii=False,
                default=str,
            ),
        )

    except Exception:
        logging.exception(
            "CloudThrift event-driven cycle failed."
        )
        raise