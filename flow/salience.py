"""Salience scoring and control law utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class SalienceConfig:
    weights: Dict[str, float]
    low_threshold: float = 0.35
    high_threshold: float = 0.7


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def compute_salience(components: Dict[str, float], config: SalienceConfig) -> float:
    total = 0.0
    for key, weight in config.weights.items():
        total += weight * components.get(key, 0.0)
    return clamp(total)


def compute_j_score(
    delta_u: float,
    voi: float,
    optionality: float,
    cost: float,
    risk: float,
    fatigue: float,
    weights: Dict[str, float],
) -> float:
    return (
        delta_u
        + weights.get("voi", 1.0) * voi
        + weights.get("optionality", 1.0) * optionality
        - cost
        - weights.get("risk", 1.0) * risk
        - weights.get("fatigue", 1.0) * fatigue
    )
