"""Pressure accumulator system for the interoception layer.

Pressure accumulates based on internal state and time, not external schedules.
This is the core mechanism that makes interoception different from cron.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any, List
import random
import json
from pathlib import Path

from .signals import Signal, SignalConfig, DEFAULT_SIGNAL_CONFIGS, EmittedSignal


@dataclass
class PressureState:
    """State for a single pressure accumulator.

    Tracks the current pressure level and timing information.
    """
    pressure: float = 0.0
    last_updated: Optional[str] = None
    last_emitted: Optional[str] = None
    last_action: Optional[str] = None  # Last time this signal led to an action
    emission_count: int = 0
    known_pending: Dict[str, int] = field(default_factory=dict)  # e.g., {"dms": 3, "mentions": 1}
    last_outcomes: Dict[str, str] = field(default_factory=dict)  # e.g., {"social": "high_engagement"}

    def to_dict(self) -> dict:
        return {
            "pressure": self.pressure,
            "last_updated": self.last_updated,
            "last_emitted": self.last_emitted,
            "last_action": self.last_action,
            "emission_count": self.emission_count,
            "known_pending": self.known_pending,
            "last_outcomes": self.last_outcomes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PressureState":
        return cls(
            pressure=data.get("pressure", 0.0),
            last_updated=data.get("last_updated"),
            last_emitted=data.get("last_emitted"),
            last_action=data.get("last_action"),
            emission_count=data.get("emission_count", 0),
            known_pending=data.get("known_pending", {}),
            last_outcomes=data.get("last_outcomes", {}),
        )


@dataclass
class InteroceptionState:
    """Complete state for the interoception system.

    Tracks all pressure accumulators plus global state.
    """
    pressures: Dict[str, PressureState] = field(default_factory=dict)
    quiet_until: Optional[str] = None  # ISO timestamp for quiet hours
    last_wake: Optional[str] = None
    total_emissions: int = 0
    anomaly_scores: Dict[str, float] = field(default_factory=dict)  # For UNCANNY detection
    output_stats: Dict[str, Any] = field(default_factory=dict)  # For DRIFT detection

    def get_pressure(self, signal: Signal) -> PressureState:
        """Get or create pressure state for a signal."""
        key = signal.value
        if key not in self.pressures:
            self.pressures[key] = PressureState()
        return self.pressures[key]

    def to_dict(self) -> dict:
        return {
            "pressures": {k: v.to_dict() for k, v in self.pressures.items()},
            "quiet_until": self.quiet_until,
            "last_wake": self.last_wake,
            "total_emissions": self.total_emissions,
            "anomaly_scores": self.anomaly_scores,
            "output_stats": self.output_stats,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InteroceptionState":
        pressures = {}
        for k, v in data.get("pressures", {}).items():
            pressures[k] = PressureState.from_dict(v)
        return cls(
            pressures=pressures,
            quiet_until=data.get("quiet_until"),
            last_wake=data.get("last_wake"),
            total_emissions=data.get("total_emissions", 0),
            anomaly_scores=data.get("anomaly_scores", {}),
            output_stats=data.get("output_stats", {}),
        )


class InteroceptionStateStore:
    """Persistent storage for interoception state."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> InteroceptionState:
        if not self.path.exists():
            return InteroceptionState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return InteroceptionState.from_dict(data)
        except Exception:
            return InteroceptionState()

    def save(self, state: InteroceptionState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8"
        )


