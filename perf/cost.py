"""Cost of a run, estimated from the resources it used.

Method 1 of the plan: no billing access needed. Dataflow reports what a
job consumed (vCPU time, memory, disk, Streaming Engine data); the
endpoint's replica count over time gives replica-hours. Both are priced
with ``perf/prices.yaml``. The billing export, once enabled, is the check
on this estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PRICES_PATH = Path(__file__).with_name("prices.yaml")


@dataclass(frozen=True)
class CostLine:
    """One priced component of a run's cost."""

    component: str
    quantity: float
    unit: str
    unit_price: float
    cost: float


def load_prices(path: Path = PRICES_PATH) -> dict[str, Any]:
    """Load the price table.

    Args:
        path: YAML file in the ``prices.yaml`` format.

    Returns:
        The parsed table.
    """
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def replica_hours(points: list[tuple[datetime, float]]) -> float:
    """Integrate a replica-count series into replica-hours.

    Each sample's value is held until the next sample (step function);
    the last sample contributes nothing because its duration is unknown.

    Args:
        points: ``(time, replicas)`` samples in any order.

    Returns:
        Replica-hours.
    """
    ordered = sorted(points)
    total_seconds = 0.0
    for (t0, value), (t1, _) in zip(ordered, ordered[1:], strict=False):
        total_seconds += value * (t1 - t0).total_seconds()
    return total_seconds / 3600


def estimate(
    job_metrics: dict[str, float],
    replica_hours_used: float,
    prices: dict[str, Any],
) -> tuple[float | None, list[CostLine]]:
    """Estimate a run's cost.

    Args:
        job_metrics: Dataflow service metrics by name.
        replica_hours_used: Vertex replica-hours (0 for stub runs).
        prices: Price table from :func:`load_prices`.

    Returns:
        ``(total, lines)``. ``total`` is ``None`` when a component that the
        run actually used has no price — an incomplete total would
        understate the cost.
    """
    lines: list[CostLine] = []
    missing = False

    for name, spec in (prices.get("dataflow") or {}).items():
        raw = job_metrics.get(name)
        if raw is None:
            continue
        quantity = raw / float(spec["divisor"])
        price = spec.get("price")
        if price is None:
            missing = missing or quantity > 0
            continue
        lines.append(
            CostLine(name, quantity, str(spec["unit"]), float(price), quantity * price)
        )

    if replica_hours_used > 0:
        price = (prices.get("vertex") or {}).get("replica_hour_price")
        if price is None:
            missing = True
        else:
            lines.append(
                CostLine(
                    "VertexReplicaHours",
                    replica_hours_used,
                    "replica-hour",
                    float(price),
                    replica_hours_used * price,
                )
            )

    if missing:
        return None, lines
    return sum(line.cost for line in lines), lines
