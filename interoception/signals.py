"""Signal definitions for the interoception layer.

Signals represent internal drive states that can trigger the main agent.
Each signal has semantic meaning beyond just "time to check something."
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class Signal(Enum):
    """Drive signals emitted by the limbic layer.

    These signals represent different types of internal pressure:
    - SOCIAL: Haven't checked interactions in a while, pressure building
    - CURIOSITY: Something might be happening worth knowing about
    - MAINTENANCE: Context is probably getting bloated, need cleanup
    - BOREDOM: Nothing's demanded attention, maybe create something
    - ANXIETY: Something might be wrong, check for problems
    - DRIFT: Outputs have been getting longer/shorter/weirder
    - STALE: Information I'm relying on might have decayed
    - UNCANNY: Something doesn't fit the expected distribution
    - QUIET: Active inhibition - suppress wakeup during off-hours
    """
    SOCIAL = "social"
    CURIOSITY = "curiosity"
    MAINTENANCE = "maintenance"
    BOREDOM = "boredom"
    ANXIETY = "anxiety"
    DRIFT = "drift"
    STALE = "stale"
    UNCANNY = "uncanny"
    QUIET = "quiet"


@dataclass
class SignalConfig:
    """Configuration for a signal type.

    Attributes:
        base_interval_seconds: How long before pressure starts accumulating
        accumulation_rate: How fast pressure builds per second after base_interval
        decay_rate: How fast pressure drops after signal emission (per second)
        emit_threshold: Pressure level that triggers signal emission
        max_pressure: Maximum pressure cap
        jitter_factor: Random variance factor (0.0-1.0) for biological variability
        priority: Signal priority for tie-breaking (higher = more urgent)
        max_interval_seconds: Maximum time before forced emission (cron floor)
    """
    base_interval_seconds: float
    accumulation_rate: float
    decay_rate: float
    emit_threshold: float
    max_pressure: float = 1.5
    jitter_factor: float = 0.15
    priority: int = 5
    max_interval_seconds: Optional[float] = None  # Cron floor - force emit after this


# Default signal configurations
# Tuned based on the discussion in the Moltbook post
DEFAULT_SIGNAL_CONFIGS: Dict[Signal, SignalConfig] = {
    Signal.SOCIAL: SignalConfig(
        base_interval_seconds=1200,      # 20 minutes before pressure starts
        accumulation_rate=0.0008,         # ~0.05 per minute after that
        decay_rate=0.02,                  # Decays quickly after emission
        emit_threshold=0.7,
        priority=7,
        max_interval_seconds=7200,        # Force check every 2 hours max
    ),
    Signal.CURIOSITY: SignalConfig(
        base_interval_seconds=3600,       # 1 hour before pressure starts
        accumulation_rate=0.0003,         # Slower accumulation
        decay_rate=0.015,
        emit_threshold=0.6,
        priority=4,
        max_interval_seconds=14400,       # 4 hours max
    ),
    Signal.MAINTENANCE: SignalConfig(
        base_interval_seconds=10800,      # 3 hours before passive pressure
        accumulation_rate=0.0001,         # Very slow passive accumulation
        decay_rate=0.02,
        emit_threshold=0.75,
        priority=6,
        max_interval_seconds=None,        # No forced emission when healthy
    ),
    Signal.BOREDOM: SignalConfig(
        base_interval_seconds=14400,      # 4 hours before boredom kicks in
        accumulation_rate=0.0002,
        decay_rate=0.01,
        emit_threshold=0.8,
        priority=2,
        max_interval_seconds=21600,       # 6 hours max
    ),
    Signal.ANXIETY: SignalConfig(
        base_interval_seconds=21600,      # 6 hours before passive pressure
        accumulation_rate=0.0001,         # Very slow passive accumulation
        decay_rate=0.03,                  # Decays quickly after emission
        emit_threshold=0.8,
        priority=8,                       # High priority
        max_interval_seconds=None,        # No forced emission when healthy
    ),
    Signal.DRIFT: SignalConfig(
        base_interval_seconds=21600,      # 6 hours before checking for drift
        accumulation_rate=0.0001,
        decay_rate=0.005,
        emit_threshold=0.7,
        priority=3,
        max_interval_seconds=43200,       # 12 hours max
    ),
    Signal.STALE: SignalConfig(
        base_interval_seconds=7200,       # 2 hours
        accumulation_rate=0.0002,
        decay_rate=0.01,
        emit_threshold=0.6,
        priority=4,
        max_interval_seconds=28800,       # 8 hours max
    ),
    Signal.UNCANNY: SignalConfig(
        base_interval_seconds=1800,       # 30 min before passive accumulation starts
        accumulation_rate=0.001,          # Slow passive - should be externally boosted
        decay_rate=0.05,                  # Decays fast after emission
        emit_threshold=0.5,
        priority=9,                       # Highest priority
        max_interval_seconds=None,        # No forced emission - purely reactive
    ),
    Signal.QUIET: SignalConfig(
        base_interval_seconds=0,
        accumulation_rate=0.0,            # Doesn't accumulate naturally
        decay_rate=0.0001,                # Very slow decay
        emit_threshold=0.9,               # Hard to trigger naturally
        priority=10,                      # Overrides everything
        max_interval_seconds=None,
    ),
}


@dataclass
class EmittedSignal:
    """A signal that has been emitted by the limbic layer.

    Contains context about why the signal was emitted.
    """
    signal: Signal
    pressure: float
    reason: str
    context: Dict[str, Any]
    forced: bool = False  # True if emitted due to max_interval (cron floor)

    def __str__(self) -> str:
        forced_str = " [FORCED]" if self.forced else ""
        return f"{self.signal.value}{forced_str} (pressure={self.pressure:.2f}): {self.reason}"
