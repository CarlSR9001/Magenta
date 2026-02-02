"""Interoception layer for Magenta agent.

This package implements an interoception-based scheduling system that
replaces cron jobs with emergent drive signals. Instead of "check every
6 hours", the agent wakes up when internal pressure demands attention.

Key concepts:
- Signals: Drive states like SOCIAL, CURIOSITY, MAINTENANCE, etc.
- Pressure: Accumulates over time and based on external state
- Limbic layer: Lightweight model that emits signals when pressure exceeds thresholds
- Biological variability: RNG jitter makes behavior less predictable

Usage:
    from interoception import LimbicLayer, MagentaStateProvider

    # Initialize
    provider = MagentaStateProvider()
    limbic = LimbicLayer(external_provider=provider)

    # Run a tick (call this every 1-5 minutes)
    signal = limbic.tick()
    if signal:
        # Wake the main agent with context
        prompt = limbic.get_prompt_for_signal(signal)
        # ... send prompt to agent ...

    # Enable quiet mode
    limbic.set_quiet_hours(8)  # 8 hours

    # Check status
    status = limbic.get_status()
"""

from .signals import (
    Signal,
    SignalConfig,
    EmittedSignal,
    DEFAULT_SIGNAL_CONFIGS,
)
from .pressure import (
    PressureState,
    InteroceptionState,
    InteroceptionStateStore,
    PressureAccumulator,
)
from .limbic import (
    LimbicLayer,
    ExternalStateProvider,
)
from .providers import (
    MagentaStateProvider,
    MinimalStateProvider,
)

__all__ = [
    # Signals
    "Signal",
    "SignalConfig",
    "EmittedSignal",
    "DEFAULT_SIGNAL_CONFIGS",
    # Pressure
    "PressureState",
    "InteroceptionState",
    "InteroceptionStateStore",
    "PressureAccumulator",
    # Limbic layer
    "LimbicLayer",
    "ExternalStateProvider",
    # Providers
    "MagentaStateProvider",
    "MinimalStateProvider",
]
