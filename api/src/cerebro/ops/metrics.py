"""Small deterministic metric helpers shared by operational reports."""

from math import ceil
from statistics import median


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "median_seconds": round(median(values), 3) if values else None,
        "p95_seconds": round(nearest_rank(values, 0.95) or 0, 3) if values else None,
    }