class PressureAccumulator:
    """Manages pressure accumulation and signal emission.

    This is the core of the interoception layer. It:
    1. Tracks time since last events
    2. Accumulates pressure based on elapsed time and state
    3. Applies RNG jitter for biological variability
    4. Emits signals when pressure exceeds thresholds
    """

    def __init__(
        self,
        configs: Optional[Dict[Signal, SignalConfig]] = None,
        state: Optional[InteroceptionState] = None,
    ):
        self.configs = configs or DEFAULT_SIGNAL_CONFIGS
        self.state = state or InteroceptionState()

    def _apply_jitter(self, value: float, config: SignalConfig) -> float:
        """Apply random jitter for biological variability."""
        if config.jitter_factor <= 0:
            return value
        jitter = random.uniform(-config.jitter_factor, config.jitter_factor)
        return value * (1 + jitter)

    def _time_since(self, iso_timestamp: Optional[str]) -> float:
        """Get seconds since an ISO timestamp."""
        if not iso_timestamp:
            return float('inf')
        try:
            then = datetime.fromisoformat(iso_timestamp)
            now = datetime.now(timezone.utc)
            return (now - then).total_seconds()
        except Exception:
            return float('inf')

    def update_pressure(self, signal: Signal, external_boost: float = 0.0) -> float:
        """Update pressure for a signal based on elapsed time.

        Args:
            signal: The signal to update
            external_boost: Additional pressure from external factors (e.g., pending items)

        Returns:
            The new pressure value
        """
        config = self.configs.get(signal)
        if not config:
            return 0.0

        pressure_state = self.state.get_pressure(signal)
        now = datetime.now(timezone.utc)

        # Calculate time since last update
        time_since_update = self._time_since(pressure_state.last_updated)
        time_since_emission = self._time_since(pressure_state.last_emitted)

        # Base pressure accumulation
        if time_since_emission > config.base_interval_seconds:
            # Past the base interval - start accumulating
            accumulation_time = time_since_emission - config.base_interval_seconds
            if time_since_update < float('inf'):
                # Only accumulate for time since last update
                accumulation_time = min(accumulation_time, time_since_update)

            base_accumulation = accumulation_time * config.accumulation_rate
            base_accumulation = self._apply_jitter(base_accumulation, config)
        else:
            base_accumulation = 0.0

        # Add external boost (e.g., from pending notifications)
        total_accumulation = base_accumulation + external_boost

        # Update pressure
        new_pressure = pressure_state.pressure + total_accumulation
        new_pressure = min(new_pressure, config.max_pressure)

        pressure_state.pressure = new_pressure
        pressure_state.last_updated = now.isoformat()

        return new_pressure

    def decay_pressure(self, signal: Signal) -> float:
        """Decay pressure after signal emission."""
        config = self.configs.get(signal)
        if not config:
            return 0.0

        pressure_state = self.state.get_pressure(signal)
        now = datetime.now(timezone.utc)

        # Reset pressure after emission
        pressure_state.pressure = 0.0
        pressure_state.last_emitted = now.isoformat()
        pressure_state.emission_count += 1

        return pressure_state.pressure

    def should_emit(self, signal: Signal) -> tuple[bool, str, bool]:
        """Check if a signal should be emitted.

        Returns:
            Tuple of (should_emit, reason, is_forced)
        """
        config = self.configs.get(signal)
        if not config:
            return False, "no_config", False

        pressure_state = self.state.get_pressure(signal)
        time_since_emission = self._time_since(pressure_state.last_emitted)

        # Check if quiet mode is active
        if self.is_quiet() and signal != Signal.QUIET:
            return False, "quiet_mode_active", False

        # Cooldowns for high-priority signals to prevent spam loops
        # UNCANNY: prevent re-firing within 10 minutes - no bypass allowed
        # UNCANNY should only fire when there's an external anomaly, not passive accumulation
        if signal == Signal.UNCANNY:
            cooldown_seconds = 600  # 10 minutes - enough time to actually fix the issue
            if time_since_emission < cooldown_seconds:
                return False, f"uncanny_cooldown ({cooldown_seconds - time_since_emission:.0f}s remaining)", False

        # ANXIETY: prevent re-firing within 3 minutes unless errors are spiking
        if signal == Signal.ANXIETY:
            cooldown_seconds = 180  # 3 minutes
            if time_since_emission < cooldown_seconds:
                if pressure_state.pressure < 1.0:  # Above normal threshold
                    return False, f"anxiety_cooldown ({cooldown_seconds - time_since_emission:.0f}s remaining)", False

        # BOREDOM: prevent re-firing within 30 minutes - boredom needs time to actually build
        # This is a safeguard against external boost loops
        if signal == Signal.BOREDOM:
            cooldown_seconds = 1800  # 30 minutes minimum between BOREDOM signals
            if time_since_emission < cooldown_seconds:
                return False, f"boredom_cooldown ({cooldown_seconds - time_since_emission:.0f}s remaining)", False

        # Check forced emission (cron floor)
        if config.max_interval_seconds:
            if time_since_emission >= config.max_interval_seconds:
                return True, f"max_interval_exceeded ({time_since_emission:.0f}s)", True

        # Check pressure threshold
        threshold = self._apply_jitter(config.emit_threshold, config)
        if pressure_state.pressure >= threshold:
            return True, f"pressure_threshold ({pressure_state.pressure:.2f} >= {threshold:.2f})", False

        return False, "below_threshold", False

    def emit_signal(self, signal: Signal, reason: str, forced: bool = False) -> EmittedSignal:
        """Emit a signal and decay its pressure."""
        pressure_state = self.state.get_pressure(signal)
        current_pressure = pressure_state.pressure

        # Build context
        context = {
            "pending": pressure_state.known_pending,
            "last_outcomes": pressure_state.last_outcomes,
            "emission_count": pressure_state.emission_count,
            "time_since_last_emission": self._time_since(pressure_state.last_emitted),
        }

        # Decay pressure
        self.decay_pressure(signal)

        # Update global state
        self.state.total_emissions += 1
        self.state.last_wake = datetime.now(timezone.utc).isoformat()

        return EmittedSignal(
            signal=signal,
            pressure=current_pressure,
            reason=reason,
            context=context,
            forced=forced,
        )

    def is_quiet(self) -> bool:
        """Check if quiet mode is active."""
        if not self.state.quiet_until:
            return False
        try:
            quiet_until = datetime.fromisoformat(self.state.quiet_until)
            return datetime.now(timezone.utc) < quiet_until
        except Exception:
            return False

    def set_quiet(self, duration_hours: float) -> None:
        """Enable quiet mode for a duration."""
        until = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        self.state.quiet_until = until.isoformat()
        # Also set QUIET signal pressure high to emit if checked
        quiet_state = self.state.get_pressure(Signal.QUIET)
        quiet_state.pressure = 1.0

    def clear_quiet(self) -> None:
        """Disable quiet mode."""
        self.state.quiet_until = None
        quiet_state = self.state.get_pressure(Signal.QUIET)
        quiet_state.pressure = 0.0

    def update_pending(self, signal: Signal, pending: Dict[str, int]) -> None:
        """Update known pending items for a signal."""
        pressure_state = self.state.get_pressure(signal)
        pressure_state.known_pending = pending

    def update_outcome(self, signal: Signal, outcome: str) -> None:
        """Record the outcome of acting on a signal."""
        pressure_state = self.state.get_pressure(signal)
        pressure_state.last_outcomes[signal.value] = outcome
        pressure_state.last_action = datetime.now(timezone.utc).isoformat()

    def get_all_pressures(self) -> Dict[Signal, float]:
        """Get current pressure levels for all signals."""
        return {
            signal: self.state.get_pressure(signal).pressure
            for signal in Signal
        }

    def get_status(self) -> Dict[str, Any]:
        """Get a status summary of the interoception system."""
        now = datetime.now(timezone.utc)
        status = {
            "quiet_mode": self.is_quiet(),
            "quiet_until": self.state.quiet_until,
            "total_emissions": self.state.total_emissions,
            "last_wake": self.state.last_wake,
            "signals": {},
        }

        for signal in Signal:
            config = self.configs.get(signal)
            pressure_state = self.state.get_pressure(signal)

            time_since_emission = self._time_since(pressure_state.last_emitted)
            time_until_base = max(0, config.base_interval_seconds - time_since_emission) if config else 0

            status["signals"][signal.value] = {
                "pressure": round(pressure_state.pressure, 3),
                "threshold": config.emit_threshold if config else None,
                "time_since_emission_seconds": round(time_since_emission, 0) if time_since_emission < float('inf') else None,
                "time_until_accumulation_seconds": round(time_until_base, 0),
                "pending": pressure_state.known_pending,
                "emission_count": pressure_state.emission_count,
            }

        return status
