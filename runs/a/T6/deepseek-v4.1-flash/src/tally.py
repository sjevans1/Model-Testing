"""Aggregation helpers used by the tenant reporting pipeline."""
from __future__ import annotations

import math


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty sequence")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Middle value (mean of the two middle values for an even-length input)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of empty sequence")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile, pct in [0, 100]."""
    if not 0 <= pct <= 100:
        raise ValueError("pct must be between 0 and 100")
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of empty sequence")
    rank = max(1, min(len(ordered), math.ceil(pct / 100.0 * len(ordered))))
    return ordered[rank - 1]


def summarize(values: list[float]) -> dict:
    """The shape the reporting pipeline consumes."""
    return {"n": len(values), "mean": mean(values), "median": median(values),
            "p90": percentile(values, 90)}
