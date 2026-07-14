"""
CloudThrift Audit Logger

Provides immutable, structured audit records for every CloudThrift
orchestration cycle and infrastructure decision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


logger = logging.getLogger("cloudthrift.audit_logger")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIRECTORY = PROJECT_ROOT / "logs"
DEFAULT_AUDIT_FILE = DEFAULT_AUDIT_DIRECTORY / "audit_log.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()

    return value


class AuditLogger:
    def __init__(
        self,
        audit_file: Path | str = DEFAULT_AUDIT_FILE,
    ) -> None:
        self.audit_file = Path(audit_file)
        self.audit_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def write_record(
        self,
        *,
        event_type: str,
        telemetry: Any,
        decision: Any,
        execution_result: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "audit_id": str(uuid4()),
            "event_type": event_type,
            "timestamp_utc": utc_now_iso(),
            "telemetry": serialize_value(telemetry),
            "decision": serialize_value(decision),
            "execution_result": serialize_value(execution_result),
            "metadata": metadata or {},
        }

        try:
            with self.audit_file.open(
                mode="a",
                encoding="utf-8",
            ) as file:
                file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        except OSError as error:
            logger.exception(
                "Failed to write audit record to %s",
                self.audit_file,
            )
            raise RuntimeError(
                "CloudThrift could not persist the audit record."
            ) from error

        logger.info(
            "Audit record written successfully | "
            "audit_id=%s | event_type=%s",
            record["audit_id"],
            event_type,
        )

        return record