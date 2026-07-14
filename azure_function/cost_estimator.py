"""
CloudThrift Cost Estimator

Estimates the financial impact of infrastructure scaling decisions
before an action is executed.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any


logger = logging.getLogger("cloudthrift.cost_estimator")


@dataclass(frozen=True)
class CostEstimate:
    current_hourly_cost: float
    target_hourly_cost: float
    hourly_cost_change: float
    estimated_daily_cost_change: float
    estimated_monthly_cost_change: float
    currency: str
    instance_hourly_price: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CostEstimator:
    def __init__(
        self,
        *,
        instance_hourly_price: float = 0.36,
        currency: str = "SAR",
    ) -> None:
        if instance_hourly_price <= 0:
            raise ValueError(
                "Instance hourly price must be greater than zero."
            )

        self.instance_hourly_price = instance_hourly_price
        self.currency = currency

    def estimate(
        self,
        *,
        current_instances: int,
        target_instances: int,
    ) -> CostEstimate:
        if current_instances < 0:
            raise ValueError(
                "Current instance count cannot be negative."
            )

        if target_instances < 0:
            raise ValueError(
                "Target instance count cannot be negative."
            )

        current_hourly_cost = (
            current_instances * self.instance_hourly_price
        )

        target_hourly_cost = (
            target_instances * self.instance_hourly_price
        )

        hourly_cost_change = (
            target_hourly_cost - current_hourly_cost
        )

        estimate = CostEstimate(
            current_hourly_cost=round(
                current_hourly_cost,
                4,
            ),
            target_hourly_cost=round(
                target_hourly_cost,
                4,
            ),
            hourly_cost_change=round(
                hourly_cost_change,
                4,
            ),
            estimated_daily_cost_change=round(
                hourly_cost_change * 24,
                2,
            ),
            estimated_monthly_cost_change=round(
                hourly_cost_change * 24 * 30,
                2,
            ),
            currency=self.currency,
            instance_hourly_price=self.instance_hourly_price,
        )

        logger.info(
            (
                "Cost impact estimated | "
                "Current=%d instances | Target=%d instances | "
                "Hourly change=%.4f %s | Monthly change=%.2f %s"
            ),
            current_instances,
            target_instances,
            estimate.hourly_cost_change,
            estimate.currency,
            estimate.estimated_monthly_cost_change,
            estimate.currency,
        )

        return estimate